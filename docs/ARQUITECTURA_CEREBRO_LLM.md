# Arquitectura objetivo: el "Cerebro" del teleoperador

> **Creado: 2026-07-03.** Documento de diseño. NO se toca código hasta revisarlo y aprobarlo.
> Objetivo: reorganizar la **capa de decisión** (entendimiento + diálogo) sin rehacer el proyecto.
> Reemplaza las 8 funciones de detección por palabras por **un único manejador de turno con el LLM**.
> Complementa a `docs/PLAN_TURNTAKING_NATURALIDAD.md` (turn-taking) e `INTEGRACION_RAG_RRHH.md` (conocimiento).

---

## 0. Principio: no rehacer el proyecto, rehacer el cerebro

La plomería cara (SIP↔WS↔audio, CosyVoice, vLLM, Whisper, buzón, barge-in, Postgres) **funciona y se queda**.
El dolor vive en **una sola capa**: la decisión "adivinando por palabras". Rehacer el proyecto resetea el
progreso sin resolver ninguno de los problemas (Whisper seguiría alucinando, CosyVoice igual de rápido).
Se rehace **el 20% del código que causa el 80% de la frustración**.

---

## 1. ⚠️ Restricción crítica: el LLM 2B es COMPARTIDO con el bot de GLPI (WhatsApp)

El mismo vLLM/Qwen-2B (`172.17.0.1:8100`) atiende al teleoperador **y** al bot de WhatsApp de GLPI.
Esto fija reglas de diseño **no negociables**:

| Regla | Por qué | Cómo se respeta |
|---|---|---|
| **No cambiar la config del server vLLM** | Rompería a GLPI | Todo lo nuevo va **por-request** (en el body de cada llamada) |
| **Guided decoding per-request** | Forzar formato sin afectar a otros clientes | Usar `guided_json`/`extra_body` en NUESTRAS llamadas; GLPI no se entera |
| **No cambiar el modelo** | GLPI depende de Qwen-2B | El diseño debe funcionar **dentro de un 2B** (por eso guided decoding) |
| **Presupuesto de carga/latencia compartido** | Si GLPI satura, subimos latencia | **No añadir llamadas**: fusionar intención+respuesta en la que ya hacemos |
| **VRAM ya contabilizada** | El server es único, no levantamos otro | Cero VRAM nueva: reusamos el endpoint existente |

> Traducción práctica: nuestra re-arquitectura **no añade carga ni toca infraestructura compartida**.
> Cambia *cómo pedimos* la respuesta, no *el motor*.

---

## 2. Vista por capas (qué se queda / qué cambia)

| Capa | Hoy | Acción |
|---|---|---|
| Transporte SIP/WS/audio | Funciona | **Se queda igual** |
| STT (Whisper) | Alucina en silencio/ruido | **Se endurece** (anti-alucinación + gate por VAD) |
| **Entendimiento + diálogo** | 8 funciones de listas de palabras | **SE REHACE** → manejador de turno LLM |
| Máquina de estados | Mezcla lógica crítica + palabras | **Se adelgaza** a esqueleto de seguridad |
| TTS (CosyVoice) | Funciona, 1er chunk ~1.5s | **Se queda**, se afina el primer chunk |
| VAD / turn-taking | Funciona, espera ~1s de silencio | **Se afina** el corte (ya iniciado en 2a) |
| Postgres / scheduler | Funciona | **Se queda igual** |

Se rehace **una** capa, no siete.

---

## 3. El corazón: el "manejador de turno" (turn-handler)

### Idea (REVISADA — ver hallazgo)
Cada turno son **dos pasos**, NO una sola llamada:
1. **Clasificar** con `guided_choice` (prompt clasificador puro) → `intent` (una etiqueta del set del estado).
2. **Generar respuesta SOLO si hace falta hablar** (`PREGUNTA` / `FUERA_DE_TEMA`). Para
   `DESPEDIDA` / `ACK` / `CALIBRACION` / `CONFIRMA` / `NIEGA` el esqueleto ya tiene la transición o la frase
   canned → **no se genera nada.** `terminar` se deduce del intent (true solo en DESPEDIDA).

