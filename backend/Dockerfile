FROM pytorch/pytorch:2.9.0-cuda12.8-cudnn9-runtime

WORKDIR /app


# ffmpeg: Para Whisper
# git: Para instalar dependencias desde git si fuera necesario
# unixodbc-dev: Para conectar a SQL Server
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
    ffmpeg \
    git \
    unixodbc \
    unixodbc-dev \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Puerto del Backend
EXPOSE 8000

# Ejecutar con Uvicorn (Servidor de alto rendimiento)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]