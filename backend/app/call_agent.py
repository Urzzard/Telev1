import asyncio
import logging
import requests
import time
from app.tts import TextToSpeech
from app.stt import SpeechToText
from app.database import EmployeeRepository
from collections import deque

logger = logging.getLogger("CallAgent")

class CallAgent:
    def __init__(self, websocket, employee_id: int):
        self.ws = websocket
        self.employee_id = employee_id
        self.tts = TextToSpeech()
        self.db = EmployeeRepository()
        
        # Audio
        self.BYTES_PER_SECOND = 16000
        self.audio_queue = deque()
        
        # Duración de marcado (se asigna desde main.py)
        self.duracion_marcado = 0
        
        # Cargar datos del empleado POR ID
        self.employee = self.db.get_employee_by_id(self.employee_id)
        
        if self.employee:
            self.nombre = self.employee.get('nombre', 'colaborador')
            self.puesto = self.employee.get('puesto', 'nuevo ingreso')
            self.fecha_inicio = self.employee.get('fecha_inicio', 'pronto')
            logger.info(f"📋 Empleado cargado: {self.nombre} - {self.puesto}")
        else:
            # Si no existe, usar datos por defecto
            self.nombre = "colaborador"
            self.puesto = "nuevo ingreso"
            self.fecha_inicio = "pronto"
            logger.error(f"❌ Empleado con ID {self.employee_id} no encontrado")

    async def detectar_buzon_voz(self):
        """
        Captura los primeros 3s de audio después de ESTABLISHED
        y verifica si es buzón usando Whisper.
        
        Returns:
            True si es buzón, False si es persona real
        """
        logger.info("🔍 Verificando si es buzón de voz...")
        
        buffer_verificacion = bytearray()
        tiempo_inicio = time.time()
        tiempo_limite = 3.0  # segundos
        
        # Capturar audio durante 3 segundos
        while (time.time() - tiempo_inicio) < tiempo_limite:
            try:
                # Timeout corto para no bloquear
                data = await asyncio.wait_for(
                    self.ws.receive_bytes(), 
                    timeout=0.1
                )
                buffer_verificacion.extend(data)
            except asyncio.TimeoutError:
                # No hay audio, seguir esperando
                continue
            except Exception as e:
                logger.error(f"❌ Error capturando audio: {e}")
                break
        
        # Verificar si capturamos suficiente audio
        if len(buffer_verificacion) < 8000:  # Menos de 0.5s de audio
            logger.warning("⚠️ Audio insuficiente capturado (silencio prolongado)")
            return True  # Asumir buzón si hay silencio
        
        # Transcribir con Whisper
        try:
            
            stt = SpeechToText()
            
            texto = await stt.transcribe(bytes(buffer_verificacion))
            
            if not texto or len(texto.strip()) < 2:
                logger.warning("⚠️ No se detectó voz clara")
                return True  # Posible buzón
            
            logger.info(f"📝 Transcripción inicial: '{texto}'")
            
            # Keywords de buzón (español e inglés)
            keywords_buzon = [
                # Español
                "mensaje", "tono", "señal", "buzón", "buzon", 
                "deje su", "deja tu", "después del", "despues del",
                "grabar", "grabación", "grabacion",
                # Inglés
                "mailbox", "voicemail", "leave a message", 
                "after the beep", "beep", "tone", "record"
            ]
            
            texto_lower = texto.lower()
            
            for keyword in keywords_buzon:
                if keyword in texto_lower:
                    logger.warning(f"🚫 BUZÓN DETECTADO: Palabra clave '{keyword}' encontrada")
                    return True
            
            logger.info(f"✅ Respuesta humana confirmada")
            return False
            
        except Exception as e:
            logger.error(f"❌ Error transcribiendo: {e}")
            return False  # En caso de error, asumir humano para no perder llamadas

    async def iniciar_conversacion(self):
        """Flujo principal de la llamada"""

        logger.info(f"📞 Iniciando llamada para {self.nombre}")
        await asyncio.sleep(1)  # Estabilizar audio
        
        # ========== DETECCIÓN DE BUZÓN (MEJORADA) ==========
        # Detectar buzón en todas las llamadas
        es_buzon = await self.detectar_buzon_voz()
        
        if es_buzon:
            logger.warning("🚫 Buzón detectado. Abortando llamada para evitar costos.")
            await asyncio.sleep(0.5)
            self._colgar()
            return  # Salir sin reproducir nada
        
        logger.info("✅ Usuario real confirmado. Iniciando script de bienvenida.")
        
        # ========== FLUJO NORMAL DE BIENVENIDA ==========
        frases = self._construir_script_bienvenida()
        
        # Generar todos los audios en paralelo
        logger.info(f"🎨 Generando {len(frases)} audios...")
        tareas = [self._generar_audio(f) for f in frases]
        audios = await asyncio.gather(*tareas)
        
        # Agregar a cola
        for audio_data in audios:
            if audio_data:
                self.audio_queue.append(audio_data)
        
        logger.info(f"✅ {len(self.audio_queue)} audios listos. Reproduciendo...")
        
        # Reproducir secuencialmente
        while self.audio_queue:
            pcm_data, duracion = self.audio_queue.popleft()
            await self._reproducir(pcm_data, duracion)
        
        logger.info("✅ Script completado. Finalizando llamada...")
        await asyncio.sleep(1)
        self._colgar()

    def _construir_script_bienvenida(self):
        """Construye el script personalizado según datos del CSV"""
        return [
            f"Hola, buenas tardes.",
            f"Me comunico de Seils Land.",
            f"¿Hablo con {self.nombre}?",
            f"Perfecto. Te damos la bienvenida a nuestra empresa.",
            f"Has sido contratado como {self.puesto}.",
            f"Tu fecha de inicio es el {self.fecha_inicio}.",
            f"Pronto recibirás más información por correo.",
            f"Muchas gracias y bienvenido al equipo.",
            f"Que tengas excelente día. Hasta pronto."
        ]

    async def _generar_audio(self, texto):
        """Genera audio y retorna (pcm_data, duracion)"""
        try:
            audio_mp3 = await self.tts.synthesize(texto)
            if not audio_mp3:
                return None
            
            pcm_data = self._mp3_to_pcm(audio_mp3)
            duracion = len(pcm_data) / self.BYTES_PER_SECOND
            return (pcm_data, duracion)
        except Exception as e:
            logger.error(f"❌ Error generando audio: {e}")
            return None

    async def _reproducir(self, pcm_data, duracion):
        """Transmite audio por WebSocket"""
        chunk_size = 1024
        for i in range(0, len(pcm_data), chunk_size):
            try:
                await self.ws.send_bytes(pcm_data[i:i+chunk_size])
                await asyncio.sleep(0.002)
            except Exception as e:
                logger.error(f"❌ Error enviando audio: {e}")
                return
        
        await asyncio.sleep(duracion)

    def _mp3_to_pcm(self, audio_bytes):
        import subprocess
        process = subprocess.Popen(
            ['ffmpeg', '-i', 'pipe:0', '-f', 's16le', '-ac', '1', '-ar', '8000', 'pipe:1'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        pcm_data, _ = process.communicate(input=audio_bytes)
        return pcm_data

    def _colgar(self):
        try:
            requests.get("http://sip-service:8000/?b", timeout=1)
            logger.info("📞 Llamada finalizada")
        except Exception as e:
            logger.error(f"⚠️ Error al colgar: {e}")