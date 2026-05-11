# Telev1 — Contexto del proyecto

## ¿Qué es este proyecto?
**Telefonista AI** — Sistema de llamadas automáticas para onboarding de nuevos colaboradores en Salesland Peru. Llama a empleados via SIP, conduce una conversación guiada con STT + LLM + TTS, y registra resultados en PostgreSQL.

## Hardware del servidor
- **GPU:** NVIDIA GeForce RTX 5080 — 16,303 MiB VRAM
- **OS:** Debian Trixie
- **CUDA:** 13.2 / Driver 595.58.03
- **IP servidor:** 200.126.54.98

## Arquitectura actual (producción)
```
Llamada entrante/saliente
  └── sip-service (Baresip + bridge.py, puerto 8000)
        └── WebSocket audio bidireccional
              └── backend (FastAPI, puerto 5000 externo / 8000 interno)
                    ├── STT: Faster Whisper (small, CUDA)
                    ├── LLM: vLLM con Qwen3.5-2B (externo, puerto 8100)
                    └── TTS: XTTS-v2 (puerto 8020)
```

## VRAM en producción
| Componente | VRAM |
|---|---|
| Whisper STT | ~0.9 GB |
| Qwen3.5-2B (vLLM, AI-Service) | ~9.6 GB |
| XTTS-v2 | ~3.1 GB |
| **Total** | **~13.7 GB** |

## Servicios Docker
- `sip-service` — Baresip + bridge.py (SIP y audio)
- `backend` — FastAPI (STT, LLM, TTS, lógica de llamada)
- `xtts` — Coqui XTTS text-to-speech (puerto 8020)
- `postgres` — Base de datos
- `scheduler` — Dispara llamadas pendientes cada cierto tiempo
- `gemini-tts` — Deshabilitado (alternativa TTS con Google)
- `AI-Service` (directorio separado `/mnt/data/salesland/AI-Service/`) — vLLM con Qwen3.5-2B en puerto 8100. Se levanta/baja por separado.

## Problema principal a resolver
**Latencia de 10-20 segundos en la respuesta de voz.**

**Causa raíz:** XTTS-v2 está configurado en modo no-streaming — espera a generar el audio completo antes de enviarlo. El usuario escucha silencio hasta que termina toda la síntesis.

## Soluciones recomendadas (en orden de preferencia)
1. **Activar streaming en XTTS-v2** — XTTS soporta streaming chunk a chunk pero está desactivado. Es el cambio de menor riesgo: misma calidad de voz, latencia percibida cae a ~1-2s.
2. **Reemplazar XTTS-v2 por Kokoro TTS o Piper TTS** — 10x más rápidos, ~200-400 MB VRAM (vs 3.1 GB de XTTS), streaming nativo. Calidad de español aceptable para uso telefónico.

## Lo que ya se descartó
**Qwen2.5-Omni-7B-AWQ** fue evaluado como reemplazo completo del pipeline (STT+LLM+TTS en un solo modelo). Resultado: **no viable en 16 GB VRAM**.
- Carga en reposo: 12.7 GB → solo 3.3 GB para inferencia
- El vocoder token2wav (ODE solver) necesita ~2 GB adicionales → OOM
- Latencia estimada > 2s incluso sin OOM
- Diseñado para GPUs de 24 GB+

## Archivos clave
| Archivo | Función |
|---|---|
| `backend/main.py` | Entry point FastAPI |
| `backend/app/call_agent.py` | Lógica principal de la llamada |
| `backend/app/tts.py` | Cliente TTS (apunta a XTTS o Gemini) |
| `backend/app/stt.py` | Cliente STT (Faster Whisper) |
| `backend/app/llm.py` | Cliente LLM (vLLM) |
| `xtts-service/` | Servicio XTTS-v2 |
| `sip-service/bridge.py` | Bridge SIP ↔ WebSocket |
| `docker-compose.yml` | Orquestación completa |

## Variables de entorno relevantes (docker-compose.yml)
- `VLLM_URL=http://172.17.0.1:8100` — LLM externo
- `TTS_BACKEND=xtts` — activa XTTS (alternativa: gemini)
- `XTTS_URL=http://xtts:8020`
- `WHISPER_MODEL=small` / `WHISPER_DEVICE=cuda`

## Comandos útiles
```bash
# Levantar todo
cd /mnt/data/salesland/Telev1 && docker compose up -d

# Levantar LLM (AI-Service, necesario para el backend)
cd /mnt/data/salesland/AI-Service && docker compose up -d

# Ver logs del backend en tiempo real
docker compose logs -f backend

# Ver logs de XTTS
docker compose logs -f xtts
```

## Advertencias
- AI-Service (vLLM) y cualquier otra carga GPU pesada no pueden correr simultáneamente si suman más de 16 GB VRAM
- El sistema está en producción activa — cambios en el pipeline de audio afectan llamadas reales
- SIP configurado para `testsales@149.56.244.21`
