# Limpieza y Refactor — Telev1 (backend)

> Auditoría **archivo por archivo** del `/backend` antes de integrar el RAG.
> El proyecto pasó por varias migraciones (CSV→PostgreSQL, Ollama→vLLM, XTTS→Kokoro→F5→CosyVoice3)
> que dejaron código suelto. Aquí se registra qué borrar, qué arreglar y **dónde cae el RAG**.
>
> Auditoría inicial: 2026-06-23 · **Re-auditoría completa verificada: 2026-06-26**
> Método: lectura de los 14 archivos + verificación de call-sites con grep (no suposiciones).

---

## Estado actual real del pipeline (verificado)

```
scheduler.py  (SQL Server → PostgreSQL, dispara POST /call cada 30s, 1 a la vez)
  └── main.py  (/call → marca + ordena marcar a sip-service; WS /ws/audio?id=&duracion=)
        └── sip-service: baresip + bridge.py
              └── call_agent.py  (máquina de estados de states.py)
                    ├── STT:  Faster-Whisper (small, CUDA)         app/stt.py
                    ├── LLM:  vLLM / Qwen3.5-2B fp8 (:8100)        app/llm.py
                    └── TTS:  CosyVoice3 (:8030, TTS_BACKEND=cosyvoice)  app/tts.py
```

Máquina de estados (`states.py`):
`DETECTAR_BUZON → PRESENTACION → ESPERAR_CONFIRMACION → BIENVENIDA → ESPERAR_DUDAS ↔ RESPONDER
→ DESPEDIDA_OK / DESPEDIDA_ERROR → FINALIZADO`

**Archivos vivos:** main.py, scheduler.py, app/{call_agent,llm,tts,stt,vad,prompts,intent_detector,
states,postgres_db,sqlserver_db}.py
**Archivos muertos:** app/{agent,database,audio}.py (ver §1).

---

## 🔴 1. Código muerto / legacy (borrar)

### Módulos completos
| Archivo | Evidencia (verificada) | Acción |
|---|---|---|
| `app/agent.py` | Clase `CallAgent` vieja (CSV/Ollama, busca por teléfono, VAD por volumen, TTS MP3+ffmpeg). **Nadie la importa**; llama `get_employee_by_phone()` inexistente. | **Borrar** |
| `app/database.py` | `EmployeeRepository` (CSV con `pandas`). Único consumidor = `agent.py` (muerto). `_get_from_sql` sin implementar. | **Borrar** (tras agent.py) |
| `app/audio.py` | Vacío (0 líneas). | **Borrar** |

### Métodos muertos dentro de `call_agent.py` (0 call-sites reales — verificado)
**Clúster del reproductor viejo (era MP3/ffmpeg) — TODO muerto:**
- `_hablar_con_streaming` (≠ `_real`) — 0 llamadas. Es la raíz del clúster.
- `_generar_audio`, `_reproducir`, `_limpiar_texto_para_tts`, `_audio_to_pcm` — solo se llaman entre sí
  o desde código muerto. (El camino vivo es `_hablar_con_streaming_real` / `_hablar_sin_barge_in`.)
- `_reproducir_muletilla` — su llamada está comentada (línea 571). `SMART_FILLERS` comentado (29-35).

**Helpers heurísticos duplicados/sin uso:**
- `_es_backchannel`, `_es_negacion_simple`, `_es_despedida` — **0 call-sites**. (Vivos sí usados:
  `_es_confirmacion_o_backchannel`, `_es_despedida_explicita`, `_es_confirmacion`, `_es_negacion`.)

> ⚠️ NO tocar (verificado vivos): `_obtener_llamada_activa`, `_es_confirmacion`, `_es_negacion`,
> `_hablar_con_streaming_real`, `_hablar_sin_barge_in`, `_hablar_frases`.

### Bloques comentados dentro de archivos vivos
- `call_agent.py`: `__init__` CSV viejo (39-77), `from app.database import` (8), `SMART_FILLERS` (29-35),
  import `time` **duplicado** (22 y 24), `self.intent_detector = IntentDetector()` **duplicado** (84 y 109),
  `import numpy as np` local repetido (354/445/1145/1201; ya está en el top, línea 21).
- `llm.py`: `_ensure_model_exists` (pull de Ollama) comentado (17-42); `import json` e `import requests`
  sin uso (era Ollama; hoy usa httpx).
