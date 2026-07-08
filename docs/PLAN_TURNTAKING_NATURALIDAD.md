# Plan: Turn-taking y naturalidad de la llamada

> **Creado: 2026-07-02.** Documento de diseño ANTES de tocar código. Nada se implementa hasta
> revisarlo y aprobarlo. Objetivo: acercar la llamada a la sensación de *speech-to-speech (STS)*
> **sin** perder las garantías anti-alucinación ni el control determinista de los pasos críticos.
>
> Frente: **turn-taking / VAD**. Está **aislado del RAG** (no toca conocimiento ni `prompts.py`
> del LLM de dudas), así que puede hacerse antes y probarse por separado.

---

## 0. Principio rector

La sensación de STS **no** viene de borrar la máquina de estados, sino de:
**endpointing rápido + escucha continua + barge-in + que el LLM entienda de verdad lo que dice el usuario.**

La máquina de estados (`states.py` / `call_agent.py`) se conserva como **esqueleto de seguridad**:
le garantiza al sistema los tres pasos que NO pueden ser aleatorios → **detección de buzón, verificación
de identidad y colgar**. Al LLM le damos el *cerebro conversacional* (entender intención), no el control
de esas transiciones críticas.

---

## 1. Problema 1 — Latencia en el arranque ("Aló")

### Diagnóstico (verificado en código)
`_detectar_buzon_voz()` (`backend/app/call_agent.py:577`) **captura 3.0 s fijos a ciegas** antes de
transcribir, sin importar cuándo hable la persona:

```python
tiempo_limite = 3.0
while (...) < tiempo_limite:   # graba silencio hasta cumplir 3s aunque digas "Aló" en 0.3s
    ...
```

Recién después llama a Whisper y clasifica. Esa espera ciega —no el TTS ni el LLM— es el grueso de la
latencia inicial percibida.

### Aclaración importante (ya resuelto por diseño)
El chequeo de palabras de buzón (`keywords_buzon`, `call_agent.py:607`) vive **solo** dentro de
`_detectar_buzon_voz()`, que se llama **únicamente** en el primer estado `DETECTAR_BUZON`
(`call_agent.py:219`). **A mitad de llamada NUNCA se vuelve a evaluar "buzón".** Si el usuario dice
"buzón" o Whisper lo alucina más adelante, no corta ni aborta nada. No hay que cambiar esto — ya es así.

### Cambio propuesto: endpoint-por-silencio (no "corte corto")
La regla NO es "cortar rápido", sino **"cortar cuando la persona terminó de hablar y se quedó en
silencio esperando respuesta"**. Esto distingue humano de buzón por comportamiento, no por longitud:

- **Humano:** dice su saludo (corto o largo: "Aló" / "Aló, buenas tardes") y **hace una pausa esperando**.
  → silencio sostenido temprano → cortamos ahí (~1 s en vez de 3 s).
- **Buzón:** habla continuo, sin pausas de turno. → no dispara el silencio temprano → corre hasta el techo.

Quien **clasifica** sigue siendo el chequeo de keywords sobre lo capturado; el endpoint solo decide
**cuándo dejar de capturar**. Por eso un saludo humano largo también funciona: capturamos más audio,
pero al no haber palabra de buzón → humano.

### Parámetros concretos
| Parámetro | Valor propuesto | Razón |
|---|---|---|
| Techo duro (ceiling) | **3.0 s (se mantiene)** | red de seguridad; el buzón continuo llega hasta aquí |
| Piso mínimo antes de permitir corte | **~1.0 s** | evita cortar en la 1ª sílaba |
| Silencio sostenido para cortar | **~500–700 ms** | pausa de turno real, no una respiración |
| Salvaguarda de ambigüedad | si lo capturado es muy corto/ambiguo y sin señal clara → **seguir escuchando** hasta el techo | reduce el falso "humano" de un buzón que pausa temprano |

### Dónde y qué se toca
- **Archivo:** `backend/app/call_agent.py`
- **Función:** `_detectar_buzon_voz()` (líneas ~577–630)
- **Qué:** reemplazar el `while` de captura ciega por un loop con `VoiceActivityDetector`
  (mismo patrón que `_escuchar_respuesta`), aplicando ceiling + piso + silencio sostenido + salvaguarda.
  El bloque de keywords y la lógica de retorno (`return True/False`) **no cambian**.
- **VAD:** usar un detector reseteado para esta fase (evitar arrastrar estado del resto del flujo).

### Riesgo y prueba (obligatoria antes de seguir)
- Riesgo residual: un buzón que pausa temprano ("Hola… [pausa] …deja tu mensaje") podría cortarse antes
  de la keyword. La salvaguarda de ambigüedad lo mitiga, pero **se prueba sí o sí**.
- **Casos de prueba:** (a) contestar como humano rápido, (b) rechazar la llamada → buzón,
  (c) dejar que suene hasta buzón, (d) 2–3 buzones de operadoras distintas.

---

## 2. Problema 2 — Doble pregunta tras confirmar identidad + sensación de "bot"

### Diagnóstico (verificado en código)
Dos causas concurrentes:

**(a) Ventana muerta durante la pregunta pre-generada.**
En `_estado_presentacion()` el camino con audio pre-generado (`call_agent.py:292–314`) hace
`send_bytes(...)` y luego `await asyncio.sleep(duracion)` **sin capturar audio ni monitorear barge-in**
(a diferencia de `_hablar_con_streaming_real`, que sí lo hace). Si el usuario contesta "sí, soy yo"
encima o justo al terminar "¿eres X?", **ese audio se pierde**; luego `_escuchar_respuesta` arranca de
cero, se come el timeout de 6 s y devuelve `None` → re-pregunta *"¿Hola? ¿me escuchas?"*.

