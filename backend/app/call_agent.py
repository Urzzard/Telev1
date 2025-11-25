import asyncio
from asyncio import Queue
import logging
import requests
import time
from app.tts import TextToSpeech
#from app.stt import SpeechToText
from app.stt import get_stt
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
            
            stt = get_stt()
            
            texto = await stt.transcribe(bytes(buffer_verificacion))
            
            if not texto or len(texto.strip()) < 2:
                logger.warning("⚠️ No se detectó voz clara")
                return True  # Posible buzón
            
            logger.info(f"📝 Transcripción inicial: '{texto}'")
            
            # Keywords de buzón (español e inglés)
            keywords_buzon = [
                # Español - palabras clave
                "buzón", "buzon", "busón", "buson",  # variantes
                "mensaje", "mensajes", 
                "tono", "señal", "senal",
                "deje su", "deja tu", "deje un",
                "después del", "despues del",
                "grabar", "grabación", "grabacion",
                "depositar",  # "no se puede depositar"
                "lleno",      # "buzón lleno"
                "no está disponible", "no esta disponible",
                "fuera de servicio",
                # Inglés
                "mailbox", "voicemail", "voice mail",
                "leave a message", "leave message",
                "after the beep", "beep", "tone", "record",
                "not available", "unavailable"
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

    
    async def _productor_tts(self, frases: list, queue: Queue):
        """Genera audios y los pone en la cola"""
        for i, texto in enumerate(frases):
            logger.info(f"🎨 Generando audio {i+1}/{len(frases)}: '{texto[:30]}...'")
            audio_data = await self._generar_audio(texto)
            if audio_data:
                await queue.put(audio_data)

    async def _consumidor_audio(self, queue: Queue):
        """Saca audios de la cola y los reproduce"""
        while True:
            audio_data = await queue.get()
            
            if audio_data is None:  # Señal de fin
                break
            
            pcm_data, duracion = audio_data
            if not await self._reproducir(pcm_data, duracion):
                logger.info("📴 Usuario colgó. Deteniendo script.")
                return


    async def iniciar_conversacion(self):
        """Flujo principal con generación paralela"""
        logger.info(f"📞 Iniciando llamada para {self.nombre}")
        await asyncio.sleep(0.5)
        
        # Detección de buzón
        es_buzon = await self.detectar_buzon_voz()
        
        if es_buzon:
            logger.warning("🚫 Buzón detectado. Abortando llamada.")
            await asyncio.sleep(0.5)
            self._colgar()
            return
        
        logger.info("✅ Usuario real confirmado. Iniciando script de bienvenida.")
        
        # ========== GENERACIÓN PARALELA ==========
        frases = self._construir_script_bienvenida()
        
        logger.info(f"🎨 Generando {len(frases)} audios en paralelo...")
        tareas = [self._generar_audio(texto) for texto in frases]
        resultados = await asyncio.gather(*tareas)
        
        # Filtrar None y mantener orden
        audios = [r for r in resultados if r is not None]
        logger.info(f"✅ {len(audios)} audios listos. Reproduciendo...")
        
        # ========== REPRODUCCIÓN ORDENADA ==========
        for i, (pcm_data, duracion) in enumerate(audios):
            if not await self._reproducir(pcm_data, duracion):
                logger.info("📴 Usuario colgó. Deteniendo script.")
                return  # Salir limpiamente, sin intentar colgar
        
        logger.info("✅ Script completado. Finalizando llamada...")
        await asyncio.sleep(0.5)
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
            logger.info(f"🔊 Audio listo: '{texto[:25]}...' ({duracion:.1f}s)")
            return (pcm_data, duracion)
        except Exception as e:
            logger.error(f"❌ Error generando audio: {e}")
            return None

    async def _reproducir(self, pcm_data, duracion):
        """Transmite audio por WebSocket con detección de desconexión"""
        chunk_size = 1024
        for i in range(0, len(pcm_data), chunk_size):
            try:
                # Verificar si el WebSocket sigue abierto
                if self.ws.client_state.name != "CONNECTED":
                    logger.warning("⚠️ WebSocket cerrado, deteniendo reproducción")
                    return False
                
                await self.ws.send_bytes(pcm_data[i:i+chunk_size])
                await asyncio.sleep(0.002)
            except Exception as e:
                logger.warning(f"⚠️ Conexión perdida durante reproducción")
                return False
        
        await asyncio.sleep(duracion)
        return True

    def _mp3_to_pcm(self, audio_bytes):
        import subprocess
        process = subprocess.Popen(
            ['ffmpeg', '-i', 'pipe:0', '-f', 's16le', '-ac', '1', '-ar', '8000', 'pipe:1'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        pcm_data, _ = process.communicate(input=audio_bytes)
        return pcm_data

    def _colgar(self):
        """Ordena colgar al sip-service"""
        try:
            requests.get("http://sip-service:8000/?b", timeout=0.5)
            logger.info("📞 Llamada finalizada")
        except requests.exceptions.Timeout:
            logger.info("📞 Llamada ya finalizada")
        except Exception as e:
            logger.warning(f"⚠️ Colgar: {e}")