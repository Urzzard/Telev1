# Estado del proyecto TTS — 13 Mayo 2026

## Situación actual

**TTS activo:** F5-Spanish (jpgallegoar/F5-Spanish, GPU, streaming por oración)
**Backend:** `TTS_BACKEND=f5`, `F5_URL=http://f5:8881`
**XTTS:** comentado en docker-compose.yml
**Kokoro:** comentado en docker-compose.yml

---

## Lo que se hizo hoy

### 1. Migración de Kokoro a F5-Spanish

**Problema con Kokoro:** Voz monótona/seca, sin emoción para contexto de RRHH.

**Intentos con F5:**
- Problema 1: Imagen oficial usa `f5-tts` (paquete estándar inglés/chino) → audio en "chino"
- Causa raíz: El paquete `pip install f5-tts` usa vocab inglés/chino, incompatible con el modelo jpgallegoar
- Solución: Cambiar a `pip install git+https://github.com/jpgallegoar/Spanish-F5.git`

- Problema 2: Audio de referencia estéreo 44100Hz → F5 necesita mono 24kHz
- Solución: `ffmpeg -i referencia.wav -ac 1 -ar 24000 referencia_24k.wav`

- Problema 3: `F5TTS.__init__()` usa `model_type=` no `model=` en el fork español
- Solución: Corregido en `main.py`

### 2. Audio de referencia

**Referencia activa:** `f5-service/voices/referencia_24k.wav`
- Fuente: Clip de YouTube de Platzi sobre Netflix/Warner (acento colombiano)
- Convertido a mono 24kHz
- Texto de referencia: "Netflix está apunto de comprar a Warner..."
- **Resultado:** Voz con acento colombiano natural, buena expresividad

**Referencia alternativa:** `f5-service/voices/referencia_nueva.wav`
- Grabación propia del usuario con micrófono de laptop
- Audio con algo de ruido ambiente → calidad inferior
- Descartada por ahora

### 3. Integración al sistema

- Servicio `f5` agregado a `docker-compose.yml` con GPU y volúmenes
- `tts.py` actualizado con `_synthesize_f5()` y `_synthesize_f5_stream()`
- Streaming por oraciones funcionando (usuario escucha primera oración en ~1-2s)

---

## Resultados de pruebas

| Métrica | XTTS-v2 | F5-Spanish |
|---|---|---|
| Latencia hasta primer audio | 7-20s | ~1-2s |
| TTS+Reproducción total | 7-20s | 5.5-13s |
| Streaming real | ❌ | ✅ |
| Calidad de voz | Cálida | Rígida pero mejorable |
| VRAM | ~3.1 GB | ~2-3 GB |

**Llamadas completadas con EXITO:** 2 llamadas de prueba completas con Manuel Cruz (ID: 1)

---

## Bugs pendientes (para después del almuerzo)

| Bug | Impacto | Descripción |
|---|---|---|
| Split de URL | Alto | URL convertida se fusiona con siguiente oración → pronunciación rara |
| Falso positivo "incoherente" | Alto | Frases válidas como "Entonces, solo voy y me presento a las 9" son rechazadas |
| Alucinación LLM | Medio | "Suerte con el examen" inventado por Qwen3.5-2B |
| Voz rígida | Medio | Mejoraría con audio de referencia profesional |

---

## Arquitectura actual

```
Llamada SIP
  └── sip-service (Baresip + bridge.py, puerto 8000)
        └── WebSocket audio bidireccional
              └── backend (FastAPI, puerto 5000)
                    ├── STT: Faster Whisper small/CUDA (~0.9 GB VRAM)
                    ├── LLM: vLLM + Qwen3.5-2B (externo puerto 8100, ~9.6 GB VRAM)
                    └── TTS: F5-Spanish GPU (puerto 8881, ~2-3 GB VRAM)
```

**VRAM total estimada:** ~12.5-13.5 GB de 16.3 GB disponibles

---

## Archivos clave de F5

| Archivo | Descripción |
|---|---|
| `f5-service/Dockerfile` | Build con CUDA 12.8 + Spanish-F5 fork |
| `f5-service/main.py` | Servicio FastAPI con streaming por oraciones |
| `f5-service/voices/referencia_24k.wav` | Audio de referencia activo (Platzi, mono 24kHz) |
| `f5-service/cache/` | Modelos HuggingFace cacheados localmente |

## Para volver a Kokoro o XTTS

En `docker-compose.yml`:
- Cambiar `TTS_BACKEND=kokoro` o `TTS_BACKEND=xtts`
- Descomentar el bloque del servicio correspondiente
- Descomentar la dependencia en el backend
- `docker compose up -d`
