import whisper
import logging
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
import tempfile
import numpy as np
import scipy.io.wavfile as wav

logger = logging.getLogger("STT")

class SpeechToText:
    def __init__(self):
        self.model_size = os.getenv("WHISPER_MODEL", "base")
        self.device = "cpu" # Cambia a "cuda" si usas GPU
        self.model = None
        
        # Executor para correr Whisper sin bloquear el servidor
        self.executor = ThreadPoolExecutor(max_workers=1)
        
        logger.info(f"⏳ Cargando modelo Whisper ({self.model_size}) en {self.device}...")
        # Carga diferida (lazy loading) o inmediata
        self.load_model()

    def load_model(self):
        try:
            logger.info(f"⏳ Cargando Whisper ({self.model_size})...")
            self.model = whisper.load_model(self.model_size, device=self.device)
            logger.info("✅ Modelo Whisper cargado y listo.")
        except Exception as e:
            logger.error(f"❌ Error cargando Whisper: {e}")

    async def transcribe(self, audio_bytes: bytes):
        """
        Recibe bytes de audio (WAV/PCM) y devuelve texto.
        Ejecuta la transcripción en un hilo separado.
        """
        if not self.model:
            logger.error("El modelo no está cargado.")
            return ""

        # Ejecutar en thread pool para no congelar FastAPI
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(
            self.executor, 
            self._transcribe_sync, 
            audio_bytes
        )
        return text

    def _transcribe_sync(self, audio_bytes):
        """Función síncrona que hace el trabajo pesado"""
        tmp_file = None
        try:
            audio_data = np.frombuffer(audio_bytes, dtype=np.int16)

            # Crear archivo temporal porque Whisper lee de archivo
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_file = tmp.name

            # Escribir el array numpy como archivo WAV (8000Hz)
            wav.write(tmp_file, 8000, audio_data)
            
            # Transcribir
            # fp16=False es necesario en CPU para evitar warnings
            result = self.model.transcribe(tmp_file, fp16=False, language="es", initial_prompt="Conversación telefónica de ventas y soporte técnico. Usuario confirma identidad. Español de Perú.")
            texto = result["text"].strip()
            
            # Filtro de alucinaciones comunes de Whisper
            if not texto or texto.lower() in ["gracias.", "subtítulos realizados por", "amara.org"]:
                return ""

            if texto:
                logger.info(f"🗣️ Transcripción: '{texto}'")
            
            return texto

        except Exception as e:
            logger.error(f"❌ Error transcribiendo: {e}")
            return ""
        finally:
            # Limpieza
            if tmp_file and os.path.exists(tmp_file):
                os.remove(tmp_file)