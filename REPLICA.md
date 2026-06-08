# Guía de replicación — Telev1

Instrucciones para reproducir el entorno exacto en un servidor nuevo.

---

## Requisitos del servidor
- GPU: NVIDIA RTX 5080 (16 GB VRAM) o superior
- OS: Debian Trixie (o Ubuntu 22.04+)
- CUDA 12.8 / Driver 595+
- Docker + Docker Compose
- nvidia-container-toolkit instalado

---

## 1. Clonar repositorios

```bash
# Proyecto principal
git clone <url-de-tu-repo-telev1> /mnt/data/salesland/Telev1

# Kokoro (no está dentro del repo, clonar por separado y pinear commit)
git clone https://github.com/remsky/Kokoro-FastAPI.git /mnt/data/salesland/Telev1/kokoro-service
cd /mnt/data/salesland/Telev1/kokoro-service && git checkout c84adf35567a58d61843768869421adcd5370437

# AI-Service (LLM) — no tiene repo propio, crear la carpeta y el archivo manualmente
mkdir -p /mnt/data/salesland/AI-Service
# Copiar el docker-compose.yml que está documentado más abajo en esta guía
```

---

## 2. Archivos que NO están en git — restaurar manualmente

| Archivo | Descripción |
|---|---|
| `Telev1/.env` | Variables de entorno (credenciales SQL Server, etc.) |
| `AI-Service/.env` | HF_TOKEN si se usa |
| `f5-service/referencia.wav` | Audio de voz de referencia F5 |
| `f5-service/referencia_nueva.wav` | Audio de voz de referencia F5 |
| `f5-service/referencia_24k.wav` | Audio de voz de referencia F5 (24kHz) |

---

## 3. Modelos — se descargan automáticamente

| Modelo | Dónde | Cómo |
|---|---|---|
| `Qwen/Qwen3.5-2B` @ `15852e8c` | `AI-Service/models/` | Al primer `docker compose up` de AI-Service |
| `jpgallegoar/F5-Spanish` @ `eba7e7e9` | `f5-service/cache/` | Al primer arranque del contenedor f5 |
| Whisper `small` | volumen Docker `whisper_cache` | Al primer uso del backend |

---

## 4. Levantar servicios

```bash
# Primero el LLM (tarda ~3 min en cargar)
cd /mnt/data/salesland/AI-Service
docker compose up -d

# Esperar a que vLLM esté healthy
docker compose logs -f

# Luego todo lo demás
cd /mnt/data/salesland/Telev1
docker compose up -d
```

---

## 5. Verificar que todo está corriendo

```bash
# Estado de contenedores
docker ps

# Logs del backend
docker compose -f /mnt/data/salesland/Telev1/docker-compose.yml logs -f backend

# Verificar LLM
curl http://localhost:8100/health
```

---

## AI-Service — docker-compose.yml

Crear el archivo en `/mnt/data/salesland/AI-Service/docker-compose.yml` con este contenido exacto:

```yaml
services:
  vllm:
    image: vllm/vllm-openai:latest@sha256:c32358ebfc115d56ade2acfdbcd00df5b115417dbd6006547c88f07e2b39de06
    container_name: vllm-service
    runtime: nvidia
    ipc: host
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - HUGGING_FACE_HUB_TOKEN=${HF_TOKEN:-}
      - VLLM_WORKER_MULTIPROC_METHOD=spawn
    volumes:
      - ./models:/root/.cache/huggingface
    ports:
      - "8100:8000"
    command: >
      --model Qwen/Qwen3.5-2B
      --revision 15852e8c16360a2fea060d615a32b45270f8a8fc
      --dtype float16
      --max-model-len 2048
      --gpu-memory-utilization 0.55
      --max-num-seqs 32
      --kv-cache-dtype fp8
      --enable-prefix-caching
      --language-model-only
      --enforce-eager
      --served-model-name qwen3.5-2b
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 180s
```

---

## Versiones pineadas (referencia)

| Componente | Versión / Commit |
|---|---|
| vLLM | `sha256:c32358ebfc115d56ade2acfdbcd00df5b115417dbd6006547c88f07e2b39de06` |
| Qwen3.5-2B (HF) | `15852e8c16360a2fea060d615a32b45270f8a8fc` |
| Spanish-F5 (HF) | `eba7e7e98f92fa3ae37d0b1cc747bc1f65f3440b` |
| baresip | `6b6b5d01e2bb34b9cc70aded330ef7ca0792d5f3` |
| baresip/re | `f33a7bd7c55823574aef1ff9695f2d93d239771a` |
| kokoro-service | `c84adf35567a58d61843768869421adcd5370437` |
| PyTorch (backend) | `2.9.0+cu128` |
| PyTorch (f5) | `2.8.0+cu128` |
| postgres | `15-alpine` |
