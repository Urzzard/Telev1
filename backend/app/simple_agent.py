import asyncio
import logging
import requests
import math
from app.tts import TextToSpeech

logger = logging.getLogger("SimpleAgent")

class SimpleAudioTester:
    def __init__(self, websocket):
        self.ws = websocket
        self.tts = TextToSpeech()
        self.baresip_hangup_url = "http://sip-service:8000/?b"
        
        # Constantes de audio para Baresip (8kHz, 16-bit, Mono)
        self.BYTES_PER_SECOND = 16000 # 8000 Hz * 2 bytes

    async def run_test(self):
        logger.info("🧪 INICIANDO PRUEBA PRECISA (Segmentada)")
        await asyncio.sleep(1)

        # 1. Lista de frases (Segmentación para menor latencia inicial)
        # El sistema procesará la primera rápido, y mientras la reproduce, procesa las siguientes.
        guion = [
            "Hola.",
            "Esta es una prueba de sincronización.",
            "Voy a contar rapido: uno, dos, tres.",
            "Al terminar esta frase, la llamada se cortará automáticamente.",
            "Adiós."
        ]

        for frase in guion:
            await self.procesar_frase(frase)

        logger.info("✅ Guion finalizado. Colgando...")
        self.hangup()

    async def procesar_frase(self, texto):
        """Genera audio, calcula duración y lo transmite"""
        logger.info(f"🗣️ Procesando: '{texto}'")
        
        # A. Generar (TTS)
        audio_mp3 = await self.tts.synthesize(texto)
        if not audio_mp3:
            return

        # B. Convertir a PCM (WAV raw)
        pcm_data = self.convertir_a_pcm(audio_mp3)
        
        # C. CALCULAR DURACIÓN EXACTA
        # Formula: Bytes / (SampleRate * BitDepth/8 * Channels)
        duracion_segundos = len(pcm_data) / self.BYTES_PER_SECOND
        logger.info(f"⏱️ Duración audio: {duracion_segundos:.2f}s ({len(pcm_data)} bytes)")

        # D. Transmitir
        # Enviamos los datos al socket
        chunk_size = 1024
        for i in range(0, len(pcm_data), chunk_size):
            try:
                await self.ws.send_bytes(pcm_data[i:i+chunk_size])
                # Pequeña pausa técnica para no saturar la red, 
                # pero NO es la pausa de reproducción.
                await asyncio.sleep(0.002) 
            except:
                return

        # E. ESPERAR A QUE TERMINE DE SONAR
        # Aquí está la clave: Esperamos exactamente lo que dura el audio
        # para que no se corte ni se pise con el siguiente.
        logger.info(f"⏳ Esperando playback ({duracion_segundos:.2f}s)...")
        await asyncio.sleep(duracion_segundos)

    def convertir_a_pcm(self, audio_bytes):
        """Convierte MP3 a PCM 8000Hz 16-bit"""
        import subprocess
        process = subprocess.Popen(
            ['ffmpeg', '-i', 'pipe:0', '-f', 's16le', '-ac', '1', '-ar', '8000', 'pipe:1'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        pcm_data, _ = process.communicate(input=audio_bytes)
        return pcm_data

    def hangup(self):
        try:
            requests.get(self.baresip_hangup_url, timeout=1)
            logger.info("📞 Llamada finalizada por el sistema.")
        except Exception as e:
            logger.error(f"⚠️ Error al colgar: {e}")