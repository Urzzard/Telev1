FROM pytorch/pytorch:2.9.0-cuda12.8-cudnn9-runtime

WORKDIR /app


# git: Para instalar dependencias desde git si fuera necesario
# tzdata: Zona horaria
# (faster-whisper decodifica audio con PyAV; NO requiere el binario ffmpeg del sistema)
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Puerto del Backend
EXPOSE 8000

# Ejecutar con Uvicorn (Servidor de alto rendimiento)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]