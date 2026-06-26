# RAG de RRHH para el Teleoperador — anti-alucinación con voz natural

> Plan de integración. **Creado: 2026-06-25.**
> Objetivo: que el operador responda dudas de onboarding **sin inventar nunca**, manteniendo
> conversación **natural** (no respuestas estáticas). El LLM (Qwen3.5-2b fp8) deja de ser la
> fuente de los datos: solo **redacta** info recuperada del RAG, o declina con naturalidad.
> Relacionado: voz nueva en `docs/INTEGRACION_COSYVOICE3.md`; bitácora TTS en `tts-lab/AVANCE.md`.

---

## 0. PRINCIPIO RECTOR

> **El LLM nunca habla de lo que no está en el RAG.**
> RAG con info → el LLM la redacta natural (y validamos los datos críticos).
> RAG sin info (bajo umbral o `derivar_directo`) → el LLM dice "eso no es tema de la llamada",
> parafraseado distinto cada vez. Cero respuestas inventadas, cero divagación.

Esto es la cura del problema observado en el bot WhatsApp+GLPI: dar "libertad" al LLM hacía que,
en temas sin respaldo, alucinara o se fuera a las nubes. Aquí **la recuperación le pone la correa**.

---

## 1. LO QUE YA EXISTE Y SE REUSA (no se duplica nada)

RAG funcional en `/mnt/DATOS/salesland/RAG` (`rag-api` :8200, `rag-db` pgvector). Comparte el
mismo vLLM (:8100) y embeddings `paraphrase-multilingual-MiniLM-L12-v2` (384 dims, coseno, CUDA).

- **Schema genérico** (`db/init.sql`): tabla `documents` separada por `collection`. La misma tabla
  sirve a GLPI y a RRHH → solo otra colección, **sin cambios de schema**.
- **Interfaz de ingesta** (`api/static/index.html`): "Colección" y "Categoría" son texto libre →
  se carga RRHH escribiendo `rrhh_onboarding`. **Se reusa tal cual.**
- **La correa ya está** (`api/routers/chat.py` + `config.py`, umbrales `score_min=0.55`,
  `score_high=0.75`) y el prompt de `services/llm.py` ya obliga a usar SOLO info verificada.

---

## 2. LA VARIACIÓN RRHH (lo único que cambia)

Un **endpoint nuevo para el teleoperador** (ej. `POST /chat/rrhh`) en el MISMO servicio RAG, que
reusa la recuperación pero cambia la *política de generación*:

| Aspecto | GLPI (hoy) | RRHH (variación) | Por qué |
|---|---|---|---|
| Mensaje "sin registro" | "derivar a ticket de soporte" | "eso no es tema de la llamada", parafraseado natural | En una llamada no hay tickets |
| Camino `score ≥ 0.75` | KB **estático** | **igual lo redacta el LLM** (natural) | Decisión: nada estático (ver §4) |
| Datos del empleado | n/a | inyectar nombre/puesto/fecha desde **PostgreSQL** | Son por-persona, NO van en RAG compartido |
| Estilo de salida | pasos técnicos | cálido, 1-3 frases, formato TTS ("9 de la mañana") | Es voz, no chat |
| Validación de salida | — | el dato crítico (393/URL) debe salir literal o se descarta | fp8 + voz = doble candado |

---

## 3. ESQUEMA RRHH (cómo se carga el conocimiento)

Reusa los campos existentes, solo cambia su semántica:

| Campo BD | En RRHH | Ejemplo |
|---|---|---|
| `collection` | fijo | `rrhh_onboarding` |
| `titulo` | tema/pregunta canónica | "Horario de trabajo" |
| `sintomas` | **cómo lo pregunta la gente** (variantes; se embebe junto al título) | "a qué hora entro, cuál es el horario, jornada, hora de salida, a qué hora salgo" |
| `pasos` | **respuesta verificada, lista para hablar** (formato TTS) | "De 9 de la mañana a 6 de la tarde, con descanso de 1 a 2 de la tarde." |
| `categoria` | agrupador | horario / ubicacion / portal / primer_dia / documentos |
| `derivar_directo` | temas para humano | salario, contrato, beneficios → "eso lo verás con RRHH" |
| `documento` / `autor` | procedencia (opcional) | "RRHH/Onboarding/manual.pdf" |

### Semilla inicial (migrar `EMPRESA_INFO` de `prompts.py` → 5-6 entradas de KB)
horario · ubicacion · portal_empleado · primer_dia (qué hacer) · documentos · (puesto/fecha = del empleado, NO en KB).
Los temas restringidos (salario, contrato, beneficios, vacaciones) se cargan con `derivar_directo=true`
para que devuelvan el "no es el tema" en vez de silencio.

