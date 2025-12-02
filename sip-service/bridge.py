import asyncio
import websockets
import sounddevice as sd
import json
import requests
import time
import os
import sys
import numpy as np
from enum import Enum

# --- CONFIGURACIÓN ---
BACKEND_WS_URL = os.getenv("WS_URL", "ws://backend:8000/ws/audio")
BARESIP_STATUS_URL = "http://127.0.0.1:8000/?l"
BARESIP_HANGUP_URL = "http://127.0.0.1:8000/?b"

SAMPLE_RATE = 8000
CHANNELS = 1
DTYPE = 'int16'
BLOCK_SIZE = 1024

# Configuración de timeouts
TIMEOUT_MARCADO = 25  # Segundos máximos marcando antes de abortar

# --- ESTADOS DE LLAMADA ---
class CallState(Enum):
    IDLE = "idle"
    DIALING = "dialing"      # EARLY detectado
    ESTABLISHED = "established"

def check_call_state():
    """
    Consulta el estado actual de la llamada en Baresip.
    Retorna: (CallState, texto_completo)
    """
    try:
        res = requests.get(BARESIP_STATUS_URL, timeout=0.5)
        if res.status_code == 200:
            texto = res.text
            
            # Sin llamadas activas
            if "Active calls (0)" in texto:
                return (CallState.IDLE, texto)
            
            # Llamada en estado EARLY (Marcando)
            if "EARLY" in texto:
                return (CallState.DIALING, texto)
            
            # Llamada ESTABLECIDA (Contestado o Buzón)
            if "ESTABLISHED" in texto:
                return (CallState.ESTABLISHED, texto)
    except Exception as e:
        # Si falla la consulta, asumimos IDLE
        pass
    
    return (CallState.IDLE, "")

def get_current_call_id():
    """Consulta al backend el ID del empleado de la llamada actual"""
    try:
        res = requests.get("http://backend:8000/current_call_id", timeout=1)
        if res.status_code == 200:
            data = res.json()
            return data.get('id')
    except:
        pass
    return None

def colgar_llamada():
    """Envía comando de colgar a Baresip"""
    try:
        requests.get(BARESIP_HANGUP_URL, timeout=1)
        print("📞 Comando de colgar enviado a Baresip")
        return True
    except Exception as e:
        print(f"❌ Error al colgar: {e}")
        return False

def notificar_llamada_fallida(employee_id: int, reason: str):
    """Notifica al backend que la llamada falló"""
    try:
        response = requests.post(
            "http://backend:8000/call_failed",
            params={"id": employee_id, "reason": reason},
            timeout=5
        )
        if response.status_code == 200:
            print(f"✅ Backend notificado: llamada fallida ({reason})")
        else:
            print(f"⚠️ Error notificando backend: {response.status_code}")
    except Exception as e:
        print(f"❌ Error notificando backend: {e}")

