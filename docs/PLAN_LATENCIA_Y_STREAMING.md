# Plan y hallazgos — latencia, streaming y naturalidad del turno

> **Fecha: 2026-07-08.** Frente de turn-taking/latencia. Objetivo: acercarse a la sensación STS
> (respuesta fluida, pausas naturales) entendiendo dónde está la latencia real y qué técnicas valen la
> pena en NUESTRO hardware (2B compartido con GLPI, telefonía 8kHz). Diseño, nada construido aún.
> Relacionado: `ARQUITECTURA_CEREBRO_LLM.md`, `PLAN_TURNTAKING_NATURALIDAD.md`.

---

## 1. La latencia real: "tú dejas de hablar" → "oyes al bot"

Medido con logs reales (llamada ID 16). El "1.2s" que a veces se cita es **solo el TTS**, no la cadena completa:

| Componente | Tiempo | ¿Bajable? |
|---|---|---|
| **Espera del VAD** (silencio muerto tras callarte) | **~0.65–1.0s** | Sí, pero pelea con cortar al usuario |
| Whisper STT | ~0.15s | Ya vuela |
| LLM (respuesta completa) | ~0.5–0.8s | Ya vuela |
| **TTS → primer audio** (CosyVoice 1er segmento) | **~1.2s** | Sí (segmentando) |
| Red / jitter buffer del teléfono | ~0.3–0.5s | Inherente |
| **TOTAL percibido** | **≈ 3–3.5s** | (coincide con el "3-4s" reportado) |

**No hay un villano único.** Las dos gordas: **espera del VAD** + **TTS primer audio**.

---

## 2. Lo que YA está optimizado

- **STT:** ~130ms. No es el problema (su problema es calidad, no velocidad).
- **LLM:** ~500ms. Rápido.
- **TTS por segmentos:** `_hablar_con_streaming_real` ya envía cada segmento apenas CosyVoice lo suelta
  (`yield speech len ...`), así el usuario oye a ~1.2s y no a los 16s. "Generar mientras se reproduce" **ya existe a nivel TTS.**

---

## 3. La palanca grande: pipelining LLM → TTS por oraciones (NO existe hoy)

Hoy esperamos el **LLM completo** → *después* arranca el TTS. El TTS no puede empezar hasta que el LLM
terminó **toda** la frase.

**Ideal:** el **LLM streamea** (vLLM soporta `stream: true`) → apenas termina la **1ª oración**, se la
mandamos a CosyVoice → **suena mientras el LLM genera la 2ª.** Doble premio:
1. El **tiempo al primer audio se vuelve INDEPENDIENTE de lo larga que sea la respuesta** → respuestas
   ricas SIN pagar latencia (no hace falta "acortar", hace falta "segmentar").
2. Una **1ª oración corta genera más rápido** en CosyVoice → baja también el ~1.2s del TTS.

> Es la idea del usuario ("mientras se reproduce parte, genero lo que falta") llevada un nivel arriba (al LLM, no solo al TTS).

**Costo:** complejidad media (LLM en streaming + partir por oraciones + ordenar el audio). Es la palanca
que más mueve la aguja de latencia percibida.

---

## 4. Gracia adaptativa (pausas / continuación)

Problema: dices "…el horario… *(1-1.5s)* …y también la dirección" → hoy el endpoint corta en la pausa y
responde solo a lo primero; la continuación llega como barge-in desarticulado.

**Solución:** ventana de **gracia** tras el endpoint (mantener el micro ~1-1.5s), y **coser** los fragmentos.
- **Adaptativa (clave):** solo extender la gracia si el fragmento **termina en conector** ("y", "también",
  "o", "pero", "este…") o queda a media idea. Si cierras limpio → responde igual de rápido que hoy.
- **Memoria:** no es bloqueador — como no respondemos al fragmento 1 prematuramente, solo se **acumulan en
  el mismo buffer**; y el historial del LLM ya da contexto entre turnos.
- **Costo:** añade latencia SOLO en el caso de pausa; la versión adaptativa la limita a cuando hueles continuación.

---

## 5. RAG + streaming: el grounding queda casi gratis

Costo del RAG = **recuperación** (embeber pregunta + buscar en base vectorial, ~100-200ms, serial e
inevitable) + **penalización por prompt más largo** (generar tarda un pelín más).

**El streaming ESCONDE la segunda parte:** como la 1ª oración sale igual de rápido, la penalización del
prompt largo no se nota. → **Con streaming, el RAG añade solo ~150ms (la búsqueda), no ~300ms.**
El RAG mejora **de qué habla** (grounding), no la velocidad — pero con streaming su costo se vuelve pequeño.

---

## 6. Técnicas del "ideal STS" — qué SÍ y qué NO en nuestro hardware

| Técnica | ¿Vale la pena aquí? | Por qué |
|---|---|---|
| **LLM streaming → TTS por oraciones** | ✅ Sí | La palanca grande de latencia |
| **Gracia adaptativa** (pausas) | ✅ Sí | Naturalidad; costo controlado |
| **RAG** (con streaming escondiendo su costo) | ✅ Sí | Grounding casi gratis salvo la búsqueda |
| **Whisper incremental / online** | ❌ No | faster-whisper no es streaming; STT ya es ~130ms → poco premio, mucha complejidad |
| **Ejecución especulativa** (pre-computar en la pausa) | ❌ No | Desperdicia llamadas del **2B COMPARTIDO con GLPI** si el usuario continúa; y Whisper no da texto parcial estable. Tier soñado, caro/riesgoso aquí |

Con las tres primeras se llega muy cerca del ideal STS **sin** las dos últimas (caras para este setup).

---

## 7. Estado y orden sugerido

Todo **diseñado, nada construido**. Orden propuesto (el usuario decide cuándo pasar de diseño a código):
1. **`initial_prompt`** en Whisper (2.1) — barato, mejora el texto ya (mishears).
2. **Turn-handler** (`ARQUITECTURA_CEREBRO_LLM.md`) — la palanca grande de naturalidad + confirm-before-hangup.
3. **Paquete latencia:** pipelining LLM→TTS por oraciones + gracia adaptativa.
4. **RAG** en el campo `respuesta` (con streaming, su costo es pequeño).

Nota: latencia total ≈ 3-3.5s hoy; el paquete (3) ataca las dos gordas (espera VAD + TTS primer audio) sin
obligar a respuestas cortas.
</content>
