import asyncio
import websockets
import sounddevice as sd
import json
import requests
import time
import os
import sys
import numpy as np

# --- CONFIGURACIÓN ---
BACKEND_WS_URL = os.getenv("WS_URL", "ws://backend:8000/ws/audio")

# CONSULTA: Usamos el comando "l" (List calls) para ver el estado
# La URL termina en /?l
BARESIP_STATUS_URL = "http://127.0.0.1:8000/?l"

SAMPLE_RATE = 8000
CHANNELS = 1
DTYPE = 'int16'
BLOCK_SIZE = 512


async def bridge_loop():
    print(f"🌉 BRIDGE: Iniciando (Usando dispositivos por defecto del entorno)...")

    try:
        print(f"🎤 Input Default: {sd.query_devices(kind='input')['name']}")
        print(f"🔊 Output Default: {sd.query_devices(kind='output')['name']}")
    except:
        pass
    
    # Variables de estado
    call_active_previously = False
    debug_counter = 0

    while True:
        try:
            # 1. Verificar estado de la llamada
            # Consultamos la URL /?l que devuelve la lista de llamadas
            is_call_active = check_active_call_http()

            # Log de "latido" cada 10 segundos para saber que el script sigue vivo
            debug_counter += 1
            if debug_counter % 20 == 0: # Cada ~10 segundos (20 * 0.5s)
                print(f"🆗 Bridge vivo. Estado llamada: {'ACTIVA' if is_call_active else 'INACTIVA'}")

            if is_call_active and not call_active_previously:
                print("📞 LLAMADA DETECTADA Y ESTABLECIDA: Conectando audio...")
                call_active_previously = True
            
            elif not is_call_active:
                if call_active_previously:
                    print("📴 LLAMADA FINALIZADA o NO CONECTADA.")
                    call_active_previously = False
                
                await asyncio.sleep(0.5)
                continue

            # 2. Si llegamos aquí, HAY LLAMADA ESTABLECIDA. Conectar WS.
            print(f"🔌 Intentando conectar al Backend: {BACKEND_WS_URL}")
            async with websockets.connect(BACKEND_WS_URL) as ws:
                print("✅ WebSocket Conectado! Transmitiendo audio...")
                
                loop = asyncio.get_event_loop()

                # Callback de entrada (Oído -> Backend)
                def callback_input(indata, frames, time, status):
                    if status: print(status, file=sys.stderr)
                    try:
                        asyncio.run_coroutine_threadsafe(ws.send(indata.tobytes()), loop)
                    except: pass

                # Abrir Streams
                input_stream = sd.InputStream(
                    channels=CHANNELS, samplerate=SAMPLE_RATE,
                    dtype=DTYPE, blocksize=BLOCK_SIZE, callback=callback_input
                )
                output_stream = sd.OutputStream(
                    channels=CHANNELS, samplerate=SAMPLE_RATE,
                    dtype=DTYPE
                )

                input_stream.start()
                output_stream.start()

                try:
                    # Bucle de recepción (Backend -> Boca)
                    async for message in ws:
                        # Chequeo constante de que la llamada siga viva
                        if not check_active_call_http():
                            print("📴 Corte detectado en Baresip.")
                            break
                        
                        if isinstance(message, bytes):
                            audio_chunk = np.frombuffer(message, dtype=np.int16)
                            output_stream.write(audio_chunk)

                except websockets.exceptions.ConnectionClosed:
                    print("⚠️ WebSocket cerrado por el backend.")
                finally:
                    input_stream.stop()
                    output_stream.stop()
                    print("🛑 Audio detenido.")

        except Exception as e:
            if "Connection refused" in str(e):
                print(f"⏳ Esperando Backend (Connection refused)...")
            else:
                print(f"⚠️ Error en ciclo principal: {e}")
            await asyncio.sleep(1)

def check_active_call_http():
    """Consulta la lista de llamadas (?l) y busca 'ESTABLISHED'"""
    try:
        # El truco: ?l simula presionar 'l' para listar llamadas
        res = requests.get(BARESIP_STATUS_URL, timeout=0.5)
        if res.status_code == 200:
            texto = res.text
            # Buscamos la palabra clave que indica que contestaron
            # "ESTABLISHED" aparece cuando el audio ya fluye
            if "ESTABLISHED" in texto:
                return True
    except Exception:
        pass
    return False

# def get_device_index(name_substring, is_input=True):
#     try:
#         devices = sd.query_devices()
#         # Solo la primera vez, imprimir lista completa para debug
#         if not hasattr(get_device_index, "debug_printed"):
#             print("\n🔍 DISPOSITIVOS DE AUDIO DETECTADOS:")
#             for i, dev in enumerate(devices):
#                 tipo = "ENTRADA" if dev['max_input_channels'] > 0 else "SALIDA"
#                 print(f"   [{i}] {dev['name']} ({tipo})")
#             get_device_index.debug_printed = True
#             print("-" * 30)

#         for i, dev in enumerate(devices):
#             check_channels = dev['max_input_channels'] if is_input else dev['max_output_channels']
#             # Búsqueda más flexible (case insensitive)
#             if name_substring.lower() in dev['name'].lower() and check_channels > 0:
#                 return i
#     except Exception as e:
#         print(f"Error buscando dispositivos: {e}")
#     return None

if __name__ == "__main__":
    time.sleep(5) # Dar tiempo a que Baresip arranque
    print("🚀 Bridge.py iniciado.")
    try:
        asyncio.run(bridge_loop())
    except KeyboardInterrupt:
        pass