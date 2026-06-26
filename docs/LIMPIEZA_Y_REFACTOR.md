# Limpieza y Refactor — Telev1

> Documento de seguimiento del código muerto, inconsistencias y deuda técnica acumulada.
> El proyecto pasó por varios cambios y "reparaciones" (CSV → PostgreSQL, Ollama → vLLM,
> XTTS → Kokoro → F5) que dejaron código suelto sin uso. Aquí se registra qué quitar,
> qué arreglar y qué tener en cuenta antes de seguir construyendo.
>
> Fecha de auditoría: 2026-06-23

---

## Estado actual real del pipeline (para referencia)

```
scheduler.py  (sincroniza SQL Server → PostgreSQL, dispara /call)
  └── main.py  (/call marca empleado + ordena marcar a baresip)
        └── sip-service: baresip + bridge.py  (cables virtuales PulseAudio cruzados)
              └── WebSocket /ws/audio?id=&duracion=
                    └── call_agent.py  (máquina de estados de states.py)
                          ├── STT:  Faster-Whisper (small, CUDA)
                          ├── LLM:  vLLM / Qwen3.5-2B  (contenedor vllm-service, :8100)
                          └── TTS:  F5-TTS Spanish     (servicio f5, :8881)
```

Máquina de estados real (`states.py`):
`DETECTAR_BUZON → PRESENTACION → ESPERAR_CONFIRMACION → BIENVENIDA → ESPERAR_DUDAS ↔ RESPONDER → DESPEDIDA_OK / DESPEDIDA_ERROR → FINALIZADO`

---

## 🔴 1. Código muerto / legacy (candidato a borrar)

| Archivo | Problema | Acción propuesta |
|---|---|---|
| `backend/app/agent.py` | Contiene **otra clase `CallAgent`** (duplica el nombre de la real). Versión vieja era CSV/Ollama: busca empleado por teléfono, VAD por volumen, prompt inline. **No se importa en ningún lado.** Además llama `db.get_employee_by_phone()` que **no existe** en `database.py`. | Borrar |
| `backend/app/database.py` | `EmployeeRepository` basado en CSV (`/app/data/empleados.csv`), anterior a PostgreSQL. Solo lo usa el `agent.py` muerto y bloques comentados de `call_agent.py`. | Borrar (tras quitar `agent.py`) |
| `backend/app/audio.py` | Archivo **vacío** (0 líneas). | Borrar |

> Nota: el código vivo del agente es `backend/app/call_agent.py`. No confundir.

### Código comentado dentro de archivos vivos (limpiar inline)
- `backend/app/call_agent.py`:
  - Bloque grande comentado del `__init__` viejo con CSV (`# USANDO CSV`, líneas ~39-76).
  - `SMART_FILLERS` comentado (~29-35).
  - `_reproducir_muletilla` está deshabilitado por bug pero el método sigue ahí; la llamada está comentada en `_estado_responder`.
- `backend/app/llm.py`: bloque `_ensure_model_exists` (lógica de pull de Ollama) comentado completo (~17-42).
- `docker-compose.yml`: bloques comentados de `gemini-tts`, `xtts`, `ollama`, `kokoro`. (Mantener mientras sean alternativas reales; documentar que están desactivados.)

---

## 🔴 2. Documentación desincronizada con la realidad

| Doc | Dice | Realidad |
|---|---|---|
| `CLAUDE.md` | TTS = XTTS-v2 (problema de latencia por no-streaming) | TTS = **F5-TTS Spanish** (streaming por oraciones) |
| `AGENTS.md` | LLM = Ollama, TTS = Coqui XTTS | LLM = **vLLM / Qwen3.5-2B**, TTS = **F5** |
| `AGENTS.md` / `CLAUDE.md` | Ruta `/mnt/data/salesland/Telev1` | Ruta real `/mnt/DATOS/salesland/TELEV1` |

**Acción:** actualizar ambos docs para reflejar F5 + vLLM + rutas reales antes de planear mejoras sobre ellos.

---

## 🔴 3. Bugs latentes / riesgos

### 3.1 Deadlock del scheduler por estado `EN_LLAMADA` colgado
- El scheduler marca al empleado como `EN_LLAMADA` **antes** de llamar, y `hay_llamada_activa()` **bloquea TODAS las llamadas** mientras exista alguien en ese estado.
- Si una llamada termina de forma anómala (baresip queda `ESTABLISHED` pero el WS nunca conecta, o el backend muere a mitad de llamada), **nadie resetea ese `EN_LLAMADA`** → el scheduler se traba indefinidamente.
- El `finally` de `iniciar_conversacion()` cubre el caso normal (marca `FALLIDO`), pero **no** el caso en que el agente nunca arrancó.
- **Propuesta:** watchdog que devuelva a `PENDIENTE` cualquier `EN_LLAMADA` con antigüedad > X minutos (consulta por `actualizado_en`). Implementar en `scheduler.py` o como query periódica.

