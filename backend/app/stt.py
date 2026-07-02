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

# ========== GETTER ==========
def get_stt():
    """Retorna instancia única del STT (Faster Whisper, CUDA)"""
    global _instance
    if _instance is None:
        logger.info(">>> Usando Faster Whisper <<<")
        _instance = FasterWhisperSTT()
    return _instance
# ===============================


# ========== FASTER WHISPER ==========
class FasterWhisperSTT:
    def __init__(self):
        self.model_size = os.getenv("WHISPER_MODEL", "small")
        self.compute_type = "float16"
        self.model = None
        self.executor = ThreadPoolExecutor(max_workers=2)

        self.load_model()

    def load_model(self):
        try:
            from faster_whisper import WhisperModel
            logger.info(f"⏳ Cargando Faster Whisper ({self.model_size}) en CUDA...")
            self.model = WhisperModel(
                self.model_size,
                device="cuda",
                compute_type=self.compute_type
            )
            logger.info("✅ Faster Whisper cargado en CUDA.")
        except Exception as e:
            logger.error(f"❌ Error cargando Faster Whisper: {e}")

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

            volumen_promedio = np.abs(audio_data).mean()
            if volumen_promedio < 50:
                logger.warning(f"⚠️ Audio muy bajo ({volumen_promedio:.0f}), ignorando")
                return ""

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_file = tmp.name

            wav.write(tmp_file, 8000, audio_data)

            segments, info = self.model.transcribe(
                tmp_file,
                language="es",
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )

            texto = " ".join([s.text for s in segments]).strip()

            if not self._es_texto_valido(texto):
                logger.warning(f"⚠️ Texto filtrado (alucinación): '{texto[:50]}'")
                return ""

            logger.info(f"🗣️ Transcripción (Faster): '{texto}'")
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

        patrones_basura = [
            "subtítulos", "amara.org", "gracias por ver",
            "suscríbete", "subscribe", "like",
            "<|", "|>",
            "♪", "♫", "🎵",
        ]

        if any(p in texto_lower for p in patrones_basura):
            return False

        caracteres_exoticos = sum(1 for c in texto if ord(c) > 0x024F)
        if caracteres_exoticos > len(texto) * 0.1:
            return False

        palabras = texto_lower.split()
        if len(palabras) >= 5:
            from collections import Counter
            contador = Counter(palabras)
            palabra_mas_comun, frecuencia = contador.most_common(1)[0]

            if frecuencia > len(palabras) * 0.5:
                logger.warning(f"⚠️ Alucinación detectada: '{palabra_mas_comun}' x{frecuencia}")
                return False

        if len(texto) > 20:
            for i in range(2, 8):
                patron = texto[:i]
                repeticiones = texto.count(patron)
                if repeticiones > 5 and len(patron) * repeticiones > len(texto) * 0.5:
                    logger.warning(f"⚠️ Patrón repetitivo detectado: '{patron}' x{repeticiones}")
                    return False

        if palabras:
            palabra_mas_larga = max(len(p) for p in palabras)
            if palabra_mas_larga > 25:
                return False

        return True
