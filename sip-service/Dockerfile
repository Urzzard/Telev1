FROM debian:bookworm-slim

# 1. Instalar dependencias del sistema y de audio
RUN apt-get update && apt-get install -y \
    build-essential cmake libssl-dev libasound2-dev \
    libpulse-dev pulseaudio pulseaudio-utils \
    git python3 python3-pip python3-venv libportaudio2 \
    libsndfile1 ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# 2. Crear usuario 'sipuser' (PulseAudio no debe correr como root)
RUN useradd -m -s /bin/bash sipuser

# 3. Compilar librería 're' (Dependencia de Baresip) — commit probado en producción
WORKDIR /home/sipuser
RUN git clone https://github.com/baresip/re.git && \
    cd re && git checkout f33a7bd7c55823574aef1ff9695f2d93d239771a && \
    cmake -B build -S . && \
    cmake --build build && cmake --install build && ldconfig

# 4. Compilar 'baresip' — commit probado en producción
WORKDIR /home/sipuser
RUN git clone https://github.com/baresip/baresip.git && \
    cd baresip && git checkout 6b6b5d01e2bb34b9cc70aded330ef7ca0792d5f3 && \
    cmake -B build -S . && \
    cmake --build build && cmake --install build && ldconfig

# 5. Instalar librerías Python para el futuro Bridge (Audio y WebSockets)
# Usamos --break-system-packages porque en Debian 12 es necesario, pero es seguro en Docker.
RUN pip3 install --break-system-packages \
    sounddevice numpy websockets requests asyncio

# 6. Preparar directorios de configuración
USER sipuser
WORKDIR /home/sipuser
RUN mkdir -p .baresip

# 7. Copiar nuestros archivos de configuración al contenedor
COPY --chown=sipuser:sipuser config .baresip/config
COPY --chown=sipuser:sipuser accounts .baresip/accounts
COPY --chown=sipuser:sipuser entrypoint.sh entrypoint.sh

# *COPIAMOS EL ARCHIVO BRIDGE*
COPY --chown=sipuser:sipuser bridge.py bridge.py

# 8. Permisos de ejecución
RUN chmod +x entrypoint.sh

# Exponer puerto de control de Baresip
EXPOSE 8000

# Comando de arranque
CMD ["./entrypoint.sh"]