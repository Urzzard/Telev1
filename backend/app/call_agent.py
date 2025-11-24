import asyncio
import logging
import requests
from app.tts import TextToSpeech
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

    async def iniciar_conversacion(self):
        """Flujo principal de la llamada"""
        logger.info(f"📞 Iniciando llamada para {self.nombre}")
        await asyncio.sleep(1)  # Estabilizar audio
        
        # Script fijo de bienvenida (FASE 2)
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
            except:
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