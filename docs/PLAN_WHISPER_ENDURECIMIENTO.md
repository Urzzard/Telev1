# Plan y hallazgos — endurecimiento del STT (Whisper)

> **Fecha: 2026-07-03.** Frente aparte del turn-handler. Objetivo: que Whisper deje de alucinar
> (adiós fantasma) y que el audio no fiable se maneje como "pedir repetir" en vez de mandar basura al LLM.
> ⚠️ **Sin commitear.** Instrumentación de Fase A YA activa en `backend/app/stt.py` y `docker-compose.yml`.
> Relacionado: `HALLAZGOS_Y_AVANCE.md`, `ARQUITECTURA_CEREBRO_LLM.md` (§8).

---

## 0. Metodología: medir antes de fijar umbrales

Igual que con el clasificador: **primero medimos con datos reales, luego ponemos el corte.**
Fases: **A** medir (logueo) → **B** banco offline → **C** implementar la puerta → **D** confirmar en llamada.

---

## 1. Fase A — instrumentación (HECHA)

En `stt.py`, sin cambiar comportamiento todavía:
- Se loguean las 3 señales de confianza de Whisper por transcripción: `[STT-CONF] no_speech / avg_logprob / compression / dur / texto`.
- Volcado opcional del WAV (gated por env `STT_DUMP_DIR`) → muestras en `./backend/stt_samples/` para el banco offline.
- `STT_DUMP_DIR=/app/stt_samples` añadido temporalmente al backend en `docker-compose.yml` (quitar luego).

### Qué significa cada señal
| Señal | Mide | Rango | Bueno | Malo |
|---|---|---|---|---|
| `no_speech` | prob. de que sea silencio/ruido (no voz) | 0–1 | cerca de 0 | > ~0.6 |
| `avg_logprob` | confianza promedio por palabra | ≤ 0 | cerca de 0 | < ~-1.0 |
| `compression` | repetitividad del texto (len/gzip) | ~0.5–3 | ~1.5–2.4 | > 2.4 (bucles) |

Cada una caza un tipo distinto: `no_speech`→silencio/fantasma · `avg_logprob`→adivinanza · `compression`→bucles.

---

## 2. Hallazgos de las 2 llamadas de prueba

### Baseline de habla BUENA (combinado, ~16 transcripciones reales)
| Señal | Rango observado |
|---|---|
| `no_speech` | 0.04 – **0.22** (máx) |
| `avg_logprob` | -0.25 – **-0.99** (mín) |
| `compression` | 0.38 – 1.00 |

### Hallazgo 1 — el silencio limpio YA está protegido
Cuando el usuario se quedó callado, Whisper devolvió **`sin segmentos (VAD filtró todo el audio)` → texto ""**.
O sea, el `vad_filter=True` borra el silencio limpio y **no alucina**. El flujo ya trata "" como "sin respuesta".

### Hallazgo 2 — el "adiós fantasma" NO se reprodujo
No apareció "nos vemos en el próximo video" en estas pruebas. Conclusión: **necesita ruido de bajo nivel que
pase el VAD pero sin voz real** (no silencio limpio). No capturamos sus números todavía.

### Hallazgo 3 — errores acústicos plausibles (el gate NO los atrapa)
"Okéten"/"Yoquita" (= "soy yo, ¿qué tal?"), "cofre de área" (= "jefe de área"), "bravo" (= "gracias").
Todos con **confianza buena** (`no_speech` bajo, `avg_logprob` normal). No son basura ni silencio → la puerta
de confianza no los distingue. **Frente separado** (ver §5).

### Hallazgo 4 — doble "aló" al inicio (tema de turn-taking, no STT)
El primer saludo del usuario no dispara la respuesta a la primera; hay que repetir. Es un **hueco de arranque**
(setup antes de escuchar + espera del saludo pre-generado), no un fallo del STT. Va al frente de turn-taking/latencia.

---

## 3. Fase C — diseño de la puerta de confianza (por implementar)

Diseño **conservador**: que JAMÁS rechace el habla buena observada (máx `no_speech`=0.22, mín `avg_logprob`=-0.99).

```
Tras transcribir, si NO texto vacío:
  si  no_speech    > 0.60   → NO FIABLE → pedir repetir   (buena ≤ 0.22, margen enorme)
  o   compression  > 2.40   → NO FIABLE → pedir repetir   (buena ≤ 1.0; caza bucles)
  o   texto ∈ lista_bloqueo → NO FIABLE → descartar       (fantasmas conocidos)
  → si no, PASA al LLM.
```
- **`avg_logprob` NO se usa como corte solo**: el habla real llegó a -0.99, pegado al umbral clásico de -1.0.
  Solo se usaría combinado (p.ej. `avg_logprob < -1.0 Y no_speech > 0.4`).
- **`condition_on_previous_text=False`** en `transcribe()` (hoy default True) → corta el arrastre que alimenta alucinaciones.
- **Ampliar `_es_texto_valido`** (lista de bloqueo `stt.py:107`): añadir "nos vemos en el próximo video",
  "próximo video", "no olvides suscribirte", etc. (hoy tiene "subtítulos"/"gracias por ver" pero le faltaba el fantasma real).
- **Señal de salida:** "no fiable" debe distinguirse de "silencio" para que el flujo diga "¿me repites?"
  (hoy ambos caen en "" → se maneja como sin-respuesta; a revisar si conviene un retorno explícito).

### Umbrales de arranque (a refinar si capturamos el fantasma)
`no_speech > 0.60` · `compression > 2.40`. El logueo queda **encendido** para ver el fantasma si reaparece.

---

## 4. Fases restantes

- **B — banco offline:** script que corre DENTRO del contenedor backend (`docker compose exec backend python ...`),
  replaya los WAV de `./backend/stt_samples/` por la misma lógica e imprime `texto / no_speech / logprob / compression → DECISIÓN`.
  Reproducible, sin llamar. (Útil sobre todo cuando tengamos una muestra del fantasma.)
- **C — implementar** la puerta (§3) en `stt.py`.
- **D — confirmar** en llamada real: quedarse callado / con ruido → el fantasma debe caer en "¿me repites?" y no cortar.

---

## 5. Pendientes relacionados (otros frentes)

- **Errores acústicos plausibles** ("Okéten", "cofre") → a futuro: mecanismo de **repetición/confirmación**
  cuando un dato clave (nombre en identidad) no cuadra. El gate de confianza no aplica aquí.
- **Doble "aló" de arranque** → frente turn-taking/latencia.
- Al terminar: **quitar** `STT_DUMP_DIR` de `docker-compose.yml` y decidir si el logueo `[STT-CONF]` se
  deja (útil) o se baja a `debug`.

---

## 6. Estado

- Fase A instrumentada y con datos. Baseline de habla buena capturado.
- Fantasma NO capturado aún (silencio limpio ya protegido por `vad_filter`).
- Puerta diseñada (conservadora) y lista para implementar (Fase C).
- Todo **sin commitear**.
</content>
