import aiohttp
import logging
import os

logger = logging.getLogger("TTS")


class TextToSpeech:
    def __init__(self):
        # Selección de backend: "gemini" o "xtts"
        self.backend = os.getenv("TTS_BACKEND", "gemini").lower()
        
        # URLs de los servicios
        self.gemini_url = os.getenv("TTS_URL", "http://gemini-tts:5003")
        self.xtts_url = os.getenv("XTTS_URL", "http://xtts:8020")
        
        # Configuración XTTS
        self.xtts_speaker = os.getenv("XTTS_SPEAKER", "basic")
        self.xtts_language = os.getenv("XTTS_LANGUAGE", "es")
        
        logger.info(f"🔊 TTS Backend: {self.backend.upper()}")
        if self.backend == "xtts":
            logger.info(f"   URL: {self.xtts_url}")
            logger.info(f"   Speaker: {self.xtts_speaker}")
        else:
            logger.info(f"   URL: {self.gemini_url}")

    async def synthesize(self, text: str):
        """
        Genera audio a partir de texto.
        Retorna bytes de audio (MP3 para Gemini, WAV para XTTS).
        """
        if not text:
            return None
        
        if self.backend == "xtts":
            return await self._synthesize_xtts(text)
        else:
            return await self._synthesize_gemini(text)

    async def _synthesize_gemini(self, text: str):
        """Genera audio usando Gemini TTS (retorna MP3)"""
        url = f"{self.gemini_url}/synthesize"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={"text": text}) as response:
                    if response.status == 200:
                        audio_data = await response.read()
                        logger.info(f"✅ [Gemini] Audio generado ({len(audio_data)} bytes)")
                        return audio_data
                    else:
                        logger.error(f"❌ [Gemini] Error TTS: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"❌ [Gemini] Error conectando: {e}")
            return None

    async def _synthesize_xtts(self, text: str):
        """Genera audio usando XTTS v2 (retorna WAV)"""
        url = f"{self.xtts_url}/tts_to_audio/"
        
        payload = {
            "text": text,
            "speaker_wav": self.xtts_speaker,
            "language": self.xtts_language
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        audio_data = await response.read()
                        logger.info(f"✅ [XTTS] Audio generado ({len(audio_data)} bytes)")
                        return audio_data
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ [XTTS] Error TTS: {response.status} - {error_text[:100]}")
                        return None
        except Exception as e:
            logger.error(f"❌ [XTTS] Error conectando: {e}")
            return None

    async def synthesize_stream(self, text: str):
        """
        Streaming de audio (solo Gemini por ahora).
        XTTS streaming tiene bugs, usamos modo normal.
        """
        if not text:
            return
        
        if self.backend == "xtts":
            # XTTS: Fallback a síntesis normal (streaming tiene bugs)
            logger.info(f"🎤 [XTTS] Generando audio (sin streaming): '{text[:30]}...'")
            audio_data = await self._synthesize_xtts(text)
            if audio_data:
                # Enviar todo el audio como un solo chunk
                yield audio_data
            return
        
        # Gemini: Streaming real
        url = f"{self.gemini_url}/stream"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={"text": text}) as response:
                    if response.status == 200:
                        logger.info(f"🎤 [Gemini] Streaming: '{text[:30]}...'")
                        async for chunk in response.content.iter_chunked(4096):
                            yield chunk
                        logger.info(f"✅ [Gemini] Stream completado")
                    else:
                        logger.error(f"❌ [Gemini] Error stream: {response.status}")
        except Exception as e:
            logger.error(f"❌ [Gemini] Error en streaming: {e}")

    def get_audio_format(self) -> str:
        """Retorna el formato de audio del backend actual"""
        return "wav" if self.backend == "xtts" else "mp3"