import aiohttp
import logging
import os
import re

def preparar_texto_para_tts(texto: str) -> str:
    """
    Preprocesa texto para que el TTS lo pronuncie naturalmente.
    Convierte siglas, fechas y URLs a texto pronunciable.
    """
    if not texto:
        return texto

    # ===== PASO 1: PROTEGER a.m./p.m. antes de cualquier procesamiento =====
    texto = re.sub(r'(\d{1,2}):(\d{2})\s*a\.?m\.?', r'\1:\2 de la mañana', texto)
    texto = re.sub(r'(\d{1,2}):(\d{2})\s*p\.?m\.?', r'\1:\2 de la tarde', texto)
    texto = re.sub(r'\ba\.?m\.?\b', 'de la mañana', texto)
    texto = re.sub(r'\bp\.?m\.?\b', 'de la tarde', texto)
    
    # ===== SIGLAS =====
    texto = re.sub(r'\bRRHH\b', 'Recursos Humanos', texto)
    texto = re.sub(r'\bR\.R\.H\.H\.?\b', 'Recursos Humanos', texto)
    texto = re.sub(r'\bDNI\b', 'D N I', texto)
    
    # ===== HORARIOS =====
    texto = re.sub(r'\b9:00\s*(a\.?m\.?)?', '9 de la mañana', texto)
    texto = re.sub(r'\b18:00\b', '6 de la tarde', texto)
    texto = re.sub(r'\b6:00\s*(p\.?m\.?)?', '6 de la tarde', texto)
    texto = re.sub(r'\b13:00\b', '1 de la tarde', texto)
    texto = re.sub(r'\b14:00\b', '2 de la tarde', texto)
    
    # ===== FECHAS dd/mm/yyyy =====
    def convertir_fecha(match):
        dia, mes, año = match.groups()
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                 "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        try:
            dia_num = int(dia)
            mes_num = int(mes)
            return f"{dia_num} de {meses[mes_num-1]} del {año}"
        except:
            return match.group(0)
    
    texto = re.sub(r'(\d{1,2})/(\d{1,2})/(\d{4})', convertir_fecha, texto)
    
    # ===== URLs - CONVERTIR A TEXTO PRONUNCIABLE =====
    def url_a_texto(match):
        url = match.group(0)
        url = re.sub(r'^https?://', '', url)
        resultado = url
        resultado = resultado.replace(':', ' puerto ')
        resultado = resultado.replace('/', ' diagonal ')
        resultado = resultado.replace('.', ' punto ')
        resultado = resultado.replace('-', ' guión ')
        resultado = resultado.replace('_', ' guión bajo ')
        
        resultado = re.sub(r'8088', 'ocho cero ocho ocho', resultado)
        resultado = re.sub(r'(\d)', lambda m: {
            '0': 'cero', '1': 'uno', '2': 'dos', '3': 'tres', '4': 'cuatro',
            '5': 'cinco', '6': 'seis', '7': 'siete', '8': 'ocho', '9': 'nueve'
        }.get(m.group(1), m.group(1)), resultado)
        
        resultado = re.sub(r'\s+', ' ', resultado).strip()
        return resultado
    
    # Detectar URLs (con o sin protocolo)
    texto = re.sub(
        r'[a-zA-Z0-9][-a-zA-Z0-9]*(?:\.[a-zA-Z0-9][-a-zA-Z0-9]*)*\.(com|net|org|pe|es|io|gov|edu|info)[^\s,]*',
        url_a_texto,
        texto,
        flags=re.IGNORECASE
    )
    
    # ===== LIMPIEZA FINAL =====
    texto = re.sub(r'\s+', ' ', texto).strip()
    
    return texto

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

        # Configuración Kokoro
        self.kokoro_url = os.getenv("KOKORO_URL", "http://kokoro:8880")
        self.kokoro_voice = os.getenv("KOKORO_VOICE", "ef_dora")

        # Configuración F5
        self.f5_url = os.getenv("F5_URL", "http://f5:8881")

        # Configuración CosyVoice3
        self.cosyvoice_url = os.getenv("COSYVOICE_URL", "http://cosyvoice:8030")
        self.cosyvoice_voice = os.getenv("COSYVOICE_VOICE", "salesland")
        self.cosyvoice_speed = float(os.getenv("COSYVOICE_SPEED", "1.0"))

        logger.info(f"🔊 TTS Backend: {self.backend.upper()}")
        if self.backend == "xtts":
            logger.info(f"   URL: {self.xtts_url}")
            logger.info(f"   Speaker: {self.xtts_speaker}")
        elif self.backend == "kokoro":
            logger.info(f"   URL: {self.kokoro_url}")
            logger.info(f"   Voice: {self.kokoro_voice}")
        elif self.backend == "f5":
            logger.info(f"   URL: {self.f5_url}")
        elif self.backend == "cosyvoice":
            logger.info(f"   URL: {self.cosyvoice_url}")
            logger.info(f"   Voice: {self.cosyvoice_voice}")
        else:
            logger.info(f"   URL: {self.gemini_url}")

    async def synthesize(self, text: str):
        """
        Genera audio a partir de texto.
        Retorna bytes de audio WAV (XTTS/Kokoro) o MP3 (Gemini).
        """
        if not text:
            return None

        text = preparar_texto_para_tts(text)

        if self.backend == "xtts":
            return await self._synthesize_xtts(text)
        elif self.backend == "kokoro":
            return await self._synthesize_kokoro(text)
        elif self.backend == "f5":
            return await self._synthesize_f5(text)
        elif self.backend == "cosyvoice":
            return await self._synthesize_cosyvoice(text)
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
            "language": self.xtts_language,
            # Parámetros para mejorar naturalidad
            "temperature": 0.65,      # Menos variabilidad (más consistente)
            "speed": 1.0,             # Velocidad normal
            "length_penalty": 1.0,    # Penalización de longitud
            "repetition_penalty": 5.0, # Evitar repeticiones
            "top_k": 50,              # Diversidad controlada
            "top_p": 0.85,            # Nucleus sampling
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

    async def _synthesize_kokoro(self, text: str):
        """Genera audio WAV completo usando Kokoro-FastAPI"""
        url = f"{self.kokoro_url}/v1/audio/speech"
        payload = {
            "model": "kokoro",
            "input": text,
            "voice": self.kokoro_voice,
            "response_format": "wav",
            "speed": 0.92,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        audio_data = await response.read()
                        logger.info(f"✅ [Kokoro] Audio generado ({len(audio_data)} bytes)")
                        return audio_data
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ [Kokoro] Error TTS: {response.status} - {error_text[:100]}")
                        return None
        except Exception as e:
            logger.error(f"❌ [Kokoro] Error conectando: {e}")
            return None

    async def _synthesize_f5(self, text: str):
        """Genera audio WAV completo usando F5-Spanish"""
        url = f"{self.f5_url}/v1/audio/speech"
        payload = {
            "input": text,
            "response_format": "wav",
            "speed": 0.9,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        audio_data = await response.read()
                        logger.info(f"✅ [F5] Audio generado ({len(audio_data)} bytes)")
                        return audio_data
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ [F5] Error TTS: {response.status} - {error_text[:100]}")
                        return None
        except Exception as e:
            logger.error(f"❌ [F5] Error conectando: {e}")
            return None

    async def _synthesize_f5_stream(self, text: str):
        """Streaming de audio PCM crudo desde F5-Spanish"""
        url = f"{self.f5_url}/v1/audio/speech"
        payload = {
            "input": text,
            "response_format": "pcm",
            "speed": 0.9,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    if response.status == 200:
                        async for chunk in response.content.iter_chunked(4800):
                            if chunk:
                                yield chunk
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ [F5] Error stream: {response.status} - {error_text[:100]}")
        except Exception as e:
            logger.error(f"❌ [F5] Error en streaming: {e}")

    async def _synthesize_cosyvoice(self, text: str):
        """Genera audio WAV completo usando CosyVoice3"""
        url = f"{self.cosyvoice_url}/v1/audio/speech"
        payload = {
            "input": text,
            "voice": self.cosyvoice_voice,
            "response_format": "wav",
            "speed": self.cosyvoice_speed,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        audio_data = await response.read()
                        logger.info(f"✅ [CosyVoice] Audio generado ({len(audio_data)} bytes)")
                        return audio_data
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ [CosyVoice] Error TTS: {response.status} - {error_text[:100]}")
                        return None
        except Exception as e:
            logger.error(f"❌ [CosyVoice] Error conectando: {e}")
            return None

    async def _synthesize_cosyvoice_stream(self, text: str):
        """Streaming de audio PCM crudo (int16 24kHz) desde CosyVoice3"""
        url = f"{self.cosyvoice_url}/v1/audio/speech"
        payload = {
            "input": text,
            "voice": self.cosyvoice_voice,
            "response_format": "pcm",
            "speed": self.cosyvoice_speed,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    if response.status == 200:
                        async for chunk in response.content.iter_chunked(4800):
                            if chunk:
                                yield chunk
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ [CosyVoice] Error stream: {response.status} - {error_text[:100]}")
        except Exception as e:
            logger.error(f"❌ [CosyVoice] Error en streaming: {e}")

    async def _synthesize_kokoro_stream(self, text: str):
        """Streaming de audio PCM crudo desde Kokoro-FastAPI (sin cabecera WAV)"""
        url = f"{self.kokoro_url}/v1/audio/speech"
        payload = {
            "model": "kokoro",
            "input": text,
            "voice": self.kokoro_voice,
            "response_format": "pcm",
            "speed": 1.0,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        async for chunk in response.content.iter_chunked(4800):
                            if chunk:
                                yield chunk
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ [Kokoro] Error stream: {response.status} - {error_text[:100]}")
        except Exception as e:
            logger.error(f"❌ [Kokoro] Error en streaming: {e}")

    async def synthesize_stream(self, text: str):
        """Streaming de audio. Kokoro y Gemini usan streaming real, XTTS genera completo."""
        if not text:
            return

        text = preparar_texto_para_tts(text)

        if self.backend == "xtts":
            logger.info(f"🎤 [XTTS] Generando audio (sin streaming): '{text[:30]}...'")
            audio_data = await self._synthesize_xtts(text)
            if audio_data:
                yield audio_data
            return

        if self.backend == "kokoro":
            logger.info(f"🎤 [Kokoro] Streaming: '{text[:30]}...'")
            async for chunk in self._synthesize_kokoro_stream(text):
                yield chunk
            return

        if self.backend == "f5":
            logger.info(f"🎤 [F5] Streaming: '{text[:30]}...'")
            async for chunk in self._synthesize_f5_stream(text):
                yield chunk
            return

        if self.backend == "cosyvoice":
            logger.info(f"🎤 [CosyVoice] Streaming: '{text[:30]}...'")
            async for chunk in self._synthesize_cosyvoice_stream(text):
                yield chunk
            return

        # Gemini: streaming real
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
        if self.backend in ("xtts", "kokoro", "f5", "cosyvoice"):
            return "wav"
        return "mp3"