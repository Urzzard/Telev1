FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias
RUN pip install --no-cache-dir \
    google-cloud-texttospeech \
    flask

# Instalar ffmpeg para procesamiento de audio
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY server.py .

EXPOSE 5003

CMD ["python", "server.py"]