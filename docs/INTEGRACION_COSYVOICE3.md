# Integración de CosyVoice3 al Teleoperador (reemplazo de F5)

> Plan de integración. **Creado: 2026-06-25.**
> Pre-requisitos ya cumplidos: motor elegido (Fun-CosyVoice3-0.5B), validado en español,
> VRAM resuelta con fp8 (todo el pipeline entra en 16GB con ~1.4GB libre).
> Bitácora del laboratorio y números medidos: `tts-lab/AVANCE.md`.

---

## 0. CONTEXTO — de dónde venimos y a dónde vamos

**Hoy (producción):** TTS = **F5** (`f5-service`, puerto 8881, `TTS_BACKEND=f5`). XTTS y Kokoro
ya descartados/comentados. La latencia percibida es el problema original del proyecto.

**Objetivo:** reemplazar F5 por **CosyVoice3** como nuevo `cosyvoice-service`, con **streaming PCM
chunk-a-chunk** (TTFB ~1.1s) y voz clonada cacheada (`spk_id='salesland'`).

**Estado actual del repo (dejado listo el 2026-06-25):**
- `TELEV1/docker-compose.yml`: servicio `f5` y su `depends_on` **comentados** (libera ~2-3GB).
- vLLM en **fp8** (`AI_SERVICE`, separado, puerto 8100). El backend lo usa por `172.17.0.1:8100`.
- Stack arriba sin TTS: RAG 822 + vLLM 7282 + Whisper 900 = **9024 MiB**, libre 7279 MiB.

---

## 1. ARQUITECTURA OBJETIVO

```
Llamada  →  sip-service (bridge.py)  →  backend (FastAPI)
                                          ├── STT: Faster-Whisper (small, CUDA)         ~0.9 GB
                                          ├── LLM: vLLM fp8 Qwen3.5-2b (172.17.0.1:8100) ~7.3 GB
                                          └── TTS: cosyvoice-service (NUEVO, :8030)      ~5.9 GB
                                                   └── /v1/audio/speech (PCM stream 24kHz)
RAG (rag-api, aparte) ~0.8 GB
```
- `cosyvoice-service` vive **dentro de TELEV1** (como `f5-service`), en su propio contenedor GPU.
- vLLM se mantiene **separado** (AI_SERVICE), como hasta ahora. NO se fusiona.

---

## 2. CONTRATO A REPLICAR (calcado de f5-service, para que sea drop-in)

`f5-service/main.py` ya define el contrato que el backend espera. Lo copiamos **idéntico**:

```
POST /v1/audio/speech
  body: { "input": str, "voice"?: str, "response_format"?: "pcm"|"wav", "speed"?: float }
  - response_format=pcm  → StreamingResponse, media_type application/octet-stream,
                            int16 PCM crudo SIN cabecera, a 24000 Hz  ← lo usa el bridge
  - response_format=wav  → Response audio/wav PCM_16
GET /health → { status, model, ... }
```

✅ **Ventaja clave:** F5 ya trabaja a **24 kHz int16 PCM** (`(wav*32767).astype(int16).tobytes()`).
CosyVoice3 también sale a 24 kHz → **mismo formato, sin resampleo nuevo**. Drop-in real.

✅ **Mejora sobre F5:** F5 streamea **oración por oración**; CosyVoice puede streamear
**chunk-a-chunk real** (`inference_zero_shot(..., stream=True)`), lo que baja aún más el TTFB.

---

## 3. GOTCHAS DE CosyVoice3 QUE EL SERVICIO DEBE RESPETAR
(ver detalle en `tts-lab/AVANCE.md`)

1. **`<|endofprompt|>`** obligatorio al registrar la voz:
   `prompt_text = "You are a helpful assistant.<|endofprompt|>" + transcripción_real_del_ref`.
2. **`text_frontend=False`** → números en español nativo (con True, wetext los lee en inglés).
   Para robustez: normalizar nosotros (num2words es) DNI/montos/fechas y dejar `text_frontend=False`.
3. **Voz cacheada** = TTFB a la mitad: `add_zero_shot_spk(prompt_text, ref_wav, 'salesland')` +
   `save_spkinfo()` **una vez** al arrancar; luego `inference_zero_shot(texto, '', '',
   zero_shot_spk_id='salesland', stream=True, text_frontend=False)`.
4. **Imagen Docker:** reusar runtime torch 2.8/cu128 (Blackwell sm_120) — base `cosyvoice2:blackwell`
   o un Dockerfile equivalente. Repo CosyVoice ya soporta v3 vía `AutoModel`.
