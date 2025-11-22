import aiohttp
import logging
import os
import base64

logger = logging.getLogger("TTS")

class TextToSpeech:
    def __init__(self):
        self.tts_url = os.getenv("TTS_URL", "http://gemini-tts:5003")
        logger.info(f"🔊 Cliente TTS configurado hacia: {self.tts_url}")

    async def synthesize(self, text: str):
        """
        Envía texto a Gemini-TTS y recibe audio (bytes).
        """
        if not text:
            return None

        url = f"{self.tts_url}/synthesize"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={"text": text}) as response:
                    if response.status == 200:
                        # El servicio devuelve bytes directos (audio/mpeg)
                        audio_data = await response.read()
                        logger.info(f"✅ Audio generado ({len(audio_data)} bytes)")
                        return audio_data
                    else:
                        logger.error(f"❌ Error TTS: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"❌ Error conectando con TTS: {e}")
            return None