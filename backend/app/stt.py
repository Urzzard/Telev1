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
        self.model_size = os.getenv("WHISPER_MODEL", "small")
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
            
            # NUEVO: Verificar que hay suficiente señal de audio
            volumen_promedio = np.abs(audio_data).mean()
            if volumen_promedio < 50:
                logger.warning(f"⚠️ Audio muy bajo ({volumen_promedio:.0f}), ignorando")
                return ""

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_file = tmp.name

            wav.write(tmp_file, 8000, audio_data)
            
            result = self.model.transcribe(
                tmp_file, 
                fp16=(self.device == "cuda"),
                language="es",
                initial_prompt="Conversación telefónica en español. Respuestas cortas: sí, no, hola, gracias."
            )
            texto = result["text"].strip()
            
            # NUEVO: Filtro agresivo de alucinaciones
            if not self._es_texto_valido(texto):
                logger.warning(f"⚠️ Texto filtrado (alucinación): '{texto[:50]}'")
                return ""

            logger.info(f"🗣️ Transcripción: '{texto}'")
            return texto

        except Exception as e:
            logger.error(f"❌ Error transcribiendo: {e}")
            return ""
        finally:
            if tmp_file and os.path.exists(tmp_file):
                os.remove(tmp_file)

    def _es_texto_valido(self, texto: str) -> bool:
        """Filtra alucinaciones de Whisper"""
        if not texto or len(texto) < 2:
            return False
        
        texto_lower = texto.lower()
        
        # Patrones de alucinación conocidos
        patrones_basura = [
            "subtítulos", "amara.org", "gracias por ver",
            "suscríbete", "subscribe", "like", 
            "<|", "|>",  # Tokens especiales de Whisper
            "♪", "♫", "🎵",  # Música
        ]
        
        if any(p in texto_lower for p in patrones_basura):
            return False
        
        # Detectar caracteres no latinos (chino, ruso, etc.)
        caracteres_exoticos = sum(1 for c in texto if ord(c) > 0x024F)
        if caracteres_exoticos > len(texto) * 0.1:  # Más del 10%
            return False
        
        # Detectar repeticiones excesivas (blufufufuf...)
        if len(texto) > 20:
            for i in range(2, 6):
                patron = texto[:i]
                if texto.count(patron) > 5:
                    return False
        
        # Texto muy largo sin espacios = basura
        palabras = texto.split()
        if palabras:
            palabra_mas_larga = max(len(p) for p in palabras)
            if palabra_mas_larga > 25:
                return False
        
        return True