5. **`libcudnn.so.8` ausente** → 2 ONNX (speaker embedding + tokenizer) caen a CPU. Con la voz
   cacheada es **costo único** al registrar. Arreglarlo (instalar cudnn8) es optimización, no bloqueante.

---

## 4. PLAN POR FASES (poco a poco, probando en cada paso)

### FASE 1 — Crear `cosyvoice-service/` aislado  ✅ HECHA (2026-06-26)
- [x] `cosyvoice-service/Dockerfile` — **build 100% autocontenido y reproducible** desde base
      pública `nvidia/cuda:12.8.0-cudnn-devel-ubuntu22.04` (NO depende del `cosyvoice2:blackwell`
      del lab). Clona el repo CosyVoice a commit fijo `074ca6d` (con submódulo Matcha-TTS).
- [x] `cosyvoice-service/main.py` (FastAPI: lifespan auto-descarga modelo + registra voces + warmup;
      `/health`; `/voices`; `/v1/audio/speech` rama pcm streaming chunk-a-chunk y rama wav).
      **+ SELECTOR DE VOCES**: pares `voices/<nombre>.wav`+`.txt`; campo `voice` elige; `DEFAULT_VOICE`.
- [x] **Modelo (~8.5GB)** → DECISIÓN: auto-descarga de ModelScope (`FunAudioLLM/Fun-CosyVoice3-0.5B-2512`)
      a un **volumen Docker persistente** (`cosyvoice_models`). No va a git, no se re-descarga.
      Voz de referencia (`salesland.wav`+`.txt`, ~360KB) **sí va a git** en `voices/`.
- [x] **Prueba aislada** (sin tocar backend), resultados:
      - `/health` ok, voz `salesland` registrada, `sample_rate=24000`.
      - WAV: 480KB = ~10s de audio en 2.36s; `RIFF WAVE PCM 16bit mono 24000 Hz` ✅.
      - PCM streaming: **2.28s para 9.48s de audio** (~4× tiempo real). TTFB real ~1.1s (medido
        en lab con spk cacheado; el `time_starttransfer` de curl mide cabeceras, no el 1er chunk).
      - VRAM: CosyVoice3 = **3956 MiB** (estimábamos 5.9GB). Stack total Whisper+vLLM+CosyVoice =
        **11326/16303 MiB** → ~5GB libres. Cuello de VRAM resuelto con holgura.
      - [x] Confirmación auditiva del usuario (2026-06-26): voz natural y números en español ✅.

### FASE 2 — Integrar en `backend/app/tts.py`  ✅ HECHA (2026-06-26)
- [x] `self.cosyvoice_url` + `self.cosyvoice_voice` + `self.cosyvoice_speed` (env COSYVOICE_URL/VOICE/SPEED).
- [x] `_synthesize_cosyvoice` (wav) y `_synthesize_cosyvoice_stream` (pcm) — calco de F5 + campo `voice`.
- [x] Rama `"cosyvoice"` en `synthesize()`, `synthesize_stream()` y `get_audio_format()` (→ "wav").
- [x] `call_agent` no se toca: ya consume PCM int16 24kHz y resamplea a 8kHz (`resample_poly(.,1,3)`)
      → CosyVoice (24kHz) es drop-in total. `preparar_texto_para_tts()` se reutiliza tal cual.
- [x] `python3 -c "import ast; ast.parse(...)"` → sintaxis OK.

### FASE 3 — docker-compose.yml  ✅ HECHA (2026-06-26)
- [x] Servicio `cosyvoice` (build `./cosyvoice-service`, puerto 8030, reserva GPU, voices bind-mount,
      volumen `cosyvoice_models` REUTILIZANDO el ya descargado → cero re-descarga).
- [x] backend: `TTS_BACKEND=cosyvoice`, `COSYVOICE_URL=http://cosyvoice:8030`, `depends_on: - cosyvoice`.
- [x] `docker compose config --quiet` → válido.

### FASE 4 — Prueba end-to-end real  ✅ HECHA (2026-06-26)
- [x] Stack completo arriba (`docker compose up -d`), standalone bajado, vLLM arriba. Backend conecta a
      `http://cosyvoice:8030/health` por red interna. `TTS_BACKEND=cosyvoice` confirmado en env.
- [x] CosyVoice arrancó **sin re-descargar modelo ni re-registrar voz** (`voz 'salesland' ya cacheada`,
      `warmup ok`). VRAM en reposo con todo arriba: **12888/16303 MiB** (~3.4GB libres).