> ⚠️ **HALLAZGO (probado 2026-07 con `scripts/test_guided_json.py`): NO fusionar clasificar+generar en un
> solo `guided_json`.** `guided_json` SÍ funciona técnicamente (6/6 JSON válido), PERO pedirle al 2B
> `{intent, respuesta, terminar}` en una salida **degrada la clasificación de 98.3% → 50%**: el modelo se
> pone en modo "asistente cálido" y afloja las etiquetas (ej. "eso sería todo" → `ACK` con `terminar=false`,
> ¡no colgaría!; "¿dónde queda la oficina?" → `FUERA_DE_TEMA` aunque responda la dirección). La generación
> **contamina** la clasificación. **Solución: separar** — clasificar aislado (guided_choice, 98.3%) y generar aparte.

### Por qué gana
1. **Despedida directa, en cualquier forma.** El clasificador entiende *significado*: "eso sería todo",
   "ya estamos", "nada más por ahora" → todas `DESPEDIDA`. **Se borran las listas de palabras.**
2. **Latencia igual o MENOR** (revisado): clasificar es **baratísimo** (~84ms). Solo se genera (~600ms) en
   los turnos que responden. Para `DESPEDIDA`/`ACK`/`CALIBRACION` **no se genera** → más rápido que hoy
   (hoy siempre hay una llamada de ~600ms). No se "fusionan dos"; se **evita** la generación cuando no toca.
3. **Menos brittle:** el clasificador entiende **contexto completo**, no fragmentos de palabras. (El input
   basura sigue siendo HARD; se mitiga con etapa + confianza + confirmación, no se elimina.)
4. **Fiable en 2B:** `guided_choice` fuerza la salida a una etiqueta del set; clasificación pura → 98.3% / 100% estable.

### Cómo se pide a vLLM (por-request, no afecta a GLPI)
```python
# Paso 1 — clasificar (llm.py: clasificar_turno)
payload = {
    "model": self.model,
    "messages": [SYS_CLASIFICADOR_por_estado, {"role": "user", "content": texto}],
    "max_tokens": 12, "temperature": 0.0,
    "guided_choice": LABELS_del_estado,   # ← per-request: fuerza UNA etiqueta. GLPI ni se entera.
    "chat_template_kwargs": {"enable_thinking": False},
}
# Paso 2 — generar respuesta (solo si intent ∈ {PREGUNTA, FUERA_DE_TEMA}) = la generación de hoy.
```

### Guided decoding garantiza FORMATO, no CORRECCIÓN
La salida siempre será una etiqueta válida; que sea la correcta depende del modelo. Clasificar en 5-6
etiquetas claras, **aislado de la generación**, da 98.3% en el 2B (medido). La lección: mantener clasificar
y generar como tareas **separadas** — juntarlas hunde la precisión.

### El manejador es consciente del estado (mismo mecanismo, distinto set de intenciones)
Sets **validados en el PoC** (`scripts/eval_intent_2b.py` — 98.3%, 100% estable):
- **Verificación de identidad:** `CONFIRMA · NIEGA · PREGUNTA_QUIEN_LLAMA · CALIBRACION · OTRO`.
- **Dudas:** `PREGUNTA · DESPEDIDA · FUERA_DE_TEMA · CALIBRACION · ACK`.
Es **un solo manejador** parametrizado por el estado, no funciones dispersas.
`CALIBRACION` = meta-conversación de audio/conexión ("¿me escuchas?", "se corta"); el esqueleto decide reintentar si persiste.

### ⭐ El manejador decide con TEXTO + ETAPA + CONFIANZA (no solo texto) — refinamiento clave
Aprendido en las pruebas de STT (ver `PLAN_WHISPER_ENDURECIMIENTO.md`): **el texto por sí solo no basta**,
porque Whisper puede entregar una transcripción **plausible-pero-errada con confianza normal**
(ej. "Aló, buenas tardes" → "Bueno, eso es todo", `avg_logprob=-1.08`). El manejador/esqueleto decide con **tres insumos**:

