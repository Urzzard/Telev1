# Pruebas del sistema — 11 Mayo 2026

## Contexto
Prueba completa del pipeline en producción con empleado de prueba: **Manuel Cruz (ID: 1), Analista de TI**.
Stack completo activo: vLLM (Qwen3.5-2B) + Faster Whisper (small/CUDA) + XTTS-v2.

---

## Llamada 1 — Falso positivo de buzón (llamada_id=7)
- **Resultado:** FALLIDO → reintento en 5min
- **Causa:** Señal débil en el teléfono del empleado. Audio nivel 8 → sistema interpretó como buzón de voz.
- **Conclusión:** El detector de buzón es agresivo. Un nivel de 8 puede ser ruido de fondo o señal baja real. A evaluar si el umbral es ajustable.

---

## Llamada 2 — Primera conversación completa (llamada_id=8)
- **Resultado:** EXITO
- **Duración conversación:** ~8 minutos

### Tiempos registrados
| Componente | Tiempo |
|---|---|
| STT (Faster Whisper) | 107–295ms ✅ |
| LLM (primer turno) | **9151ms** ❌ outlier de arranque |
| LLM (turnos siguientes) | 413–838ms ✅ |
| TTS+Reproducción | **15829ms – 20336ms** ❌ |

### Problemas detectados
1. **LLM outlier de 9s en primer turno** — arranque frío, no se repite en siguientes turnos.
2. **Hallucination del LLM:**
   - Input: "Bueno, entonces solo llego y me presento, ¿verdad?"
   - Output: *"¡Me alegra que te asustes un poco con la presentación... ¿Cuándo te gustaría agendar tu primera reunión?"*
   - Usuario respondió: *"creo que no me estás entendiendo bien"*
3. **Barge-in descarta audio → pregunta repetida:**
   - Barge-in captura fragmento con confianza 0.32 → `⚠️ Audio insuficiente`
   - Sistema re-pregunta "¿Tienes alguna pregunta?" en lugar de procesar lo que dijo el usuario
   - El usuario tuvo que preguntar la dirección dos veces
4. **VAD timeout** x2 — usuario habló más tiempo del límite del loop

---

## Llamada 3 — Segunda conversación completa (llamada_id=9)
- **Resultado:** EXITO
- **Temas cubiertos:** horario, dirección, con quién presentarse, nombre del jefe (derivó a recepción), portal de empleados, documentos a traer

### Tiempos registrados
| Componente | Tiempo |
|---|---|
| STT (Faster Whisper) | 123–191ms ✅ |
| LLM (todos los turnos) | 275ms – 948ms ✅ |
| TTS+Reproducción | **6266ms – 17083ms** ❌ |

### Mejoras respecto a llamada 2
- **LLM sin outliers ni hallucinations** — todas las respuestas coherentes y pertinentes.
- **Latencia percibida al contestar (~4s)** — XTTS tiene caché habilitado; el saludo ya estaba en caché del intento anterior, reduciendo el tiempo percibido.

### Problemas persistentes
1. **TTS sigue siendo el cuello de botella** — 6-17s de silencio por respuesta. Sin cambios respecto a llamada 2.
2. **Barge-in con fragmento de audio:**
   - Usuario: *"...tal vez un portal de empleados"* → capturó solo *"empleado. ¡Hola!"*
   - LLM respondió: *"¡Hola Manuel! Qué gusto saludarte de nuevo"* — respuesta absurda
   - Usuario repitió la pregunta

---

## Hallazgos clave

### El problema del "arranque frío"
El LLM tiene un primer turno lento (~9s) que desaparece en los turnos siguientes. En la tercera llamada (ya con vLLM caliente) esto no ocurrió. El keepalive del backend mantiene vLLM activo entre llamadas, pero **si el sistema lleva mucho tiempo sin llamadas, el primer turno de la siguiente llamada puede ser lento**.

### El caché de XTTS
XTTS tiene caché de audio habilitado (`You have enabled caching`). Esto significa:
- Los audios pre-generados (saludo, bienvenida) se reutilizan entre llamadas.
- Para un nuevo empleado con nombre diferente, el saludo y la bienvenida **se generarán desde cero** → latencia alta en el primer turno de audio.
- Las respuestas dinámicas del LLM siempre serán texto nuevo → nunca se cachearán.

### Conclusión sobre el "2da llamada siempre mejor"
No necesariamente requiere 2da llamada, pero sí hay factores que mejoran con el tiempo de vida del sistema:
- vLLM caliente → LLM más rápido en primer turno
- Caché XTTS de saludos → menos latencia percibida al inicio

---

## Problemas priorizados para resolver

| Prioridad | Problema | Impacto | Solución propuesta |
|---|---|---|---|
| 🔴 Alta | TTS sin streaming | 6-17s de silencio por respuesta | Activar streaming en XTTS-v2 |
| 🟡 Media | Hallucination del LLM | Respuesta fuera de contexto | Ajustar prompt del sistema |
| 🟡 Media | Barge-in descarta audio | Usuario repite pregunta | Bajar umbral mínimo de bytes o mejorar manejo del fragmento pre-capturado |
| 🟢 Baja | Arranque frío LLM | Solo en 1er turno de 1ra llamada tras inactividad | Keepalive más agresivo o pre-warm al inicio de cada llamada |
