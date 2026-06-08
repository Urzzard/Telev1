# Estado del proyecto TTS — 11 Mayo 2026

## Situación actual

**TTS activo:** Kokoro-82M GPU (build local, `em_alex`, speed 0.92)
**Backend:** `TTS_BACKEND=kokoro`, `KOKORO_URL=http://kokoro:8880`
**XTTS:** comentado en docker-compose.yml (desactivado)

---

## Lo que se hizo hoy

### 1. Diagnóstico del sistema con XTTS
- 3 llamadas de prueba completas con Manuel Cruz (ID: 1)
- Problema principal confirmado: **latencia TTS de 7-20 segundos** por respuesta
- Causa: XTTS-v2 genera audio completo antes de enviarlo (sin streaming)
- LLM (vLLM + Qwen3.5-2B): funciona bien, 300-900ms por respuesta
- STT (Faster Whisper): excelente, 100-300ms
- Ver detalles completos en `docs/PRUEBAS_11MAY2026.md`

### 2. Investigación de alternativas TTS

| Modelo | Decisión | Razón |
|---|---|---|
| XTTS streaming | ❌ Descartado | Proyecto abandonado, bugs conocidos sin fix |
| Soprano TTS | ❌ Descartado | Solo inglés |
| LFM2.5-Audio | ❌ Descartado | No es TTS standalone, ES en progreso |
| Qwen3-TTS | ⚠️ Futuro | Requiere GPU 24 GB+, RTF > 1x en 16 GB |
| **Kokoro-82M** | ✅ Implementado | Mejor relación velocidad/calidad para 16 GB |

### 3. Implementación de Kokoro

**Problema 1 — Imagen GPU incompatible con RTX 5080 (Blackwell sm_120):**
- La imagen `ghcr.io/remsky/kokoro-fastapi-gpu:latest` usa CUDA 12.6 → no soporta sm_120
- Solución: build local desde `kokoro-service/` con CUDA 12.8 + torch 2.8.0+cu128
- Cambios: `docker/gpu/Dockerfile` (base image) + `pyproject.toml` (torch index)

**Problema 2 — CPU/ONNX demasiado lento:**
- Probado temporalmente: 10-32 segundos por respuesta, peor que XTTS
- El streaming real solo funciona con GPU (ONNX genera todo de golpe)

**Estado actual con Kokoro GPU:**
- Latencia mejoró vs XTTS en frases cortas
- Streaming real funcionando (PCM chunked)
- Voz `ef_dora` → muy seca; cambiado a `em_alex` speed 0.92 → ligera mejora
- Problema persistente: voz monótona, sin emoción para contexto de RRHH

---

## Problemas pendientes

| Problema | Impacto | Estado |
|---|---|---|
| Voz Kokoro monótona | Alto — experiencia del empleado | Sin resolver |
| Latencia TTS variable | Medio — algunas respuestas aún lentas | Mejorado parcialmente |
| Hallucination LLM ocasional | Medio — respuestas incoherentes | Sin resolver |
| Barge-in descarta audio | Bajo — usuario repite pregunta | Sin resolver |
| Arranque frío LLM | Bajo — solo primer turno | Sin resolver |

---

## Opciones para el TTS

### Opción A — Quedarse con Kokoro GPU y mejorar la voz
- Probar voice blending (Kokoro permite mezclar voces)
- Probar las 3 voces ES disponibles: `ef_dora`, `em_alex`, `em_santa`
- Grabar audio de referencia propio y usar voice cloning (requiere investigar si Kokoro lo soporta)
- **Riesgo:** la arquitectura del modelo limita la expresividad

### Opción B — Volver a XTTS con pipeline de frases cortas
- Dividir cada respuesta del LLM en oraciones antes de enviarlo a TTS
- XTTS genera frase por frase en pipeline: mientras reproduce la 1ra, genera la 2da
- Latencia percibida cae a ~2-3s (el usuario escucha la primera oración rápido)
- Voz más cálida y natural que Kokoro
- **Riesgo:** requiere cambios en `call_agent.py` o `tts.py`
- **Para volver:** descomentar `xtts` en docker-compose.yml, cambiar `TTS_BACKEND=xtts`

### Opción C — Qwen3-TTS (futuro)
- Requiere GPU de 24 GB+ (el servidor actual tiene 16 GB)
- Voice cloning con 3 segundos de audio de referencia
- 10 idiomas incluyendo español latino
- Streaming nativo, 97ms latencia
- **Condición:** upgrade de hardware

### Opción D — XTTS + Kokoro híbrido
- Usar XTTS para frases estáticas pre-generadas (saludo, bienvenida, despedida) → voz cálida en momentos clave
- Usar Kokoro para respuestas dinámicas del LLM → más rápido
- **Complejidad:** media, requiere lógica de selección de backend por contexto

---

## Para volver a XTTS

En `docker-compose.yml`:
```yaml
# 1. Cambiar backend
- TTS_BACKEND=xtts

# 2. Descomentar bloque xtts (buscar "descomentar bloque completo")

# 3. Descomentar dependencia en backend
- xtts  # en depends_on
```

Luego:
```bash
docker compose up -d --build
```

---

## Arquitectura actual

```
Llamada SIP
  └── sip-service (Baresip + bridge.py, puerto 8000)
        └── WebSocket audio bidireccional
              └── backend (FastAPI, puerto 5000)
                    ├── STT: Faster Whisper small/CUDA (~0.9 GB VRAM)
                    ├── LLM: vLLM + Qwen3.5-2B (externo puerto 8100, ~9.6 GB VRAM)
                    └── TTS: Kokoro-82M GPU (puerto 8880, ~2-3 GB VRAM)
```

**VRAM total:** ~13.5 GB de 16.3 GB disponibles

---

## Commits del día
- `d45dca3` — change to vllm with qwen3.5:2b (incluye CLAUDE.md y docs/PRUEBAS_11MAY2026.md)
