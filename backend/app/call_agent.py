import asyncio
import logging
import requests
import re
from app.tts import TextToSpeech
from app.stt import get_stt
from app.database import EmployeeRepository
from app.states import CallState
from app.prompts import (
    get_saludo, get_presentacion, get_verificacion,
    get_bienvenida, get_despedida_ok, get_despedida_error
)

logger = logging.getLogger("CallAgent")


class CallAgent:
    def __init__(self, websocket, employee_id: int):
        self.ws = websocket
        self.employee_id = employee_id
        self.tts = TextToSpeech()
        self.stt = get_stt()
        self.db = EmployeeRepository()
        
        # Audio config
        self.BYTES_PER_SECOND = 16000
        self.SAMPLE_RATE = 8000
        
        # Estado
        self.state = CallState.DETECTAR_BUZON
        self.duracion_marcado = 0
        
        # Cargar datos del empleado
        self.employee = self.db.get_employee_by_id(self.employee_id)
        self.intentos_confirmacion = 0
        self.MAX_INTENTOS = 3
        
        if self.employee:
            self.nombre = self.employee.get('nombre', 'colaborador')
            self.puesto = self.employee.get('puesto', 'nuevo ingreso')
            self.fecha_inicio = self.employee.get('fecha_inicio', 'pronto')
            logger.info(f"📋 Empleado cargado: {self.nombre} - {self.puesto}")
        else:
            self.nombre = "colaborador"
            self.puesto = "nuevo ingreso"
            self.fecha_inicio = "pronto"
            logger.error(f"❌ Empleado con ID {self.employee_id} no encontrado")

    async def iniciar_conversacion(self):
        """Flujo principal usando máquina de estados"""
        logger.info(f"📞 Iniciando llamada para {self.nombre}")
        await asyncio.sleep(0.5)
        
        while self.state != CallState.FINALIZADO:

            if self.ws.client_state.name != "CONNECTED":
                logger.warning("📴 WebSocket desconectado, finalizando")
                break

            logger.info(f"🔄 Estado: {self.state.value}")
            
            if self.state == CallState.DETECTAR_BUZON:
                await self._estado_detectar_buzon()
            
            elif self.state == CallState.PRESENTACION:
                await self._estado_presentacion()
            
            elif self.state == CallState.ESPERAR_CONFIRMACION:
                await self._estado_esperar_confirmacion()
            
            elif self.state == CallState.BIENVENIDA:
                await self._estado_bienvenida()
            
            elif self.state == CallState.ESPERAR_DUDAS:
                await self._estado_esperar_dudas()
            
            elif self.state == CallState.RESPONDER:
                await self._estado_responder()
            
            elif self.state == CallState.DESPEDIDA_OK:
                await self._estado_despedida_ok()
            
            elif self.state == CallState.DESPEDIDA_ERROR:
                await self._estado_despedida_error()
        
        logger.info("📞 Llamada finalizada")

    # ==================== ESTADOS ====================

    async def _estado_detectar_buzon(self):
        """Detecta si es buzón o humano"""
        es_buzon = await self._detectar_buzon_voz()
        
        if es_buzon:
            logger.warning("🚫 Buzón detectado. Abortando.")
            self._colgar()
            self.state = CallState.FINALIZADO
        else:
            logger.info("✅ Humano detectado")
            self.state = CallState.PRESENTACION

    async def _estado_presentacion(self):
        """Saludo y verificación de identidad"""
        frases = [
            get_saludo(),
            get_presentacion(),
            get_verificacion(self.nombre)
        ]
        
        if not await self._hablar_frases(frases):
            self.state = CallState.FINALIZADO
            return
        
        self.state = CallState.ESPERAR_CONFIRMACION

    async def _estado_esperar_confirmacion(self):
        """Escucha si confirma identidad"""
        respuesta = await self._escuchar_respuesta()
        
        if not respuesta:
            self.intentos_confirmacion += 1
            if self.intentos_confirmacion >= self.MAX_INTENTOS:
                logger.warning("⚠️ Máximo de intentos alcanzado")
                self.state = CallState.DESPEDIDA_ERROR
                return
            await self._hablar_frases(["¿Hola? ¿Me escuchas?"])
            return
        
        if self._es_confirmacion(respuesta):
            logger.info("✅ Identidad confirmada")
            self.state = CallState.BIENVENIDA
        elif self._es_negacion(respuesta):
            logger.info("❌ No es la persona")
            self.state = CallState.DESPEDIDA_ERROR
        else:
            self.intentos_confirmacion += 1
            if self.intentos_confirmacion >= self.MAX_INTENTOS:
                logger.warning("⚠️ No se pudo confirmar identidad")
                self.state = CallState.DESPEDIDA_ERROR
                return
            await self._hablar_frases([f"Disculpa, ¿eres {self.nombre}?"])

    async def _estado_bienvenida(self):
        """Da la bienvenida y pregunta por dudas"""
        frases = get_bienvenida(self.nombre, self.puesto, self.fecha_inicio)
        
        if not await self._hablar_frases(frases):
            self.state = CallState.FINALIZADO
            return
        
        self.state = CallState.ESPERAR_DUDAS

    async def _estado_esperar_dudas(self):
        """Escucha si tiene dudas - loop hasta que diga que no"""
        
        # Verificar conexión
        if self.ws.client_state.name != "CONNECTED":
            logger.warning("📴 Conexión perdida")
            self.state = CallState.FINALIZADO
            return
        
        respuesta = await self._escuchar_respuesta()
        
        if not respuesta:
            if self.ws.client_state.name != "CONNECTED":
                self.state = CallState.FINALIZADO
                return
            await self._hablar_frases(["¿Tienes alguna pregunta sobre tu incorporación?"])
            respuesta = await self._escuchar_respuesta()
        
        if not respuesta:
            self.state = CallState.DESPEDIDA_OK
            return
        
        # PRIMERO verificar si quiere terminar
        if self._es_negacion_simple(respuesta) or self._es_despedida(respuesta):
            logger.info("👋 Usuario sin más dudas")
            self.state = CallState.DESPEDIDA_OK
            return
        
        # Si no es despedida, es una duda
        logger.info(f"❓ Usuario tiene duda: {respuesta}")
        self.duda_actual = respuesta
        self.state = CallState.RESPONDER

    async def _estado_responder(self):
        """Responde y pregunta si hay más dudas"""
        
        if self.ws.client_state.name != "CONNECTED":
            self.state = CallState.FINALIZADO
            return
        
        # TODO: Integrar LLM en siguiente fase
        respuesta = "Por ahora no puedo responder esa pregunta específica. Recibirás toda la información por correo."
        
        if not await self._hablar_frases([respuesta]):
            self.state = CallState.FINALIZADO
            return
        
        if not await self._hablar_frases(["¿Hay algo más en lo que pueda ayudarte?"]):
            self.state = CallState.FINALIZADO
            return
        
        self.state = CallState.ESPERAR_DUDAS

    async def _estado_despedida_ok(self):
        """Despedida exitosa"""
        await self._hablar_frases([get_despedida_ok()])
        await asyncio.sleep(0.5)
        self._colgar()
        self.state = CallState.FINALIZADO

    async def _estado_despedida_error(self):
        """Despedida por error/no es la persona"""
        await self._hablar_frases([get_despedida_error()])
        await asyncio.sleep(0.5)
        self._colgar()
        self.state = CallState.FINALIZADO

    # ==================== HELPERS ====================

    async def _detectar_buzon_voz(self):
        """Captura audio inicial y detecta si es buzón"""
        logger.info("🔍 Verificando si es buzón de voz...")
        
        buffer = bytearray()
        tiempo_inicio = asyncio.get_event_loop().time()
        tiempo_limite = 3.0
        
        while (asyncio.get_event_loop().time() - tiempo_inicio) < tiempo_limite:
            try:
                data = await asyncio.wait_for(self.ws.receive_bytes(), timeout=0.1)
                buffer.extend(data)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"❌ Error capturando audio: {e}")
                break
        
        if len(buffer) < 8000:
            logger.warning("⚠️ Audio insuficiente")
            return True
        
        texto = await self.stt.transcribe(bytes(buffer))
        
        if not texto or len(texto.strip()) < 2:
            logger.warning("⚠️ No se detectó voz clara")
            return True
        
        logger.info(f"📝 Transcripción inicial: '{texto}'")
        
        keywords_buzon = [
            "buzón", "buzon", "busón", "buson",
            "mensaje", "mensajes",
            "tono", "señal", "senal",
            "deje su", "deja tu", "deje un",
            "después del", "despues del",
            "grabar", "grabación", "grabacion",
            "depositar", "lleno",
            "no está disponible", "no esta disponible",
            "fuera de servicio",
            "mailbox", "voicemail", "voice mail",
            "leave a message", "leave message",
            "after the beep", "beep", "tone", "record",
            "not available", "unavailable"
        ]
        
        texto_lower = texto.lower()
        for keyword in keywords_buzon:
            if keyword in texto_lower:
                logger.warning(f"🚫 BUZÓN: Palabra '{keyword}' detectada")
                return True
        
        logger.info("✅ Respuesta humana confirmada")
        return False

    async def _escuchar_respuesta(self, timeout: float = 6.0):
        """Escucha respuesta del usuario con mejor timing"""
        import numpy as np
        
        # Pequeño delay para que el usuario procese lo que escuchó
        await asyncio.sleep(0.5)
        
        buffer = bytearray()
        silencio_consecutivo = 0
        max_silencio = 20  # ~2 segundos de silencio para considerar fin de frase
        frames_con_voz = 0
        tiempo_inicio = asyncio.get_event_loop().time()
        
        logger.info("👂 Escuchando respuesta...")
        
        while (asyncio.get_event_loop().time() - tiempo_inicio) < timeout:
            try:
                # Verificar conexión
                if self.ws.client_state.name != "CONNECTED":
                    logger.warning("📴 WebSocket desconectado durante escucha")
                    return None
                
                data = await asyncio.wait_for(self.ws.receive_bytes(), timeout=0.1)
                buffer.extend(data)
                
                # VAD simple
                chunk = np.frombuffer(data, dtype=np.int16)
                volumen = np.abs(chunk).mean()
                
                if volumen > 100:  # Detectamos voz
                    silencio_consecutivo = 0
                    frames_con_voz += 1
                else:
                    silencio_consecutivo += 1
                
                # Si detectamos voz Y luego silencio prolongado, procesar
                if frames_con_voz > 5 and silencio_consecutivo > max_silencio:
                    logger.info(f"🎤 Fin de frase detectado (voz: {frames_con_voz} frames)")
                    break
                    
            except asyncio.TimeoutError:
                silencio_consecutivo += 1
                if frames_con_voz > 5 and silencio_consecutivo > max_silencio:
                    break
            except Exception as e:
                logger.error(f"❌ Error escuchando: {e}")
                return None
        
        # Verificar que capturamos suficiente audio con voz
        if len(buffer) < 4000 or frames_con_voz < 3:
            logger.warning(f"⚠️ Audio insuficiente (buffer: {len(buffer)}, voz: {frames_con_voz} frames)")
            return None
        
        texto = await self.stt.transcribe(bytes(buffer))
        if texto:
            logger.info(f"👤 Usuario: '{texto}'")
        return texto

    async def _hablar_frases(self, frases: list) -> bool:
        """Genera y reproduce frases en paralelo"""
        logger.info(f"🎨 Generando {len(frases)} audios...")
        
        tareas = [self._generar_audio(f) for f in frases]
        resultados = await asyncio.gather(*tareas)
        audios = [r for r in resultados if r is not None]
        
        for pcm_data, duracion in audios:
            if not await self._reproducir(pcm_data, duracion):
                return False
        
        return True

    async def _generar_audio(self, texto):
        """Genera audio TTS"""
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

    async def _reproducir(self, pcm_data, duracion) -> bool:
        """Transmite audio por WebSocket"""
        chunk_size = 1024
        for i in range(0, len(pcm_data), chunk_size):
            try:
                if self.ws.client_state.name != "CONNECTED":
                    logger.warning("⚠️ WebSocket cerrado")
                    return False
                
                await self.ws.send_bytes(pcm_data[i:i+chunk_size])
                await asyncio.sleep(0.002)
            except Exception:
                logger.warning("⚠️ Conexión perdida durante reproducción")
                return False
        
        await asyncio.sleep(duracion)
        return True

    def _mp3_to_pcm(self, audio_bytes):
        """Convierte MP3 a PCM"""
        import subprocess
        process = subprocess.Popen(
            ['ffmpeg', '-i', 'pipe:0', '-f', 's16le', '-ac', '1', '-ar', '8000', 'pipe:1'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        pcm_data, _ = process.communicate(input=audio_bytes)
        return pcm_data

    def _es_confirmacion(self, texto: str) -> bool:
        """Detecta si el usuario confirma"""
        patterns = [
            r"\bs[íi]\b", r"soy yo", r"correcto", r"así es", r"aja",
            r"claro", r"dime", r"el mismo", r"la misma", r"con [eé]l",
            r"con ella", r"s[íi] soy", r"afirmativo"
        ]
        texto_lower = texto.lower()
        return any(re.search(p, texto_lower) for p in patterns)

    def _es_negacion(self, texto: str) -> bool:
        """Detecta si el usuario niega"""
        patterns = [
            r"\bno\b", r"equivocad", r"error", r"no soy",
            r"otro número", r"número equivocado"
        ]
        texto_lower = texto.lower()
        return any(re.search(p, texto_lower) for p in patterns)


    def _es_negacion_simple(self, texto: str) -> bool:
        """Detecta negación como respuesta a '¿alguna duda?'"""
        texto_lower = texto.lower().strip()
        
        indicadores_no = [
            "no,", "no.", "que no", "nada", "ninguna", 
            "no tengo", "no gracias", "no, gracias",
            "de momento no", "por ahora no", "todo bien",
            "todo claro", "estoy bien", "está bien"
        ]
        
        return any(ind in texto_lower for ind in indicadores_no)


    def _es_despedida(self, texto: str) -> bool:
        """Detecta si el usuario quiere terminar"""
        texto_lower = texto.lower()
        
        # Si menciona querer saber/preguntar = NO es despedida
        if any(p in texto_lower for p in ["quisiera saber", "me gustaría", "puedes decirme", "cuál es"]):
            return False
        
        # Contiene "gracias" + alguna forma de negación/cierre
        if "gracias" in texto_lower:
            if any(p in texto_lower for p in ["no", "nada", "eso es todo", "momento"]):
                return True
        
        # Despedidas directas
        despedidas = ["chau", "adiós", "adios", "hasta luego", "bye", "nos vemos"]
        if any(d in texto_lower for d in despedidas):
            return True
        
        return False
    

    def _colgar(self):
        """Ordena colgar al sip-service"""
        try:
            requests.get("http://sip-service:8000/?b", timeout=0.5)
            logger.info("📞 Llamada finalizada")
        except requests.exceptions.Timeout:
            logger.info("📞 Llamada ya finalizada")
        except Exception as e:
            logger.warning(f"⚠️ Colgar: {e}")