- [x] **Llamada real de onboarding hecha.** Resultado del usuario: pipeline funciona end-to-end con la
      voz clonada; latencia "igual que la recordaba" (el cuello es el LLM, no el TTS) y voz "aceptable,
      mejorable". Sin OOM.
- [x] CONCLUSIÓN: integración CosyVoice **terminada y operativa**. Backend usa CosyVoice por defecto.

### FASE 5 — Afinado de producción (mejoras, NO bloqueantes)
- [x] **Warmup** al arrancar el servicio (1 síntesis dummy) — ya implementado (`WARMUP=1`).
- [ ] **⬅️ ABIERTO: mejor voz de referencia.** El usuario grabará una toma de mayor calidad. La actual
      (`voices/salesland.wav`, 11.3s) ya está en el largo óptimo; la palanca NO es más duración sino:
      grabación limpia (sin ruido/reverb/saturación), tono deseado (cálido/claro), 1 hablante, ~10-15s,
      alta calidad antes de bajar a 16k mono. **Techo real = los 8kHz de la telefonía** (ninguna voz
      sonará HD en la llamada). Cómo enchufarla → ver §7 "Cambiar/mejorar la voz".
- [ ] Probar `COSYVOICE_SPEED=0.9` (más pausado, suele sonar más natural en teléfono).
- [ ] `num2words(es)` para DNI dígito a dígito, montos S/, fechas (el regex actual cubre horarios y
      fechas dd/mm/yyyy, pero no DNI ni montos).
- [ ] Arreglar `libcudnn.so.8` (cudnn8 en la imagen) — solo afecta el registro de voz, ya cacheado → cosmético.
- [ ] **Muletillas pregeneradas** ("déjame revisar...", "un momento...") para enmascarar latencia del LLM.

### FASE 6 — Concurrencia (solo si hace falta)
- [ ] Si varias llamadas simultáneas degradan el TTFB (backend default: ×5 → 1.1s→6.1s),
      activar el **backend vLLM de CosyVoice** (`load_vllm=True`, carga `{model_dir}/vllm`).
- [ ] Re-medir VRAM (el backend vLLM de CosyVoice puede pedir algo más).

---

## 4b. CAMBIAR / MEJORAR LA VOZ (selector de voces) — todo queda listo para esto

El servicio registra **cada par** `<nombre>.wav` (o `.flac`/`.mp3`) + `<nombre>.txt` (transcripción
EXACTA del audio) que haya en `cosyvoice-service/voices/`. El `spk_id` = nombre del archivo.
**Agregar una voz NO re-descarga el modelo** (es solo `spk2info.pt`, segundos).

Pasos para enchufar una mejor toma:
1. Pon `voices/<nombre>.wav` + `voices/<nombre>.txt` (la transcripción literal de lo que se dice).
2. `docker compose restart cosyvoice` → en logs: `registrando voz '<nombre>'`.
3. Probar sin llamar:
   `curl -s -X POST http://localhost:8030/v1/audio/speech -H 'Content-Type: application/json' \
     -d '{"input":"...","voice":"<nombre>","response_format":"wav"}' -o /tmp/v.wav`
4. Cuando convenza, fijarla por defecto: en `docker-compose.yml` (servicio backend) cambiar
   `COSYVOICE_VOICE=<nombre>` y en el servicio `cosyvoice` `DEFAULT_VOICE=<nombre>`; `up -d`.

> La voz buena se versiona en git (es pequeña). El modelo NO (vive en el volumen `cosyvoice_models`).

---

## 5. RIESGOS / DECISIONES ABIERTAS
- **Concurrencia real esperada:** ¿cuántas llamadas simultáneas? Define si la Fase 6 es necesaria ya
  o más adelante. (Con default, 1 llamada va perfecta a ~1.1s TTFB.)
- ~~**Ubicación del modelo de 8.5GB**~~ → RESUELTO: auto-descarga de ModelScope a volumen Docker
  `cosyvoice_models` (no va a git; en clon nuevo se baja en el 1er arranque). Servicio autocontenido.
- **Limpieza de audios:** el `scheduler` monta `./xtts-service/output`; revisar si CosyVoice escribe ahí
  o si se cambia esa ruta.
- **Legal (antes de prod):** consentimiento de la voz clonada + aviso de voz sintética en la llamada.

---

## 6. ROLLBACK (volver a F5 en 1 minuto)
En `docker-compose.yml`: descomentar el servicio `f5` + su `depends_on: - f5`, poner `TTS_BACKEND=f5`,
comentar `cosyvoice`, y `docker compose up -d`. F5 ya está construido (imagen `f5-spanish:local`).