- `prompts.py`: bloque comentado final (292-302).

---

## 🔴 2. Dependencias y build con peso muerto

### `requirements.txt`
| Paquete | Por qué sobra | Acción |
|---|---|---|
| `openai-whisper==20250625` | `USE_FASTER_WHISPER=true` → no se usa. PERO `stt.py` hace `import whisper` en el top (línea 1) y define `SpeechToText` (openai-whisper). | Quitar paquete **+** quitar `import whisper`, la clase `SpeechToText` y la rama `else` de `get_stt()` |
| `pandas==3.0.1` | Solo lo usa `database.py` (muerto). | Quitar (tras borrar database.py) |
| `pyodbc==5.3.0` | El código usa `pymssql`. | Quitar |
| `sqlalchemy` | Sin uso (solo en comentario de database.py). | Quitar |

### `backend/Dockerfile`
- `unixodbc` / `unixodbc-dev` → solo para pyodbc. Quitar al quitar pyodbc.
- `ffmpeg` → en código vivo **ya no se usa** (solo el clúster MP3 muerto vía `_audio_to_pcm`).
  ⚠️ **Verificar** que faster-whisper no lo necesita al leer el `.wav` temporal antes de quitarlo.
- `git` → revisar si hace falta (no se instala nada por git en requirements).

### Volumen `whisper_cache` (docker-compose.yml)
- Monta `whisper_cache:/root/.cache/whisper`, pero faster-whisper baja a `~/.cache/huggingface`
  → el modelo **se re-descarga en cada rebuild**. Montar volumen en `/root/.cache/huggingface` (o `HF_HOME`).

---

## 🔴 3. Bugs / riesgos latentes

| # | Dónde | Problema | Propuesta |
|---|---|---|---|
| 3.1 | `scheduler.py` + `postgres_db.py` | **Deadlock EN_LLAMADA**: se marca `EN_LLAMADA` antes de llamar y `hay_llamada_activa()` bloquea TODO. Si una llamada muere sin resetear, el scheduler se traba para siempre. El `finally` de `iniciar_conversacion` no cubre el caso "el agente nunca arrancó". | Watchdog: devolver a `PENDIENTE` cualquier `EN_LLAMADA` con `actualizado_en` > X min |
| 3.2 | `scheduler.py` (94-97) | `esta_en_horario()` está **comentado** en `procesar_cola` → llama 24/7. `HORARIO_INICIO/FIN` y la función quedan sin efecto. | Decidir: reactivar gate u quitar la función |
| 3.3 | `postgres_db.py::marcar_intento_fallido` | `INTERVAL '%s minutes'` con parámetro dentro del literal. Frágil. | `CURRENT_TIMESTAMP + make_interval(mins => %s)` |
| 3.4 | `call_agent.py::_actualizar_resumen` (1542-58) | `nuevo_resumen` solo se asigna dentro del `if historial_para_resumir:`; si está vacío → `NameError` en 1555. | Inicializar `nuevo_resumen = ""` antes del if |
| 3.5 | `stt.py` | `_es_texto_valido` está **duplicado** idéntico en `SpeechToText` y `FasterWhisperSTT`. | Extraer a función/módulo compartido |

---

## 🟡 4. Inconsistencias menores
- **Identidad del asistente** (`prompts.py`): el prompt dice **"Jorge"** pero también "asistente telefónic**a**"
  (femenino); `llm.py::_limpiar_respuesta` filtra `Ana:` **y** `Jorge:`. Unificar nombre/género.
- **Doble anti-thinking**: el prompt empieza con `/no_think` Y se manda `enable_thinking: False`. Redundante.
- **`init.sql`**: el comentario de `estado` lista `PENDIENTE, EXITO, TERMINADO` pero el código usa también
  `EN_LLAMADA`/`FALLIDO`; `llamadas.resultado` usa `en_curso`/`completada`/`fallida`. Documentar valores reales.
- **`turnos_desde_ultimo_resumen`** (call_agent): se setea/resetea pero el gate real usa `len(historial_llm)>=6`. Estado sin uso.
- **`sqlserver_db.obtener_max_id`**: definido pero el scheduler usa `obtener_nuevos_empleados`. Revisar si se usa.
- **Docs raíz** (`CLAUDE.md`/`AGENTS.md`): dicen XTTS/Ollama y ruta `/mnt/data/...`. Realidad: CosyVoice3 +
  vLLM + `/mnt/DATOS/...`. Actualizar.