**(b) Detección de intención por listas de patrones (frágil).**
`_es_confirmacion()` (`call_agent.py:1074`) y `_es_negacion()` (`call_agent.py:1084`) son listas de
regex. No cubren la variación real del habla. Ejemplo clave: **"¿de parte de quién?"** —desconfianza
legítima ante una llamada desconocida— no es confirmación ni negación, así que hoy cae en el `else` →
*"Disculpa, ¿eres X?"*. Eso es lo que suena a bot.

> **Aclaración de capas:** esto **no** lo arregla el RAG. RAG = aterrizar el *contenido* de las
> respuestas (anti-alucinación). Intención = entender *qué quiso decir* el usuario. Son capas distintas
> y complementarias. La herramienta correcta para intención es el **LLM que ya está cargado**.

### Cambio propuesto: híbrido keyword + LLM-clasificador

**Camino rápido (sin latencia):** para lo obvio y frecuente ("sí", "no", "soy yo") se resuelve con las
keywords actuales al instante.

**Fallback LLM (solo si el keyword no resuelve claro):** el LLM clasifica la frase en un set cerrado:
`CONFIRMA` / `NIEGA` / `PREGUNTA_QUIEN_LLAMA` / `OTRO`. Salida de una sola palabra → rápido
(~100–300 ms), `temperature=0`, y **fallback a keyword** si devuelve algo fuera del set o se cae.

**Rama nueva `PREGUNTA_QUIEN_LLAMA`:** el bot **se re-identifica** ("Te llama Jorge, de Recursos Humanos
de Salesland, para darte la bienvenida — ¿hablo con {nombre}?") y **vuelve a escuchar**. Esta rama es la
que más mata la sensación de bot.

### Dónde y qué se toca

| Archivo | Función / punto | Qué se hace |
|---|---|---|
| `backend/app/call_agent.py` | `_estado_presentacion()` pre-gen (`:292–314`) | Cerrar la ventana muerta: envolver la reproducción con el monitor de barge-in ya existente (`_monitorear_barge_in`) para no perder el inicio de la respuesta. |
| `backend/app/call_agent.py` | `_estado_esperar_confirmacion()` (`:331–366`) | Reemplazar el `if/elif` por el clasificador híbrido + añadir la rama `PREGUNTA_QUIEN_LLAMA`. |
| `backend/app/call_agent.py` | **nuevo** `_clasificar_confirmacion(texto)` | Orquesta: keyword-rápido → LLM fallback → `OTRO`. |
| `backend/app/call_agent.py` | `_es_confirmacion` / `_es_negacion` (`:1074`, `:1084`) | Se **conservan** como capa rápida (no se borran). |
| `backend/app/llm.py` | **nuevo** `classify_intent(texto, etiquetas)` | Método liviano: reusa el patrón `httpx` existente, `max_tokens` bajo, `temperature=0`, valida que la salida ∈ etiquetas, si no → `None` (para fallback). |
| `backend/app/prompts.py` | **nuevo** `get_reidentificacion(nombre)` | Frase de re-identificación para la rama "¿de parte de quién?". Reusa el tono de `get_presentacion` + re-pregunta. |

### Riesgo y prueba
- Riesgo: latencia extra del LLM (mitigada con keyword-rápido + salida de 1 palabra) y dependencia de la
  calidad del prompt de clasificación (mitigada con fallback a keyword).
- **Casos de prueba:** "sí soy yo", "claro, soy yo", "sí", "no", "número equivocado",
  "¿de parte de quién?", "¿de parte de?", silencio total, respuesta ininteligible.

---

## 3. Orden de ejecución

1. **Punto 1 aislado** (arranque endpoint-por-silencio). Probar con los 4 casos de buzón. **Gate:**
   no avanzar hasta que la detección de buzón siga siendo confiable.
2. **Punto 2** (ventana muerta + clasificador híbrido + rama re-identificación).
3. **(Después, sobre la marcha)** propagar el patrón keyword+LLM a los otros detectores frágiles
   (`_es_despedida_explicita`, `es_pregunta_fuera_de_tema`, `es_respuesta_incoherente`).

Cada punto se prueba con una llamada real antes de pasar al siguiente. Cambios aislados = rollback fácil.

---

## 4. Fuera de alcance (explícito)

- **NO** se reescribe la máquina de estados para que el LLM conduzca toda la llamada (riesgo
  anti-alucinación + pérdida de determinismo en buzón/identidad/colgar + difícil de revertir).
- **NO** se toca el RAG ni `get_system_prompt_llm` en este frente.
- El endpointing por milisegundos reales (en vez de por nº de paquetes WS) y la escucha continua total
  quedan como mejora futura de la "versión grande", no en este pase.

---

## 5. Resumen de archivos a tocar

| Archivo | Punto 1 | Punto 2 |
|---|---|---|
| `backend/app/call_agent.py` | `_detectar_buzon_voz` | `_estado_presentacion`, `_estado_esperar_confirmacion`, `_clasificar_confirmacion` (nuevo) |
| `backend/app/llm.py` | — | `classify_intent` (nuevo) |
| `backend/app/prompts.py` | — | `get_reidentificacion` (nuevo) |

Ningún cambio toca `docker-compose.yml`, dependencias, ni el esquema de BD.
</content>
</invoke>