### 3.2 `marcar_intento_fallido` — INTERVAL con parámetro
- En `postgres_db.py`: `proxima_llamada = CURRENT_TIMESTAMP + INTERVAL '%s minutes'` con `(minutos_espera,)`. Funciona, pero es frágil (el `%s` va dentro del literal SQL). **Preferible** `CURRENT_TIMESTAMP + make_interval(mins => %s)` para que sea robusto.

---

## 🟡 4. Dependencias y build con peso muerto

### `backend/requirements.txt`
- `openai-whisper==20250625` **y** `faster-whisper==1.2.1` ambos instalados, pero `USE_FASTER_WHISPER=true` → openai-whisper no se usa (instalación pesada). **Quitar openai-whisper** (y la clase `SpeechToText` de `stt.py` si se confirma que no se vuelve a openai-whisper).
- `pyodbc==5.3.0` instalado pero el código usa `pymssql`. **Quitar pyodbc.**
- `sqlalchemy` instalado pero no se usa en el código actual. **Revisar / quitar.**
- `unixodbc`/`unixodbc-dev` en `backend/Dockerfile` solo hacían falta para pyodbc → se pueden quitar si se elimina pyodbc.

### Volumen `whisper_cache`
- `docker-compose.yml` monta `whisper_cache:/root/.cache/whisper`, pero **faster-whisper descarga a `~/.cache/huggingface`**, no a esa ruta → el modelo **se re-descarga en cada rebuild**.
- **Propuesta:** montar un volumen en `/root/.cache/huggingface` (o `HF_HOME`) para cachear el modelo de faster-whisper.

### Imagen base backend
- `ffmpeg` sigue en el Dockerfile. Se usa en `_audio_to_pcm` (rutas no-streaming: muletilla/fallback). Mantener mientras esos paths existan.

---

## 🟡 5. Inconsistencias menores

- **Identidad del asistente** (`prompts.py`): el system prompt dice que se llama **"Jorge"** pero también lo describe como **"asistente telefónica"** (femenino), y `llm.py::_limpiar_respuesta` filtra tanto `Ana:` como `Jorge:`. Unificar nombre/género.
- **Prompt redundante**: el system prompt empieza con `/no_think` y además se manda `chat_template_kwargs.enable_thinking: False`. Redundante (inofensivo). Confirmar cuál respeta el modelo y dejar uno.
- **`init.sql`**: el comentario de la columna `estado` lista `PENDIENTE, EXITO, TERMINADO` pero el código usa también `EN_LLAMADA`. Y la tabla `llamadas.resultado` usa `en_curso`/`completada`/`fallida`. Documentar los valores reales en el esquema.
- **`call_agent.py`**: `IntentDetector()` y `self.intent_detector` se instancian **dos veces** en `__init__` (líneas ~84 y ~109). Dejar una.
- **`call_agent.py`**: imports duplicados de `time` (líneas 22 y 24) e imports locales repetidos de `numpy`/`scipy` dentro de varios métodos. Consolidar arriba.
- **`_es_despedida` / `_es_negacion_simple` / `_es_backchannel`**: hay mucha lógica heurística solapada y parcialmente sin usar (`_es_despedida`, `_es_negacion_simple` parecen no llamarse). Auditar cuáles están vivas y consolidar.

---

## 🟢 6. Faltantes tras clonar (no es deuda, es setup)

| Faltante | Impacto | Origen |
|---|---|---|
| `f5-service/voices/referencia_24k.wav` | **Crítico**: sin él F5 responde 503 → no hay voz | gitignored por `*.wav` |
| `f5-service/cache/` vacío | Se descarga el modelo F5 al primer arranque (~min) | esperado |
| `database/data/` vacío | Postgres lo crea con `init.sql` | esperado |
| `kokoro-service/`, `xtts-service/models/` | No necesarios (backends desactivados) | gitignored |

> `.env` y `sip-service/accounts` (credenciales SIP) **sí** están presentes.

---

## Orden de ejecución propuesto

1. **Limpieza de código muerto** — borrar `agent.py`, `database.py`, `audio.py`; quitar bloques comentados muertos. (Bajo riesgo, despeja terreno.)
2. **Actualizar `CLAUDE.md` / `AGENTS.md`** — reflejar F5 + vLLM + rutas reales.
3. **Watchdog de `EN_LLAMADA`** — evitar el deadlock del scheduler en producción.
4. **Adelgazar dependencias** — quitar openai-whisper / pyodbc / sqlalchemy; arreglar cache de whisper.
5. **Inconsistencias menores** — identidad del asistente, duplicados en `__init__`, esquema documentado.
6. (Después) Mejoras de fondo: latencia, calidad de voz, flujo conversacional.

---

## Pendiente de definir con el equipo
- ¿Se descarta definitivamente XTTS/Kokoro/Gemini, o se mantienen como alternativas conmutables? (Afecta cuánto código TTS conservar en `tts.py`.)
- ¿Se vuelve alguna vez a openai-whisper? (Afecta si se borra la clase `SpeechToText`.)
- Confirmar nombre/género oficial del asistente (Jorge vs. femenino).