---

## ⭐ 5. MAPA DE CIRUGÍA DEL RAG (dónde caen los cambios)

Hoy la "correa" anti-alucinación está **dispersa en 3 sitios** (por eso conviene limpiar antes):
1. `intent_detector.py` (filtros por keywords): `es_pregunta_fuera_de_tema`, `es_respuesta_incoherente`
   (en `_estado_esperar_dudas`); `es_tema_permitido` + `detectar_categoria` (en `_estado_responder`).
   ⚠️ `es_permitido` se **calcula pero NO se usa** para frenar (call_agent línea 562 = gate muerto).
2. `prompts.py::get_system_prompt_llm`: prompt gigante con TODOS los datos + reglas + "TEMAS PROHIBIDOS".
3. `llm.py::_limpiar_respuesta`: detección de "prompt leak" + recorte.

**El RAG las colapsa en UN gate (umbral de recuperación).** Puntos de inserción:

| Archivo | Cambio |
|---|---|
| `call_agent._estado_responder` (551-626) | **Cirugía principal.** Hoy: arma prompt gigante → `self.llm.generate_response`. Pasa a: pre-filtro incoherencia → `rag.consultar(duda)` → declinar **o** redactar-grounded → validar → `_hablar_con_streaming_real`. |
| **NUEVO `app/rag_client.py`** | Cliente fino a `POST /chat/rrhh` (gemelo de `tts.py`/`llm.py`). |
| `prompts.py` | `get_system_prompt_llm` se adelgaza a rol+estilo+reglas; `EMPRESA_INFO` migra al KB (`rrhh_onboarding`). |
| `intent_detector.py` | Conservar `es_respuesta_incoherente` (pre-filtro anti-basura de Whisper); retirar `es_tema_permitido`/`es_pregunta_fuera_de_tema`/`detectar_categoria` (los reemplaza el umbral del RAG). |
| `llm.py` | Bajar `temperature 0.7 → ~0.3`. En el camino responder ya no se llama desde el backend (lo llama el RAG); `summarize` se mantiene. |

> Plan funcional del RAG: `docs/INTEGRACION_RAG_RRHH.md`. Esto es solo el mapa de archivos.

---

## Orden propuesto (cada fase = bajo riesgo + 1 llamada de prueba)

- [x] **F5 + Kokoro eliminados** (2026-06-26): de `tts.py`, `docker-compose.yml` y carpeta `f5-service/`.
      Quedan conmutables: `cosyvoice` (activo), `xtts`, `gemini`. Rollback solo por git.
1. [x] **Borrar módulos muertos** (2026-06-26): `agent.py`, `database.py`, `audio.py`.
2. [x] **Limpiar `call_agent.py`** (2026-06-26): clúster MP3 muerto + muletilla + helpers 0-uso +
       duplicados (`time`, `intent_detector`, `numpy` locales) + bloques comentados.
       **`call_agent.py`: 1558 → 1165 líneas.** Los 13 .py parsean, 0 referencias colgadas.
       ✅ Validación con llamada real: la limpieza no rompió nada. (La llamada disparó un OOM por
       presupuesto de GPU, NO por la limpieza — ya RESUELTO, ver "BLOQUEANTE VRAM" abajo.)
3. [x] **Limpiar `llm.py` / `prompts.py`** (2026-06-30): `llm.py` 288→258 (quitados `import json`/`import requests`,
       el bloque comentado `_ensure_model_exists` de Ollama y un comentario residual); `prompts.py` 301→289
       (bloque comentado muerto del final). Sintaxis OK, 0 residuales. `EMPRESA_INFO`/`TEMAS_*` se conservan
       (semilla del RAG, ya capturada en `PROMPT_ACTUAL_Y_SEED_RAG.md`). **`temperature` se queda en 0.7**
       → se baja a ~0.3 SOLO al integrar el RAG (a 0.3 pierde naturalidad mientras el LLM siga siendo la fuente).
