import asyncio
import logging
import numpy as np
import re
import requests
from app.stt import SpeechToText
from app.llm import LLMClient
from app.tts import TextToSpeech
from app.database import EmployeeRepository

logger = logging.getLogger("Agent")

# Estados de la conversación
STATE_INIT = "INIT"
STATE_WAITING_CONFIRMATION = "WAIT_CONFIRM"
STATE_WELCOMING = "WELCOMING"
STATE_QA = "QA"
STATE_ENDING = "ENDING"

class CallAgent:
    def __init__(self, websocket, employee_phone: str):
        self.ws = websocket
        self.phone = employee_phone
        
        # Servicios
        self.stt = SpeechToText()
        self.llm = LLMClient()
        self.tts = TextToSpeech()
        self.db = EmployeeRepository()
        
        # Datos del empleado
        self.employee = self.db.get_employee_by_phone(self.phone) or {}
        self.nombre_empleado = self.employee.get('nombre', 'colaborador')
        self.puesto = self.employee.get('puesto', 'nuevo ingreso')
        self.fecha_inicio = self.employee.get('fecha_inicio', 'pronto')

        # Estado
        self.state = STATE_INIT
        self.history = []
        self.is_speaking = False
        self.audio_buffer = bytearray()
        
        # VAD (Ajustado para ser menos sensible al ruido)
        self.silence_threshold = 600 
        self.silence_frames = 0
        self.max_silence_frames = 25 # ~1.5s de silencio para procesar

    async def start_conversation(self):
        """Arranca el flujo"""
        logger.info(f"📞 CallAgent iniciado para: {self.nombre_empleado}")
        
        # 1. Saludo Inicial (Inmediato)
        saludo = f"Hola, buenas tardes. Me comunico de Seils Land. ¿Hablo con {self.nombre_empleado}?"
        await self._speak(saludo)
        
        self.state = STATE_WAITING_CONFIRMATION
        self.history.append({"role": "assistant", "content": saludo})

        # 2. Bucle de Escucha
        try:
            while True:
                data = await self.ws.receive_bytes()
                await self._process_audio_stream(data)
        except Exception as e:
            logger.info(f"Fin de conexión: {e}")

    async def _process_audio_stream(self, audio_bytes):
        if self.is_speaking: return

        # VAD Simple
        audio_chunk = np.frombuffer(audio_bytes, dtype=np.int16)
        volume = np.abs(audio_chunk).mean()

        if volume > self.silence_threshold:
            self.silence_frames = 0
            self.audio_buffer.extend(audio_bytes)
        else:
            if len(self.audio_buffer) > 0:
                self.silence_frames += 1
            
            # Procesar si hay suficiente silencio y suficiente audio capturado
            if self.silence_frames > self.max_silence_frames and len(self.audio_buffer) > 16000: # ~1s audio
                await self._turn_processing()
                self.audio_buffer = bytearray()
                self.silence_frames = 0

    async def _turn_processing(self):
        self.is_speaking = True
        
        # 1. Transcribir
        user_text = await self.stt.transcribe(bytes(self.audio_buffer))
        
        # Filtro de texto vacío o muy corto
        if not user_text or len(user_text) < 2:
            self.is_speaking = False
            return

        logger.info(f"👤 Usuario ({self.state}): {user_text}")
        self.history.append({"role": "user", "content": user_text})

        # 2. Máquina de Estados (Lógica de Negocio)
        response_text = ""

        if self.state == STATE_WAITING_CONFIRMATION:
            # Lógica determinista (Regex) - Cero Latencia
            if self._check_affirmation(user_text):
                response_text = f"Perfecto. Te damos la bienvenida a la familia Seils Land. Estamos felices de contar contigo como {self.puesto} a partir del {self.fecha_inicio}. ¿Tienes alguna duda sobre tu ingreso?"
                self.state = STATE_QA # Pasamos a modo IA
            elif self._check_negation(user_text):
                response_text = "Entiendo, disculpa la confusión. Que tengas buen día."
                self.state = STATE_ENDING
            else:
                # No entendimos, preguntamos de nuevo
                response_text = f"Disculpa, ¿podrías confirmarme si eres {self.nombre_empleado}?"

        elif self.state == STATE_QA:
            # Modo IA (Ollama)
            # Detectar despedida antes de llamar al LLM
            if self._check_goodbye(user_text):
                response_text = "Muchas gracias, te esperamos. ¡Hasta pronto!"
                self.state = STATE_ENDING
            else:
                # Aquí sí usamos el LLM potente
                system_prompt = self._get_system_prompt()
                messages = [{"role": "system", "content": system_prompt}] + self.history[-4:] # Solo últimos mensajes
                response_text = await self.llm.generate_response(messages)

        elif self.state == STATE_ENDING:
            return # Ya no procesamos más

        # 3. Hablar
        if response_text:
            self.history.append({"role": "assistant", "content": response_text})
            await self._speak(response_text)

        # 4. Si el estado es ENDING, colgamos
        if self.state == STATE_ENDING:
            logger.info("👋 Finalizando llamada por flujo completado.")
            await asyncio.sleep(1) # Dar tiempo a que termine el audio
            self._hangup_call()

        self.is_speaking = False

    # --- HELPERS DE LÓGICA (REEMPLAZAN AL LLM EN COSAS SIMPLES) ---
    def _check_affirmation(self, text):
        patterns = [r"\bs[íi]\b", r"soy yo", r"correcto", r"así es", r"claro", r"dime", r"habla él", r"habla ella"]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def _check_negation(self, text):
        patterns = [r"\bno\b", r"equivocad", r"error", r"no soy"]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def _check_goodbye(self, text):
        patterns = [r"gracias", r"listo", r"chau", r"adiós", r"hasta luego", r"ninguna"]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def _get_system_prompt(self):
        return f"""Eres asistente de RRHH de Seils Land.
Responde dudas sobre la incorporación de {self.nombre_empleado}.
Horario: L-V 9am-6pm.
Ubicación: Jirón Horacio Cachay Díaz 393, La Victoria.
Sé muy breve y amable."""

    async def _speak(self, text):
        """Genera y envía audio"""
        audio_bytes = await self.tts.synthesize(text)
        if audio_bytes:
            # Conversión MP3 -> PCM 8000Hz
            import subprocess
            process = subprocess.Popen(
                ['ffmpeg', '-i', 'pipe:0', '-f', 's16le', '-ac', '1', '-ar', '8000', 'pipe:1'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            pcm_data, _ = process.communicate(input=audio_bytes)
            
            chunk_size = 1024
            for i in range(0, len(pcm_data), chunk_size):
                try:
                    await self.ws.send_bytes(pcm_data[i:i+chunk_size])
                    await asyncio.sleep(0.005) 
                except:
                    break

    def _hangup_call(self):
        """Ordena colgar al sip-service"""
        try:
            requests.get("http://sip-service:8000/?b", timeout=1)
        except:
            pass