> **Datos del empleado (nombre, puesto, fecha) NO van al RAG** — salen de PostgreSQL por llamada
> (`call_agent._cargar_empleado_postgres`) y se inyectan al generar.

---

## 4. DECISIÓN TOMADA: naturalidad sobre atajo estático

A `score ≥ 0.75`, en vez del KB estático de GLPI, **el teleoperador SIEMPRE redacta por LLM**
(grounded en la respuesta verificada) → naturalidad, que es la prioridad. Coste: ~0.5-1s de LLM por
turno. Si en pruebas la latencia molesta, se activa el atajo estático **solo para las FAQs top**
(optimización posterior, no de entrada).

Umbrales: se parte de 0.55/0.75 pero **se recalibran con preguntas reales** (ver §6). El umbral
es la perilla #1: muy bajo → off-topic se cuela (alucina); muy alto → rechaza preguntas válidas.

---

## 5. FLUJO POR TURNO EN EL OPERADOR (qué se toca en el código)

En `call_agent._estado_responder` (hoy arma el system prompt gigante y llama al LLM directo):

1. Texto del usuario (de Whisper) → **pre-filtro** incoherencia (`intent_detector.es_respuesta_incoherente`)
   para no consultar el RAG con basura de transcripción.
2. **Consultar** `POST /chat/rrhh {message, collection: "rrhh_onboarding"}`.
3. El RAG decide con el umbral:
   - sin match / `derivar_directo` → respuesta "no es el tema" (parafraseada) → hablar.
   - con match → LLM redacta usando SOLO `pasos` + datos del empleado + estilo TTS.
4. **Validación de salida** (datos críticos por categoría: dirección 393, URL del portal) → si falla,
   se descarta y se reintenta o cae a una frase segura.
5. Hablar la respuesta (CosyVoice streaming).

Cambios principales:
- `prompts.py`: `EMPRESA_INFO` deja de ser la fuente directa → migra a KB. El system prompt del
  operador se adelgaza a **rol + estilo + reglas**, sin datos volcados (los inyecta el RAG por turno).
- `llm.py` / nuevo cliente RAG en el backend: llamar a `/chat/rrhh` en vez de armar el prompt gigante.
- RAG `api/routers/chat.py` + `services/llm.py`: endpoint/política RRHH (mensaje de rechazo, estilo,
  inyección de datos del empleado, validación).

---

## 6. ⚠️ EVALUACIÓN OBLIGATORIA ANTES DE PRODUCCIÓN (no negociable)

Nada pasa a producción sin esta batería. Se documentan resultados (como con el TTS).

- [ ] **Calibración de umbral:** lote de preguntas reales (bien hechas) + variantes + mal
      transcritas (Whisper) + off-topic + restringidas. Medir cuántas: responde bien / declina mal
      (falso "no es el tema") / responde algo que debía declinar (peligroso). Ajustar 0.55/0.75.
- [ ] **Anti-alucinación:** set de preguntas trampa (datos que NO están, temas prohibidos, preguntas
      ambiguas) → verificar que SIEMPRE declina y NUNCA inventa.
- [ ] **Fidelidad de datos:** que el 393, la URL, el horario salgan SIEMPRE literales (validación).
- [ ] **Naturalidad:** que el "no es el tema" y las respuestas varíen y no suenen robóticas.
- [ ] **Ruido de Whisper:** preguntas transcritas con errores → ¿recupera bien o se rompe?
- [ ] **Latencia end-to-end:** STT → RAG → LLM → CosyVoice. Medir el turno completo; ver si el atajo
      de score alto hace falta.
- [ ] **VRAM casa llena:** RAG + vLLM + Whisper + CosyVoice a la vez bajo carga (ya estimado ~14.9GB).

---

## 7. RIESGOS / DECISIONES ABIERTAS
- **Umbral** = el make-or-break (§4, §6). Requiere datos reales para calibrar.
- **Whisper rompe la query:** evaluar limpiar/normalizar la transcripción antes de embeber.
- **Inyección de datos del empleado:** definir formato exacto en el prompt del endpoint RRHH.
- **Doble candado:** umbral (recuperación) + instrucción dura al LLM + validación de salida.
- **¿Una colección o varias?** (`rrhh_onboarding` única vs por-cliente/campaña si crece).

## 8. ROLLBACK
El backend puede volver al system prompt gigante actual (no se borra `get_system_prompt_llm`,
solo se deja de usar) mientras el endpoint RRHH madura. El RAG GLPI no se toca (otra colección).