4. [x] **Adelgazar deps + Dockerfile** (HECHO 2026-06-30, rebuild verificado 2026-07-01 — STT carga limpio en CUDA
   sin ffmpeg; ✅ falta solo confirmar una transcripción en llamada real, bajo riesgo. Bonus 2026-07-01: cache de
   wetext de CosyVoice persistida en volumen `cosyvoice_modelscope` — ojo, `cosyvoice_models` conserva su
   `name: cosyvoice-service_cosyvoice_models`; NO insertar volúmenes entre esa clave y su `name:`):
       - `requirements.txt`: quitados `openai-whisper`, `pandas`, `sqlalchemy`, `pyodbc`. (`faster-whisper`, `requests`,
         `psycopg2-binary`, `pymssql` **se quedan** — verificado que se usan vivos.)
       - `stt.py` 278→144: fuera `import whisper` + clase `SpeechToText`; `get_stt()` ahora usa faster-whisper
         **incondicional** (eliminado el gate `USE_FASTER_WHISPER`). Bonus: se elimina la duplicación de
         `_es_texto_valido` → resuelto de paso el punto 3.5 de Fase 5.
       - `docker-compose.yml`: **bug de cache arreglado** (`whisper_cache` apuntaba a `/root/.cache/whisper` de
         openai-whisper → repuntado a `/root/.cache/huggingface`, que es donde faster-whisper descarga; antes
         re-descargaba ~450 MB en cada recreación). Envs muertas quitadas: `WHISPER_DEVICE`, `USE_FASTER_WHISPER` (0 lecturas).
       - `Dockerfile`: quitados `ffmpeg` (faster-whisper usa PyAV, no el binario), `unixodbc`, `unixodbc-dev` (eran de `pyodbc`).
       - ⚠️⚠️ **CORRECCIÓN IMPORTANTE:** `app/sqlserver_db.py` + `pymssql` **NO son código muerto** — los usa
         `backend/scheduler.py` (`sincronizar_empleados()`) para traer empleados nuevos de **SQL Server → PostgreSQL**
         cada 5 min. Casi los borro por un grep incompleto (solo miré `app/`+`main.py`, y `scheduler.py` está en la raíz
         de `backend/`). **NO TOCAR.** El flujo real: SQL Server = fuente de empleados nuevos → scheduler sincroniza a
         PostgreSQL → backend/llamadas leen de PostgreSQL.
5. [x] **Bugs** (HECHO 2026-07-01, bind-mounted → solo reiniciar backend+scheduler para que tome):
       - **3.1 watchdog EN_LLAMADA**: `marcar_en_llamada` ahora setea `actualizado_en`; nuevo `resetear_llamadas_colgadas(minutos)`
         en `postgres_db.py` devuelve a PENDIENTE los `EN_LLAMADA` colgados; el scheduler lo llama cada poll con
         `WATCHDOG_MINUTOS` (env, default 10). Ya no se traba la cola si una llamada muere sin resetear.
       - **3.3 make_interval**: `marcar_intento_fallido` usa `make_interval(mins => %s)` (adiós al `%s` dentro del literal).
       - **3.4 nuevo_resumen**: inicializado `= ""` antes del `if` → sin `NameError` si el historial sale sin 'assistant'.
       - **3.5** ya resuelto en Fase 4 (borrada la clase duplicada).
       - **3.2 gate de horario: NO se toca** — no está muerto, está "de descanso"; se reactiva para producción (no debe llamar 24/7).
6. [x] **Inconsistencias** (HECHO 2026-07-01, bind-mounted → reiniciar backend):
       - Identidad **Jorge**: corregidas las auto-referencias femeninas en `prompts.py` (CÁLIDA→CÁLIDO, EMPÁTICA→EMPÁTICO,
         concisa→conciso). (Las "cálida" que quedan modifican "forma"/"estructura" = gramática correcta, no género.)
       - `/no_think` quitado del prompt (redundante: las 4 llamadas ya pasan `enable_thinking: False` + `_limpiar_respuesta` filtra `<think>`).
       - `database/init.sql` documentado: `empleados.estado` = PENDIENTE·EN_LLAMADA·EXITO·TERMINADO (faltaba EN_LLAMADA);
         `llamadas.resultado` = en_curso·completada·fallida·buzon.
       - Gate de horario: **NO reactivado** (de descanso, va para producción — decisión del usuario).

