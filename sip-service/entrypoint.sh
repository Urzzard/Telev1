#!/bin/bash

echo "🎧 Iniciando Demonio de PulseAudio..."
# Iniciamos PulseAudio en modo demonio (background)
pulseaudio -D --exit-idle-time=-1

echo "🔌 Creando Cables Virtuales (Boca y Oído)..."
# Cable 1: CableVirtual (Donde la IA habla -> Baresip escucha)
# Cable 2: CableOido (Donde Baresip habla -> La IA escucha)
pactl load-module module-null-sink sink_name=CableVirtual sink_properties=device.description="Cable_Virtual_IA"
pactl load-module module-null-sink sink_name=CableOido sink_properties=device.description="Cable_Oido_IA"

echo "⚙️ Configurando Enrutamiento de Audio..."
# Baresip usará estos por defecto:
# Micrófono de Baresip = Monitor del CableVirtual (Lo que habla la IA)
pactl set-default-source CableVirtual.monitor
# Parlante de Baresip = CableOido (Lo que escucha la IA)
pactl set-default-sink CableOido

echo "🚀 Iniciando Baresip..."
# Iniciamos Baresip escuchando en el puerto 8000
baresip -f /home/sipuser/.baresip &
BARESIP_PID=$!

echo "⏳ Esperando arranque de Baresip..."
sleep 5

echo "🌉 Iniciando Python Bridge (Con cables cruzados)..."
# Forzamos al script de Python a usar los cables inversos.
# Input (Lo que escucha Python) = CableOido.monitor (Lo que sale de Baresip)
# Output (Lo que habla Python)  = CableVirtual (Lo que entra a Baresip)
export PULSE_SOURCE=CableOido.monitor
export PULSE_SINK=CableVirtual

# Ejecutamos el bridge sin buffer (-u)
python3 -u bridge.py &
BRIDGE_PID=$!

# Esperar a que cualquiera de los procesos termine
wait -n $BARESIP_PID $BRIDGE_PID