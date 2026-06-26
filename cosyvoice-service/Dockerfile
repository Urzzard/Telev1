# cosyvoice-service — TTS CosyVoice3 para el Teleoperador (reemplazo de F5)
# Build 100% autocontenido y reproducible (NO depende de imágenes del tts-lab).
# Receta probada para RTX 5080 (Blackwell sm_120): CUDA 12.8 + torch 2.8/cu128.
FROM nvidia/cuda:12.8.0-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8
SHELL ["/bin/bash", "--login", "-c"]

RUN apt-get update -y --fix-missing && \
    apt-get install -y git build-essential curl wget ffmpeg unzip git-lfs sox libsox-dev && \
    git lfs install && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Miniforge + entorno conda python 3.10
RUN wget --quiet https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O ~/miniforge.sh && \
    /bin/bash ~/miniforge.sh -b -p /opt/conda && rm ~/miniforge.sh
ENV PATH=/opt/conda/bin:$PATH
RUN conda create -y -n cosyvoice python=3.10
ENV PATH=/opt/conda/envs/cosyvoice/bin:/opt/conda/bin:$PATH
ENV CONDA_DEFAULT_ENV=cosyvoice

# pynini desde conda-forge (evita compilarlo con pip)
RUN conda install -y -n cosyvoice -c conda-forge pynini==2.1.5

# PyTorch para Blackwell (sm_120)
RUN pip install --no-cache-dir torch==2.8.0 torchaudio==2.8.0 \
    --index-url https://download.pytorch.org/whl/cu128

# Dependencias de CosyVoice (sin torch ni openai-whisper). Trae fastapi/uvicorn/soundfile.
COPY requirements.cosy.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# openai-whisper aparte (su setup.py viejo importa pkg_resources; setuptools<81 lo trae)
RUN pip install --no-cache-dir "setuptools<81" wheel && \
    pip install --no-cache-dir --no-build-isolation openai-whisper==20231117

# modelscope para descargar el modelo en runtime
RUN pip install --no-cache-dir modelscope

# Alguna dep arrastra torch 2.3.1+cu121 y pisa el nuestro. Reforzamos torch+torchaudio
# 2.8/cu128 AL FINAL con --force-reinstall (sube también libs nvidia-*-cu12 a 12.8).
RUN pip install --no-cache-dir --force-reinstall \
    torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128

# Repo CosyVoice a commit fijo (incluye submódulo third_party/Matcha-TTS)
RUN git clone https://github.com/FunAudioLLM/CosyVoice.git /workspace/CosyVoice && \
    cd /workspace/CosyVoice && \
    git checkout 074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc && \
    git submodule update --init --recursive

ENV PYTHONPATH=/workspace/CosyVoice:/workspace/CosyVoice/third_party/Matcha-TTS

WORKDIR /app
COPY main.py /app/main.py
COPY voices /app/voices

EXPOSE 8030

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8030"]