> **✅ REFACTOR COMPLETO (Fases 1-6).** Terreno limpio para el RAG. Siguiente = punto 7.
7. [ ] **(Después) RAG** sobre terreno limpio: ver §5 + `INTEGRACION_RAG_RRHH.md`.

> Probar tras 1-2 y tras 4 con una llamada real (no romper el flujo de voz que ya funciona).

---

## ✅ BLOQUEANTE VRAM — RESUELTO (2026-06-30, verificado en llamada real)

**Descubierto 2026-06-26:** la llamada de prueba destapó un **CUDA Out Of Memory** en CosyVoice
(`llm_job`) en el pico de síntesis. La limpieza Fase 1+2 NO tuvo culpa (todo era código muerto).

**Fix aplicado:** bajar vLLM `--gpu-memory-utilization 0.50 → 0.46` en
`/mnt/DATOS/salesland/AI_SERVICE/docker-compose.yml` + `docker compose up -d --force-recreate`.
**Solo eso bastó.** NO hizo falta el paso 2 (`expandable_segments`) ni el 3 (RAG a CPU): quedan en reserva.

**Por qué funciona (medido, no estimado):**
- A 0.50: KV cache 67,536 tok → concurrencia **25.3x**. A 0.46: KV 40,736 tok → **15.2x**.
  Necesitamos ~8 simultáneas (3 teleop + 3-5 GLPI) → **15.2x es cómodo, sobra**.
- `gpu_memory_utilization` cambia el **tamaño del KV** (libera VRAM); `max_model_len` cambiaría
  cuánto **pide** cada llamada. Solo tocamos la primera; `max_model_len` sigue en **4096** (sin tocar,
  para no arriesgar truncar prompts largos del bot GLPI — es lever de reserva si algún día aprieta).
- Footprint vLLM: 5,992 MiB en reposo → **6,648 MiB caliente** (warmup +656 MiB en la 1ª consulta, estable en la 2ª).

**Reparto real verificado (4 consumidores cargados, post-llamada):**
| Componente | VRAM |
|---|---|
| vLLM (Qwen3.5-2B fp8, **0.46**, caliente) | 6,650 MiB |
| CosyVoice | 3,958 MiB |
| Whisper (backend STT) | 978 MiB |
| RAG (`rag-api`, embeddings CUDA) | 722 MiB |
| **Total cargado** | **12,334 MiB / 16,303** → ~3,548 libres |

**Resultado de la llamada:** ✅ sin OOM · voz bien, sin cortes · latencia **~3s (a veces menos)**, mejor que antes.

**⚠️ MATICES ABIERTOS (vigilar, no bloqueantes):**
1. **Pico observado ~14,000 MiB** en un momento de la síntesis (quedaron ~2,300 libres). No reventó,
   pero el margen en el pico es más ajustado que los 3,548 "en reposo cargado". Si se mete más presión, vigilar.
2. **Solo se probó UNA llamada.** La concurrencia de vLLM (15.2x) cubre 8, pero **la VRAM de CosyVoice
   bajo síntesis SIMULTÁNEA de varias llamadas no está probada** — si CosyVoice no batchea y serializa/replica
   el pico, 3-8 síntesis a la vez podrían apilarse. Pendiente: la prueba "VRAM casa llena" de `INTEGRACION_RAG_RRHH.md` §6.
3. **Warning onnxruntime en CosyVoice** (`libcudnn.so.8: cannot open shared object file`): cae a CPU para
   un componente (prob. embedding de voz). No fatal, voz cacheada (`spk_id=salesland`) casi no lo usa. Limpieza opcional.

**Leveres de reserva (si los matices aprietan):** `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` en
`cosyvoice` (anti-fragmentación) · `max_model_len 4096→3072/2048` (sube concurrencia por token) ·
embeddings RAG a CPU (libera ~722 MB; el usuario NO quiere esta, prioriza latencia).

---

## Decisiones a confirmar contigo
- ¿Se descartan definitivamente XTTS/Kokoro/Gemini/F5, o se conservan como backends conmutables en `tts.py`?
  (Hoy `tts.py` soporta 5; CosyVoice es el activo.)
- ¿Se vuelve alguna vez a openai-whisper? (Define si borramos la clase `SpeechToText` + `import whisper`.)
- Nombre/género oficial del asistente (Jorge vs. femenino).
- ¿Reactivar el gate de horario (`esta_en_horario`) o quitarlo?
