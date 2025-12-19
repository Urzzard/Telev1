FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3.10 python3-pip python3-dev git \
    ffmpeg libsndfile1 portaudio19-dev libasound2-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --upgrade pip

# PyTorch con CUDA 12.8 (tu versión original)
RUN pip3 install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu128

# Instalar torchcodec para cargar audio
RUN pip3 install --no-cache-dir torchcodec

# Instalar versiones específicas que NO tienen el bug de coqpit
RUN pip3 install --no-cache-dir "coqpit==0.0.17"
RUN pip3 install --no-cache-dir "TTS==0.22.0"
RUN pip3 install --no-cache-dir xtts-api-server

EXPOSE 8020

ENV TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1

# NORMAL MODE
CMD ["python3", "-m", "xtts_api_server", "--listen", "--use-cache", "--device", "cuda"]

# STREAMING MODE
#CMD ["python3", "-m", "xtts_api_server", "--listen", "--use-cache", "--device", "cuda", "--streaming-mode"]