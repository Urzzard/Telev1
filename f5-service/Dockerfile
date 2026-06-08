FROM nvidia/cuda:12.8.0-cudnn-devel-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv \
    espeak-ng libsndfile1 ffmpeg git curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# PyTorch con CUDA 12.8 (soporte RTX 5080 Blackwell sm_120)
# torch y torchaudio deben ser la misma versión del mismo índice
RUN pip3 install --no-cache-dir --break-system-packages \
    torch==2.8.0 torchaudio==2.8.0 \
    --index-url https://download.pytorch.org/whl/cu128

# F5-TTS Spanish fork (incluye vocab en español) — commit probado en producción
RUN pip3 install --no-cache-dir --break-system-packages \
    git+https://github.com/jpgallegoar/Spanish-F5.git@eba7e7e98f92fa3ae37d0b1cc747bc1f65f3440b \
    fastapi==0.136.1 \
    "uvicorn[standard]==0.46.0" \
    soundfile==0.13.1 \
    numpy==1.26.4 \
    scipy==1.17.1 \
    huggingface-hub==0.32.0

COPY main.py .
RUN mkdir -p voices cache

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/app/cache \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

EXPOSE 8881

CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8881"]