async def bridge_loop():
    """Loop principal del bridge: maneja estados y audio"""
    print(f"🌉 BRIDGE: Iniciando...")
    print(f"⚙️ Configuración: Timeout marcado={TIMEOUT_MARCADO}s")

    try:
        print(f"🎤 Input: {sd.query_devices(kind='input')['name']}")
        print(f"🔊 Output: {sd.query_devices(kind='output')['name']}")
    except:
        print("⚠️ No se pudieron listar dispositivos de audio")
    
    # Variables de estado
    call_active_previously = False
    timestamp_inicio_marcado = None
    duracion_fase_marcado = 0
    debug_counter = 0
    ultimo_log_tiempo = 0

    while True:
        try:
            # Consultar estado actual de Baresip
            estado, texto_baresip = check_call_state()
            
            # Log de "heartbeat" cada 10 segundos
            debug_counter += 1
            if debug_counter % 20 == 0:
                print(f"💓 Bridge activo. Estado: {estado.value}")

            # ===== ESTADO: DIALING (Marcando - EARLY) =====
            if estado == CallState.DIALING:
                if timestamp_inicio_marcado is None:
                    # Primera vez que detectamos el marcado
                    timestamp_inicio_marcado = time.time()
                    print("📞 MARCANDO... Iniciando timer de timeout")
                
                # Calcular tiempo transcurrido desde que empezó a marcar
                tiempo_marcando = time.time() - timestamp_inicio_marcado
                
                # Log progresivo cada 5 segundos
                if int(tiempo_marcando) % 5 == 0 and int(tiempo_marcando) != ultimo_log_tiempo:
                    print(f"⏳ Marcando... {tiempo_marcando:.0f}s / {TIMEOUT_MARCADO}s")
                    ultimo_log_tiempo = int(tiempo_marcando)
                
                # TIMEOUT: Si pasan más de X segundos sin contestar
                if tiempo_marcando > TIMEOUT_MARCADO:
                    print(f"⏱️ TIMEOUT: {tiempo_marcando:.1f}s marcando sin respuesta")
                    print(f"🚫 Abortando llamada (posible no contesta o va a entrar a buzón)")
                    
                    colgar_llamada()

                    employee_id = get_current_call_id()
                    if employee_id:
                        notificar_llamada_fallida(employee_id, "timeout_no_contesta")

                    timestamp_inicio_marcado = None
                    ultimo_log_tiempo = 0
                    
                    # Esperar a que Baresip procese el comando
                    await asyncio.sleep(2)
                    continue
                
                # Si todavía está marcando, esperar y volver a chequear
                await asyncio.sleep(0.5)
                continue
            
            # ===== ESTADO: ESTABLISHED (Contestado o Buzón) =====
            elif estado == CallState.ESTABLISHED:
                # Calcular cuánto duró la fase de marcado
                if timestamp_inicio_marcado is not None:
                    duracion_fase_marcado = time.time() - timestamp_inicio_marcado
                    print(f"✅ LLAMADA ESTABLECIDA después de {duracion_fase_marcado:.1f}s de marcado")
                    
                    # INDICADOR DE POSIBLE BUZÓN (análisis)
                    if duracion_fase_marcado > 22:
                        print(f"⚠️ ALERTA: Tardó {duracion_fase_marcado:.1f}s en establecer")
                        print(f"⚠️ Posible buzón de voz (típicamente >22s)")
                        # FASE 2: Aquí podrías decidir colgar inmediatamente
                    
                    timestamp_inicio_marcado = None
                    ultimo_log_tiempo = 0
                
                if not call_active_previously:
                    print("🎙️ Iniciando transmisión de audio con backend...")
                    call_active_previously = True
                
                # === CONEXIÓN WEBSOCKET CON BACKEND ===
                # Obtener ID del empleado actual
                employee_id = get_current_call_id()

                if employee_id:
                    # Pasar duración de marcado al backend para detección de buzón
                    duracion_int = int(duracion_fase_marcado)
                    ws_url = f"{BACKEND_WS_URL}?id={employee_id}&duracion={duracion_int}"
                    print(f"🔌 Conectando WebSocket con ID: {employee_id}, duración marcado: {duracion_int}s")
                else:
                    ws_url = BACKEND_WS_URL
                    print(f"⚠️ No se obtuvo ID, usando URL por defecto")

                
                try:
                    async with websockets.connect(ws_url) as ws:
                        print("✅ WebSocket conectado. Audio en tiempo real activo.")
                        
                        loop = asyncio.get_event_loop()

                        # Callback de entrada (Micrófono virtual -> Backend)
                        def callback_input(indata, frames, time_info, status):
                            if status:
                                print(f"⚠️ Audio input: {status}", file=sys.stderr)
                            try:
                                asyncio.run_coroutine_threadsafe(
                                    ws.send(indata.tobytes()), 
                                    loop
                                )
                            except:
                                pass

                        # Abrir streams de audio
                        input_stream = sd.InputStream(
                            channels=CHANNELS, 
                            samplerate=SAMPLE_RATE,
                            dtype=DTYPE, 
                            blocksize=BLOCK_SIZE, 
                            callback=callback_input
                        )
                        output_stream = sd.OutputStream(
                            channels=CHANNELS, 
                            samplerate=SAMPLE_RATE,
                            dtype=DTYPE
                        )

                        input_stream.start()
                        output_stream.start()
                        print("🎧 Streams de audio iniciados")

                        try:
                            # Loop de recepción (Backend -> Parlante virtual)
                            async for message in ws:
                                # CRÍTICO: Verificar que la llamada siga activa
                                estado_actual, _ = check_call_state()
                                if estado_actual != CallState.ESTABLISHED:
                                    print("📴 Llamada terminada durante transmisión")
                                    break
                                
                                # Reproducir audio recibido del backend
                                if isinstance(message, bytes):
                                    audio_chunk = np.frombuffer(message, dtype=np.int16)
                                    output_stream.write(audio_chunk)

                        except websockets.exceptions.ConnectionClosed:
                            print("⚠️ WebSocket cerrado por el backend")
                        finally:
                            # Limpiar streams
                            input_stream.stop()
                            output_stream.stop()
                            input_stream.close()
                            output_stream.close()
                            print("🛑 Streams de audio detenidos")

                except Exception as e:
                    if "Connection refused" in str(e):
                        print(f"⏳ Backend no disponible, reintentando...")
                    else:
                        print(f"❌ Error en WebSocket: {e}")
                    await asyncio.sleep(1)
            
            # ===== ESTADO: IDLE (Sin llamada activa) =====
            elif estado == CallState.IDLE:
                if call_active_previously:
                    print("📴 LLAMADA FINALIZADA - Sistema listo para siguiente llamada")
                    call_active_previously = False
                
                # Reset completo de variables
                timestamp_inicio_marcado = None
                duracion_fase_marcado = 0
                ultimo_log_tiempo = 0
                
                # En IDLE, polling más lento
                await asyncio.sleep(0.5)
            
        except Exception as e:
            print(f"⚠️ Error en loop principal: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(1)

if __name__ == "__main__":
    print("🚀 Iniciando Bridge v2.0 (Manejo de Estados)")
    time.sleep(5)  # Dar tiempo a que Baresip arranque
    
    try:
        asyncio.run(bridge_loop())
    except KeyboardInterrupt:
        print("\n👋 Bridge detenido por usuario")