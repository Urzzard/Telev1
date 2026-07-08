# Hallazgos y avance — sesión de rediseño del teleoperador

> **Fecha: 2026-07-03.** Resumen de lo descubierto, probado y decidido en esta sesión.
> ⚠️ **Nada de esto está commiteado todavía** (por decisión: dejar todo asentado y limpio antes).
> Documentos relacionados: `PLAN_TURNTAKING_NATURALIDAD.md`, `ARQUITECTURA_CEREBRO_LLM.md`.

---

## 0. TL;DR

- El sistema **funciona**, pero con deficiencias de naturalidad y calidad concentradas en **una capa**: la decisión "adivinando por listas de palabras".
- **Decisión estratégica:** NO rehacer el proyecto (la plomería sirve). Rehacer **el cerebro** = reemplazar 8 funciones de palabras por un **manejador de turno con el LLM**.
- **Validado con datos reales sobre el hardware:** el diseño del cerebro es **viable, preciso (98.3%) y 100% estable**. El riesgo técnico #1 (guided decoding) quedó despejado.

---

## 1. Turn-taking — HECHO y validado en vivo (sin commitear)

Cambios en `backend/app/call_agent.py` + `docker-compose.yml`, probados en llamada real:

- **Punto 1 — arranque:** `_detectar_buzon_voz()` corta por VAD cuando la persona termina su "Aló" (endpoint-por-silencio: techo 3s, piso 1s, silencio 0.7s). Antes esperaba **3s ciegos**. El buzón habla continuo → corre hasta el techo → detección de buzón intacta. **Validado:** humano ~2s, buzón OK.
- **Punto 2a — ventana muerta / doble-pregunta:** nuevo helper `_reproducir_audio_pregenerado()` reproduce saludo/bienvenida **con monitoreo de barge-in** (antes era `send + sleep` ciego que perdía el inicio de la respuesta y confundía al VAD). **Validado:** la doble-pregunta **desapareció**.
- **Fix infra:** volumen `torch_hub_cache:/root/.cache/torch` para no re-descargar Silero VAD en cada arranque.

---

## 2. Problemas DESCUBIERTOS en las pruebas reales

1. **Whisper alucina un "adiós fantasma".** Sobre silencio, transcribe frases tipo *"nos vemos en el próximo video"*, que hacían match con la despedida y **cortaban la llamada de la nada**. El filtro actual (`stt.py:_es_texto_valido`) NO incluye esa frase. **Pendiente de arreglar.**
2. **Whisper descarta su propia confianza.** `stt.py:84` toma solo `s.text` y tira `avg_logprob`, `no_speech_prob`, `compression_ratio` — justo las señales que necesitamos para detectar audio malo.
3. **Latencia por turno ~4s — NO es Whisper.** Desglose real: espera de silencio del VAD (~1s) + primer chunk de CosyVoice (~1-1.5s) + LLM (~0.5s) + STT (**solo ~0.15s**) + buffer. Whisper es el que MENOS pesa en latencia; su problema es **calidad**, no velocidad.
4. **Corte de transporte del WebSocket** (ABNORMAL_CLOSURE 1006) + underruns ALSA en sip-service durante la bienvenida larga. Frente aparte, no diagnosticado a fondo.
5. **El LLM divaga con input basura** (cuando el STT entrega texto roto).
6. **La descarga que se veía en logs** = Silero VAD (torch.hub) re-bajándose cada arranque (ya con fix) + la barra `100% 1/1` de CosyVoice, que **NO es descarga**, es su barra de inferencia (tqdm).

---

## 3. Decisión de arquitectura: rehacer EL CEREBRO, no el proyecto

Detalle completo en `ARQUITECTURA_CEREBRO_LLM.md`. En una línea:

> Reemplazar `_es_confirmacion`, `_es_negacion`, `_es_despedida_explicita`, `es_pregunta_fuera_de_tema`,
> `es_respuesta_incoherente`, `es_tema_permitido`, `detectar_categoria`, `_es_confirmacion_o_backchannel`
> **(8 funciones de listas de palabras)** por **UN manejador de turno con el LLM** que devuelve en una sola
> llamada `{intent, respuesta, terminar}` con guided decoding. La máquina de estados queda como
> **esqueleto de seguridad** (buzón, identidad, colgar = deterministas).

**Restricción crítica respetada:** el Qwen-2B es **compartido con el bot de WhatsApp de GLPI** → todo per-request, sin tocar la config del server, sin añadir llamadas (se fusiona intención+respuesta), sin cambiar el modelo, sin VRAM nueva.

---