1. **Texto** — la transcripción.
2. **Etapa** — en qué estado va la llamada → **plausibilidad**: una intención imposible para la etapa se rechaza.
   Ej.: `DESPEDIDA` en el arranque (antes del saludo) = absurdo → ignorar / re-preguntar, sin importar el texto.
3. **Confianza del STT** (`avg_logprob`, `no_speech`) → **señal BLANDA**, no corte duro (el habla real llegó a -0.99).
   Débil pero real: en el barrido de pruebas, la ÚNICA alucinación fue la ÚNICA con `avg_logprob < -1.0`.

**Regla de oro — confirmar antes de acciones IRREVERSIBLES:**
Colgar es irreversible. Antes de colgar por `DESPEDIDA`, si la **etapa es dudosa** o la **confianza es floja**
(`avg_logprob` muy negativo / `no_speech` elevado) → **confirmar** ("¿seguro que eso es todo?") en vez de
colgar a ciegas. Esto ataja los dos fallos reales observados: el corte por "eso es todo" (cola perdida por STT
entrecortado) y el falso "eso es todo" del arranque.

> Los valores de confianza del STT dejan de ser un "gate" que descarta y pasan a ser **contexto que alimenta al cerebro**.

---

## 4. El esqueleto de seguridad (lo que NO delega al LLM)

La máquina de estados se conserva **delgada**, cuidando solo lo determinista y crítico:

- **Detección de buzón** (arranque) — determinista, no puede ser aleatorio.
- **Verificación de identidad** — el esqueleto decide la transición según `intent`.
- **Colgar / registrar resultado en Postgres** — determinista.

El LLM propone (`intent`, `respuesta`, `terminar`); **el esqueleto dispone** las transiciones críticas.
Así se tiene la naturalidad del LLM con las garantías del control determinista.

---

## 5. Flujo de una llamada, paso a paso

```
1. detectar_buzon  → (esqueleto) VAD endpoint + keywords. Humano/Buzón.
2. presentación    → saludo pre-generado (con barge-in, ya hecho en 2a).
3. verificar_id    → turn-handler(estado=IDENTIDAD):
      "sí soy yo"          → CONFIRMA            → bienvenida
      "no, equivocado"     → NIEGA               → despedida_error
      "¿de parte de quién?"→ PREGUNTA_QUIEN_LLAMA→ re-identifica y vuelve a escuchar
4. bienvenida      → pre-generada (con barge-in).
5. dudas (loop)    → turn-handler(estado=DUDAS) por turno (texto + etapa + confianza):
      pregunta válida      → PREGUNTA     → habla RESPUESTA, sigue en loop
      fuera de tema        → FUERA_DE_TEMA→ habla desvío profesional, sigue
      audio/conexión       → CALIBRACION  → tranquiliza y retoma; si persiste → reintentar más tarde
      reconoce, sigue      → ACK          → sigue en loop
      quiere terminar      → DESPEDIDA    → CONFIRMAR si etapa/confianza dudosa, luego despedida_ok
6. colgar + Postgres (esqueleto).
```

---

## 6. Casos difíciles (los que hoy se rompen) — cómo los maneja

| Entrada del usuario | Hoy | Con el cerebro nuevo |
|---|---|---|
| "eso sería todo, gracias" | ❌ no lo reconoce (no está en la lista) | `DESPEDIDA` → cuelga |
| "¿de parte de quién?" | ❌ cae en "¿eres X?" | `PREGUNTA_QUIEN_LLAMA` → se re-identifica |
| "el nombre de mi cabeza" (STT malo) | ❌ el LLM divaga | `PIDE_REPETIR` → "¿me repites?" |
| "¿qué noticias hay?" | ⚠️ lista de prohibidos | `FUERA_DE_TEMA` → desvío profesional |
| "nos vemos en el próximo video" (alucinación Whisper) | ❌ **adiós fantasma** | Se filtra en STT (§8) **antes** de llegar aquí |

---

## 7. Dónde encaja el RAG (no se desperdicia)

