import whisper
import logging
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
import tempfile
import numpy as np
import scipy.io.wavfile as wav

logger = logging.getLogger("STT")

# ========== SINGLETON ==========
_instance = None

def get_stt():
    """Retorna instancia única de SpeechToText"""
    global _instance
    if _instance is None:
        _instance = SpeechToText()
    return _instance
# ===============================

class SpeechToText:
    def __init__(self):
        self.model_size = os.getenv("WHISPER_MODEL", "base")
        self.device = "cuda" if os.getenv("USE_CUDA", "true").lower() == "true" else "cpu"
        self.model = None
        self.executor = ThreadPoolExecutor(max_workers=2)
        
        self.load_model()

    def load_model(self):
        try:
            logger.info(f"⏳ Cargando Whisper ({self.model_size}) en {self.device}...")
            self.model = whisper.load_model(self.model_size, device=self.device)
            logger.info(f"✅ Modelo Whisper cargado en {self.device.upper()}.")
        except Exception as e:
            logger.error(f"❌ Error cargando Whisper: {e}")

    async def transcribe(self, audio_bytes: bytes):
        if not self.model:
            logger.error("El modelo no está cargado.")
            return ""

        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(
            self.executor, 
            self._transcribe_sync, 
            audio_bytes
        )
        return text

    def _transcribe_sync(self, audio_bytes):
        tmp_file = None
        try:
            audio_data = np.frombuffer(audio_bytes, dtype=np.int16)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_file = tmp.name

            wav.write(tmp_file, 8000, audio_data)
            
            result = self.model.transcribe(
                tmp_file, 
                fp16=(self.device == "cuda"),
                language="es", 
                initial_prompt="Conversación telefónica. Usuario confirma identidad. Español de Perú."
            )
            texto = result["text"].strip()
            
            # Filtro de alucinaciones
            alucinaciones = ["gracias.", "subtítulos", "amara.org", "you"]
            if not texto or any(h in texto.lower() for h in alucinaciones):
                return ""

            logger.info(f"🗣️ Transcripción: '{texto}'")
            return texto

        except Exception as e:
            logger.error(f"❌ Error transcribiendo: {e}")
            return ""
        finally:
            if tmp_file and os.path.exists(tmp_file):
                os.remove(tmp_file)