## 4. PoC del manejador de turno — RESULTADOS VALIDADOS

Script: `scripts/eval_intent_2b.py` (stdlib pura, sin dependencias, no toca el proyecto).
Método: 58 frases reales etiquetadas, 2 estados (identidad/dudas), `guided_choice` + `temperature=0`,
few-shot **disjunto** de las frases de test (para medir generalización real, no memorización).

| Métrica | Resultado |
|---|---|
| **guided_choice soportado por el vLLM** | ✅ Sí — **riesgo técnico #1 despejado** |
| **Precisión** | **98.3%** (57/58) |
| **Estabilidad (5 pasadas, temp=0)** | **100%** — 58/58 frases dieron SIEMPRE la misma etiqueta |
| **Reproducibilidad tras `down`+`up --build`** | Idéntica (98.3% / 100% estable) |
| **Latencia (caliente)** | ~84ms media (misma llamada que además daría la respuesta) |
| **Latencia primer token en frío** | ~9.7s (warmup del vLLM; no aplica en producción con keepalive) |

**Precisión por etiqueta:** PREGUNTA 8/8 · DESPEDIDA 9/9 · FUERA_DE_TEMA 7/7 · CALIBRACION 9/9 ·
PREGUNTA_QUIEN_LLAMA 6/6 · NIEGA 5/5 · ACK 5/5 · OTRO 2/2 · **CONFIRMA 6/7**.

**Único fallo (estable, no aleatorio):** `"Sí, ¿qué tal?"` → CALIBRACION en vez de CONFIRMA. El "¿qué tal?"
lo confundió con un chequeo de audio. **Degrada elegante:** en la fase de identidad, un CALIBRACION solo
hace que el bot diga "sí, te escucho, ¿hablo con Manuel?" → el usuario confirma → sigue. El esqueleto
absorbe el error. Se cierra afinando la definición de CALIBRACION (excluir saludos sociales).

**Casos que HOY se rompen y el PoC resuelve:** "eso sería todo"/"ya estamos"/"no tengo más preguntas" →
DESPEDIDA · "de parte de quién" → PREGUNTA_QUIEN_LLAMA · "ok, chau" → DESPEDIDA · "cuánto gano" → FUERA_DE_TEMA.

### Descubrimientos de diseño que salieron del PoC
- **PIDE_REPETIR NO debe ser trabajo del LLM.** El modelo se empeña en interpretar texto basura (0/5).
  La incoherencia se detecta mejor en el **STT por confianza** (ver §2.2). → sale del clasificador.
- **CALIBRACION** (idea del usuario): intent nuevo para meta-conversación de audio/conexión
  ("¿me escuchas?", "se corta"). Absorbe el difuso OTRO; el esqueleto decide reintentar si la queja persiste.

---

## 5. Pendientes / próximos pasos

1. **Endurecer Whisper** (`stt.py`): puerta de confianza (`avg_logprob`/`no_speech_prob`/`compression_ratio`)
   + `condition_on_previous_text=False` + ampliar lista de bloqueo (incluir "nos vemos en el próximo video").
   → mata el adiós fantasma y absorbe PIDE_REPETIR.
2. **Construir el turn-handler** en `llm.py` + `call_agent.py` (guided_json `{intent, respuesta, terminar}`),
   migrando despedida/confirmación y borrando las 8 funciones de palabras.
3. **Ajuste menor:** definición de CALIBRACION para cerrar el caso "Sí, ¿qué tal?".
4. **Afinar latencia:** silencio de corte del VAD + primer chunk de CosyVoice.
5. **RAG:** alimenta solo el campo `respuesta` (fase posterior).
6. **Aparte:** diagnosticar el corte de transporte 1006 / underruns ALSA con reproducción controlada.

---

## 6. Artefactos producidos en la sesión

| Artefacto | Qué es |
|---|---|
| `docs/PLAN_TURNTAKING_NATURALIDAD.md` | Plan del turn-taking (Punto 1 + 2a + 2b) |
| `docs/ARQUITECTURA_CEREBRO_LLM.md` | Diseño del manejador de turno + restricción GLPI |
| `docs/HALLAZGOS_Y_AVANCE.md` | Este documento |
| `scripts/eval_intent_2b.py` | Evaluador del 2B (stdlib, `--repeat N` para estabilidad) |
| Simulador interactivo (artifact) | Simulación turno-a-turno del cerebro nuevo |

**Estado git:** todo sin commitear. Sólido para commitear cuando el usuario decida: turn-taking 2a +
fix del volumen VAD + los docs + el script de evaluación.
</content>