El RAG es la **fuente de conocimiento del campo `respuesta`**. El cerebro nace *RAG-ready*:
1. Fase 1: turn-handler con el conocimiento en el system prompt (como hoy).
2. Fase 2: se recupera del RAG y se inyecta como contexto **antes** de generar `respuesta`.
El RAG deja de ser "el salvador" y pasa a ser "el módulo de conocimiento" — su rol correcto.

---

## 8. STT endurecido (anti-alucinación) — arregla el adiós fantasma

Independiente del cerebro, pero prioritario (un adiós fantasma corta llamadas reales):
- `condition_on_previous_text=False` (corta el arrastre que alimenta la alucinación).
- Subir umbrales `no_speech_prob` / `log_prob` (descarta segmentos poco fiables).
- **Lista de bloqueo** de frases-fantasma ("nos vemos en el próximo video", "subtítulos…", "gracias por ver").
- La despedida (ahora vía LLM) **no** se dispara con un blip de 1 frame: exigir habla sostenida real (VAD).

---

## 9. Latencia: dónde está y qué se afina (Whisper NO es el problema)

Medido en logs reales, de "terminas de hablar" a "suena CosyVoice":
- VAD espera silencio: **~1s** ← afinable
- Whisper STT: ~0.15s ← ya rápido
- LLM: ~0.5s ← ya rápido
- CosyVoice 1er chunk: **~1-1.5s** ← afinable
- Buffer/red: ~0.5s

Palancas: (a) reducir el silencio de corte del VAD, (b) primer chunk de CosyVoice más temprano.
El cerebro nuevo **no** añade latencia (fusiona la llamada LLM que ya existe).

---

## 10. Qué se borra (deuda que desaparece)

`_es_confirmacion` · `_es_negacion` · `_es_confirmacion_o_backchannel` · `_es_despedida_explicita` ·
`es_pregunta_fuera_de_tema` · `es_respuesta_incoherente` · `es_tema_permitido` · `detectar_categoria`
→ **8 funciones de listas de palabras, reemplazadas por 1 manejador de turno.**

---

## 11. Migración incremental (sin big-bang, cada paso reversible)

1. **Endurecer Whisper** (§8) — mata el adiós fantasma. Chico, alto impacto.
2. **Construir el turn-handler** (llm.py + guided_json) y migrar **despedida + confirmación**. Probar.
3. **Migrar el resto** (fuera-de-tema, incoherente, categoría). Borrar las 8 funciones.
4. **Adelgazar la máquina de estados** a esqueleto puro.
5. **Afinar latencia** (silencio VAD + 1er chunk CosyVoice).
6. **Enchufar el RAG** en `respuesta`.

Cada paso deja el sistema igual o mejor, nunca roto a medias. 2a es la base.

---

## 12. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Guided decoding mal soportado por la versión de vLLM | Verificar `guided_json` en el vLLM actual antes de migrar; fallback a `guided_choice` solo para intent |
| El 2B clasifica mal alguna intención | Etiquetas pocas y claras; few-shot en el prompt; fallback a keyword mínimo solo para "sí/no" obvios |
| Carga de GLPI sube la latencia | No añadimos llamadas; monitorear; el manejador es 1 request/turno |
| Regresión al borrar las 8 funciones | Migración por partes con prueba en llamada real en cada paso |

---

## 13. Fuera de alcance

- No se cambia el modelo ni la config del server vLLM (compartido con GLPI).
- No se reescribe transporte, TTS, STT-engine, ni persistencia.
- La "escucha continua total" (STS puro) queda como visión futura, no en esta fase.

---

## 14. Archivos que se tocarían (cuando se apruebe)

| Archivo | Cambio |
|---|---|
| `backend/app/llm.py` | **nuevo** `manejar_turno(estado, texto, contexto)` con `guided_json` |
| `backend/app/call_agent.py` | estados `verificar_id` y `dudas` llaman al turn-handler; se borran las 8 funciones |
| `backend/app/stt.py` | endurecimiento anti-alucinación (§8) |
| `backend/app/prompts.py` | prompt del turn-handler + re-identificación; se adelgaza `get_system_prompt_llm` |
| `backend/app/intent_detector.py` | se elimina o se reduce a mínimos |

Nada toca `docker-compose.yml`, dependencias, ni esquema de BD.
</content>
