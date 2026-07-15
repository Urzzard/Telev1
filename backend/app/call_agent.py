import asyncio
import logging
import requests
import re
import aiohttp
from app.tts import TextToSpeech
from app.stt import get_stt
from app.states import CallState
from app.llm import get_llm
from app.intent_detector import IntentDetector
from app.prompts import (
    get_saludo, get_presentacion, get_verificacion,
    get_bienvenida, get_despedida_ok, get_despedida_error,
    get_despedida_sin_respuesta, get_reidentificacion,
    get_system_prompt_llm, get_pregunta_mas_dudas
)
from app.postgres_db import get_postgres_db
from app.vad import VoiceActivityDetector
import numpy as np
import time
from scipy import signal

logger = logging.getLogger("CallAgent")


class CallAgent:
    def __init__(self, websocket, employee_id: int):
        self.ws = websocket
        self.employee_id = employee_id
        self.tts = TextToSpeech()
        self.stt = get_stt()
        self.llm = get_llm()
        self.intent_detector = IntentDetector()
        
        # Audio config
        self.BYTES_PER_SECOND = 16000
        self.SAMPLE_RATE = 8000
        
        # Estado
        self.state = CallState.DETECTAR_BUZON
        self.duracion_marcado = 0
        
        # Memoria conversacional del LLM
        self.historial_llm = []
        self.resumen_conversacion = ""
        self.turnos_desde_ultimo_resumen = 0
        
        # Cargar datos del empleado desde PostgreSQL
        self._cargar_empleado_postgres()
        
        self.intentos_confirmacion = 0
        self.llamada_id = None
        self.MAX_INTENTOS = 3
        self.resultado_final = None
        self.resultado_registrado = False
        self.turno_conversacion = 0

        self.vad = VoiceActivityDetector(sample_rate=8000)

        self.barge_in_detected = False
        self.barge_in_audio = bytearray()

        # NUEVO: Pre-generación de saludo en paralelo
        self.audio_saludo_pregenerado = None
        self.tarea_pregenerar_saludo = None

        # Pre-generación de bienvenida en paralelo
        self.audio_bienvenida_pregenerado = None
        self.tarea_pregenerar_bienvenida = None

    def _cargar_empleado_postgres(self):
        """Carga datos del empleado desde PostgreSQL"""
        try:
            pg = get_postgres_db()
            if pg.connect():
                with pg.get_cursor() as cur:
                    cur.execute("""
                        SELECT nombre, puesto, fecha_ingreso, celular
                        FROM empleados WHERE id = %s
                    """, (self.employee_id,))
                    row = cur.fetchone()
                    
                    if row:
                        self.nombre = row["nombre"] or "colaborador"
                        self.puesto = row["puesto"] or "nuevo ingreso"
                        self.fecha_inicio = self._formatear_fecha(row["fecha_ingreso"])
                        logger.info(f"📋 Empleado cargado: {self.nombre} - {self.puesto}")
                    else:
                        self._set_datos_default()
                        logger.error(f"❌ Empleado {self.employee_id} no encontrado en PostgreSQL")
                pg.disconnect()
            else:
                self._set_datos_default()
        except Exception as e:
            logger.error(f"❌ Error cargando empleado: {e}")
            self._set_datos_default()

    async def _pregenerar_saludo(self):
        """Genera el audio del saludo en paralelo mientras detectamos buzón"""
        try:
            from app.prompts import get_saludo, get_presentacion, get_verificacion
            
            frases = [
                get_saludo(),
                get_presentacion(), 
                get_verificacion(self.nombre)
            ]
            texto_saludo = " ".join(frases)
            
            # Generar audio (esto toma ~1s)
            audio_data = await self.tts.synthesize(texto_saludo)
            
            if audio_data:
                logger.info(f"✅ [PRE-GEN] Saludo pre-generado ({len(audio_data)} bytes)")
                self.audio_saludo_pregenerado = audio_data
            else:
                logger.warning("⚠️ [PRE-GEN] No se pudo pre-generar saludo")
                
        except Exception as e:
            logger.warning(f"⚠️ [PRE-GEN] Error: {e}")


    async def _pregenerar_bienvenida(self):
        """Genera el audio de bienvenida en paralelo mientras esperamos confirmación"""
        try:
            frases = get_bienvenida(self.nombre, self.puesto, self.fecha_inicio)
            texto_bienvenida = " ".join(frases)
            
            audio_data = await self.tts.synthesize(texto_bienvenida)
            
            if audio_data:
                logger.info(f"✅ [PRE-GEN] Bienvenida pre-generada ({len(audio_data)} bytes)")
                self.audio_bienvenida_pregenerado = audio_data
            else:
                logger.warning("⚠️ [PRE-GEN] No se pudo pre-generar bienvenida")
                
        except Exception as e:
            logger.warning(f"⚠️ [PRE-GEN] Error bienvenida: {e}")


    def _set_datos_default(self):
        """Valores por defecto si no se encuentra empleado"""
        self.nombre = "colaborador"
        self.puesto = "nuevo ingreso"
        self.fecha_inicio = "pronto"

    
    def _formatear_fecha(self, fecha_str: str) -> str:
        """Convierte '2025-12-02' a '2 de diciembre del 2025' para TTS natural"""
        try:
            from datetime import datetime
            
            meses = [
                "enero", "febrero", "marzo", "abril", "mayo", "junio",
                "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
            ]
            
            if fecha_str and "-" in str(fecha_str):
                fecha = datetime.strptime(str(fecha_str), "%Y-%m-%d")
                dia = fecha.day  # Sin cero inicial
                mes = meses[fecha.month - 1]
                año = fecha.year
                return f"{dia} de {mes} del {año}"
            
            # Si ya viene en formato dd/mm/yyyy, también convertir
            if fecha_str and "/" in str(fecha_str):
                partes = str(fecha_str).split("/")
                if len(partes) == 3:
                    dia = int(partes[0])
                    mes_num = int(partes[1])
                    año = partes[2]
                    mes = meses[mes_num - 1]
                    return f"{dia} de {mes} del {año}"
            
            return str(fecha_str) if fecha_str else "pronto"
        except:
            return str(fecha_str) if fecha_str else "pronto"

    def _obtener_llamada_activa(self) -> int:
        """Obtiene el ID de la llamada activa para este empleado"""
        try:
            pg = get_postgres_db()
            if pg.connect():
                with pg.get_cursor() as cur:
                    cur.execute("""
                        SELECT id FROM llamadas 
                        WHERE empleado_id = %s AND resultado = 'en_curso'
                        ORDER BY iniciada_en DESC LIMIT 1
                    """, (self.employee_id,))
                    row = cur.fetchone()
                    if row:
                        return row["id"]
                pg.disconnect()
        except Exception as e:
            logger.warning(f"⚠️ Error obteniendo llamada_id: {e}")
        return None


    async def iniciar_conversacion(self):
        """Flujo principal usando máquina de estados"""
        logger.info(f"📞 Iniciando llamada para {self.nombre}")
        await self.llm.keepalive()
        await asyncio.sleep(0.5)

        self.llamada_id = self._obtener_llamada_activa()
        logger.info(f"📞 Llamada ID: {self.llamada_id}")
        
        llamada_completada = False
        
        try:
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
                    llamada_completada = True
                
                elif self.state == CallState.DESPEDIDA_ERROR:
                    await self._estado_despedida_error()
                    llamada_completada = True
        
        except Exception as e:
            logger.error(f"❌ Error en conversación: {e}")
        
        finally:
            # Si la llamada no se completó normalmente, marcar como fallido
            if not llamada_completada:
                logger.warning("⚠️ Llamada terminó sin completar flujo normal")
                self._actualizar_resultado_postgres("FALLIDO")
        
        logger.info("📞 Llamada finalizada")
        

    # ==================== ESTADOS ====================

    async def _estado_detectar_buzon(self):
        """Detecta si es buzón o humano - CON PRE-GENERACIÓN EN PARALELO"""
        
        # NUEVO: Iniciar pre-generación del saludo en paralelo
        self.tarea_pregenerar_saludo = asyncio.create_task(self._pregenerar_saludo())
        
        es_buzon = await self._detectar_buzon_voz()
        
        if es_buzon:
            logger.warning("🚫 Buzón detectado. Abortando.")
            # Cancelar pre-generación si estaba corriendo
            if self.tarea_pregenerar_saludo:
                self.tarea_pregenerar_saludo.cancel()
            self._actualizar_resultado_postgres("FALLIDO")
            self._colgar()
            self.state = CallState.FINALIZADO
        else:
            logger.info("✅ Humano detectado")
            self.state = CallState.PRESENTACION

    async def _estado_presentacion(self):
        """Saludo y verificación de identidad - USA AUDIO PRE-GENERADO SI EXISTE"""
        
        # Esperar a que termine la pre-generación (si aún está corriendo)
        if self.tarea_pregenerar_saludo:
            try:
                await asyncio.wait_for(self.tarea_pregenerar_saludo, timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("⚠️ [PRE-GEN] Timeout esperando audio")
            except Exception as e:
                logger.warning(f"⚠️ [PRE-GEN] Error: {e}")
        
        # Usar audio pre-generado si existe
        if self.audio_saludo_pregenerado:
            logger.info("🚀 [PRE-GEN] Usando saludo pre-generado (latencia reducida)")
            if not await self._reproducir_audio_pregenerado(self.audio_saludo_pregenerado):
                self.state = CallState.FINALIZADO
                return
        else:
            # Fallback: generar normalmente
            logger.info("⚠️ [PRE-GEN] Sin audio pre-generado, generando ahora...")
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
        """Escucha si confirma identidad — TURN-HANDLER (clasificar_turno, estado=IDENTIDAD)."""

        # Iniciar pre-generación de bienvenida en paralelo (si no existe ya)
        if self.tarea_pregenerar_bienvenida is None and self.audio_bienvenida_pregenerado is None:
            self.tarea_pregenerar_bienvenida = asyncio.create_task(self._pregenerar_bienvenida())
        respuesta = await self._escuchar_respuesta()

        if not respuesta:
            self.intentos_confirmacion += 1
            if self.intentos_confirmacion >= self.MAX_INTENTOS:
                logger.warning("⚠️ Máximo de intentos alcanzado")
                self.state = CallState.DESPEDIDA_ERROR
                return
            await self._hablar_frases(["¿Hola? ¿Me escuchas?"])
            return

        # Paso 1: clasificar la intención con el LLM (reemplaza _es_confirmacion / _es_negacion / incoherente)
        intent = await self.llm.clasificar_turno("IDENTIDAD", respuesta, self.nombre)
        logger.info(f"🧭 [CONFIRMACION] intent={intent}  ('{respuesta[:40]}')")

        if intent == "CONFIRMA":
            logger.info("✅ Identidad confirmada")
            self.state = CallState.BIENVENIDA

        elif intent == "NIEGA":
            logger.info("❌ No es la persona")
            self.state = CallState.DESPEDIDA_ERROR

        elif intent == "PREGUNTA_QUIEN_LLAMA":
            logger.info("🙋 Pregunta quién llama → re-identificar (no cuenta como intento fallido)")
            await self._hablar_frases([get_reidentificacion(self.nombre)])

        elif intent == "CALIBRACION":
            logger.info("🔊 Calibración → tranquilizar y re-preguntar")
            await self._hablar_frases([f"Sí, te escucho. ¿Hablo con {self.nombre}?"])

        else:  # OTRO, o None (fallback del clasificador)
            self.intentos_confirmacion += 1
            if self.intentos_confirmacion >= self.MAX_INTENTOS:
                logger.warning("⚠️ No se pudo confirmar identidad")
                self.state = CallState.DESPEDIDA_ERROR
                return
            await self._hablar_frases([f"Disculpa, ¿eres {self.nombre}?"])

    async def _estado_bienvenida(self):
        """Da la bienvenida - USA AUDIO PRE-GENERADO SI EXISTE"""
        
        # Esperar a que termine la pre-generación (si aún está corriendo)
        if self.tarea_pregenerar_bienvenida:
            try:
                await asyncio.wait_for(self.tarea_pregenerar_bienvenida, timeout=3.0)
            except asyncio.TimeoutError:
                logger.warning("⚠️ [PRE-GEN] Timeout esperando bienvenida")
            except Exception as e:
                logger.warning(f"⚠️ [PRE-GEN] Error: {e}")
        
        # Usar audio pre-generado si existe
        if self.audio_bienvenida_pregenerado:
            logger.info("🚀 [PRE-GEN] Usando bienvenida pre-generada (latencia reducida)")
            if not await self._reproducir_audio_pregenerado(self.audio_bienvenida_pregenerado):
                self.state = CallState.FINALIZADO
                return
        else:
            # Fallback: generar normalmente
            logger.info("⚠️ [PRE-GEN] Sin bienvenida pre-generada, generando ahora...")
            frases = get_bienvenida(self.nombre, self.puesto, self.fecha_inicio)
            texto_completo = " ".join(frases)
            
            if not await self._hablar_con_streaming_real(texto_completo):
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
            await self._despedir_sin_respuesta()
            return
        
        # NUEVO: Verificar si es backchannel/confirmación PRIMERO
        if self._es_confirmacion_o_backchannel(respuesta):
            logger.info("✅ Usuario confirmó, preguntando si hay más dudas")
            await self._hablar_frases([get_pregunta_mas_dudas()])
            respuesta = await self._escuchar_respuesta()
            
            if not respuesta:
                await self._despedir_sin_respuesta()
                return

        # NUEVO: Verificar si es pregunta fuera de tema (no relacionada con onboarding)
        if self.intent_detector.es_pregunta_fuera_de_tema(respuesta):
            logger.info(f"🚫 Pregunta fuera de tema: '{respuesta}'")
            await self._hablar_frases(["Disculpa, solo puedo ayudarte con temas de tu incorporación a la empresa. ¿Tienes alguna duda sobre tu primer día, horario, ubicación o demás?"])
            return  # Vuelve a esperar_dudas


        # NUEVO: Verificar si es respuesta incoherente (mala transcripción)
        if self.intent_detector.es_respuesta_incoherente(respuesta):
            logger.warning(f"⚠️ Respuesta incoherente detectada: '{respuesta}'")
            await self._hablar_frases(["Disculpa, no te escuché bien. ¿Me lo puedes repetir?"])
            return  # Vuelve a esperar_dudas
        
        # LUEGO verificar si quiere terminar (despedida explícita)
        if self._es_despedida_explicita(respuesta):
            logger.info("👋 Usuario se despide explícitamente")
            self.state = CallState.DESPEDIDA_OK
            return
        
        # Si no es despedida, es una duda
        logger.info(f"❓ Usuario tiene duda: {respuesta}")
        self.duda_actual = respuesta

        # Registrar para fine-tuning
        self._registrar_turno("usuario", respuesta, confianza=self.vad.max_confidence)
        self.state = CallState.RESPONDER

    async def _estado_responder(self):
        """Responde usando LLM - valida tema antes de responder"""
        
        
        if self.ws.client_state.name != "CONNECTED":
            self.state = CallState.FINALIZADO
            return
        
        TIEMPO_INICIO = time.time()
        
        # 1. Validar si es tema permitido
        es_permitido = self.intent_detector.es_tema_permitido(self.duda_actual)
        categoria = self.intent_detector.detectar_categoria(self.duda_actual)
        
        logger.info(f"📋 Categoría: {categoria} | Permitido: {es_permitido}")
        
        # 2. Registrar pregunta
        self.intent_detector.registrar_pregunta(self.duda_actual)

        # 3. Generar respuesta con LLM
        t_llm_inicio = time.time()
        try:
            system_prompt = get_system_prompt_llm(self.nombre, self.puesto, self.fecha_inicio)
            
            if self.resumen_conversacion:
                system_prompt += f"\n\nTEMAS YA CUBIERTOS EN ESTA LLAMADA:\n{self.resumen_conversacion}"

            pregunta_actual = {"role": "user", "content": self.duda_actual}

            # Actualizar resumen si acumulamos 3 turnos nuevos
            await self._actualizar_resumen()
            self.historial_llm.append(pregunta_actual)
            
            messages = [{"role": "system", "content": system_prompt}] + self.historial_llm[-4:]
            
            respuesta = await self.llm.generate_response(messages)
            
            if not respuesta or len(respuesta) < 5:
                respuesta = "Disculpa, no entendí tu pregunta. ¿Podrías repetirla?"
            
            self.historial_llm.append({
                "role": "assistant",
                "content": respuesta
            })
            
            # Registrar para fine-tuning
            self._registrar_turno("asistente", respuesta, categoria=categoria)


        except Exception as e:
            logger.error(f"❌ Error LLM: {e}")
            respuesta = "Disculpa, tuve un problema técnico. ¿Podrías repetir tu pregunta?"
        
        t_llm_fin = time.time()
        logger.info(f"⏱️ [TIEMPO] LLM: {(t_llm_fin - t_llm_inicio)*1000:.0f}ms")
        
        # 5. Reproducir respuesta
        t_tts_inicio = time.time()
        if not await self._hablar_con_streaming_real(respuesta):
            self.state = CallState.FINALIZADO
            return
        t_tts_fin = time.time()
        logger.info(f"⏱️ [TIEMPO] TTS+Reproducción: {(t_tts_fin - t_tts_inicio)*1000:.0f}ms")
        

        # 6. Ya no preguntamos automáticamente - el LLM decide si incluir pregunta
        if self.barge_in_detected:
            logger.info("⏩ [FLUJO] Barge-in detectado, continuando...")
        
        TIEMPO_TOTAL = time.time() - TIEMPO_INICIO
        logger.info(f"⏱️ [TIEMPO] TOTAL estado_responder: {TIEMPO_TOTAL*1000:.0f}ms")
        
        self.state = CallState.ESPERAR_DUDAS

    async def _estado_despedida_ok(self):
        """Despedida exitosa"""
        # Desactivar barge-in para la despedida final
        await self._hablar_sin_barge_in(get_despedida_ok())
        await asyncio.sleep(0.5)
        self._actualizar_resultado_postgres("EXITO")
        self._colgar()
        self.state = CallState.FINALIZADO

    async def _despedir_sin_respuesta(self):
        """Despedida cuando no hubo respuesta válida del usuario (audio bajo, colgó, etc.)"""
        logger.warning("👋 Sin respuesta válida, marcando como FALLIDO para reintento")
        await self._hablar_sin_barge_in(get_despedida_sin_respuesta())
        await asyncio.sleep(0.5)
        self._actualizar_resultado_postgres("FALLIDO")
        self._colgar()
        self.state = CallState.FINALIZADO

    async def _estado_despedida_error(self):
        """Despedida por error/no es la persona"""
        await self._hablar_frases([get_despedida_error()])
        await asyncio.sleep(0.5)

        self._actualizar_resultado_postgres("FALLIDO")
        self._colgar()
        self.state = CallState.FINALIZADO

    # ==================== HELPERS ====================

    async def _detectar_buzon_voz(self):
        """Captura audio inicial y detecta si es buzón"""
        logger.info("🔍 Verificando si es buzón de voz...")
        
        # Parámetros de endpoint-por-silencio (ver docs/PLAN_TURNTAKING_NATURALIDAD.md §1)
        CEILING = 3.0          # techo duro: el buzón continuo llega hasta aquí
        PISO_MIN = 1.0         # no permitir corte antes de 1s (evita cortar la 1ª sílaba)
        SILENCIO_CORTE = 0.7   # silencio continuo tras hablar = fin de turno (humano esperando)

        self.vad.reset()

        buffer = bytearray()
        tiempo_inicio = asyncio.get_event_loop().time()
        t_ultima_voz = None
        corte_por_silencio = False
        
        while (asyncio.get_event_loop().time() - tiempo_inicio) < CEILING:
            try:
                data = await asyncio.wait_for(self.ws.receive_bytes(), timeout=0.1)
                buffer.extend(data)

                resultado = self.vad.process_chunk(data)
                ahora = asyncio.get_event_loop().time()

                if resultado["is_speech"]:
                    t_ultima_voz = ahora

                # Endpoint: hubo voz y luego silencio continuo suficiente, pasado el piso mínimo.
                # El buzón habla continuo → no acumula silencio → corre hasta el techo.
                if self.vad.speech_started and t_ultima_voz is not None:
                    silencio = ahora - t_ultima_voz
                    transcurrido = ahora - tiempo_inicio
                    if silencio >= SILENCIO_CORTE and transcurrido >= PISO_MIN:
                        corte_por_silencio = True
                        logger.info(
                            f"⚡ [BUZÓN] Fin de turno detectado "
                            f"({transcurrido*1000:.0f}ms, silencio {silencio*1000:.0f}ms)"
                        )
                        break
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"❌ Error capturando audio: {e}")
                break

        if not corte_por_silencio:
            logger.info("⏳ [BUZÓN] Sin fin de turno claro; capturado hasta el techo (3s)")
        
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
            "not available", "unavailable", "disón"
        ]
        
        texto_lower = texto.lower()
        for keyword in keywords_buzon:
            if keyword in texto_lower:
                logger.warning(f"🚫 BUZÓN: Palabra '{keyword}' detectada")
                return True
        
        logger.info("✅ Respuesta humana confirmada")
        return False
        

    async def _escuchar_respuesta(self, timeout: float = 6.0):
        """Escucha respuesta del usuario usando Silero VAD - CON MEDICIÓN QUIRÚRGICA"""
        
        # ========== MEDICIÓN QUIRÚRGICA ==========
        T_INICIO_METODO = time.time()
        T_PRIMERA_VOZ = None          # Cuando detecta voz por primera vez
        T_ULTIMA_VOZ = None           # Último frame con voz
        T_FIN_ESCUCHA = None          # Cuando decide cortar
        frames_voz_total = 0          # Frames con voz detectada
        frames_silencio_final = 0     # Frames de silencio antes de cortar
        picos_voz = []                # Lista de (timestamp, confianza) para análisis
        # =========================================
        
        # Usar audio pre-capturado del barge-in si existe
        if self.barge_in_detected and len(self.barge_in_audio) > 800:  # >50ms de audio
            buffer = bytearray(self.barge_in_audio)
            logger.info(f"🔄 [VAD] Usando {len(buffer)} bytes pre-capturados del barge-in")
            
            # Pequeña pausa para dejar que el TTS termine de sonar en el canal
            await asyncio.sleep(0.1)
        else:
            buffer = bytearray()
            if self.barge_in_detected:
                logger.info(f"⚠️ [VAD] Audio barge-in muy corto ({len(self.barge_in_audio)} bytes), descartando")

        # Reset estado barge-in
        self.barge_in_audio = bytearray()
        self.barge_in_detected = False

        self.vad.reset()

        tiempo_inicio = asyncio.get_event_loop().time()
        T_INICIO_LOOP = time.time()
        
        logger.info("👂 [VAD] Escuchando respuesta (Silero VAD)...")
        
        while (asyncio.get_event_loop().time() - tiempo_inicio) < timeout:
            try:
                if self.ws.client_state.name != "CONNECTED":
                    logger.warning("📴 WebSocket desconectado")
                    return None
                
                data = await asyncio.wait_for(self.ws.receive_bytes(), timeout=0.1)
                buffer.extend(data)
                
                # Usar Silero VAD
                resultado = self.vad.process_chunk(data)
                
                # ========== MEDICIÓN: Detectar eventos de voz ==========
                if resultado["is_speech"]:
                    T_ULTIMA_VOZ = time.time()
                    frames_voz_total += 1
                    
                    # Registrar primera detección de voz
                    if T_PRIMERA_VOZ is None:
                        T_PRIMERA_VOZ = time.time()
                        tiempo_hasta_voz = (T_PRIMERA_VOZ - T_INICIO_LOOP) * 1000
                        logger.info(f"🎤 [VAD] ¡VOZ DETECTADA! Latencia hasta voz: {tiempo_hasta_voz:.0f}ms (conf: {resultado['confidence']:.2f})")
                    
                    # Registrar picos de confianza alta
                    if resultado["confidence"] > 0.6:
                        picos_voz.append((time.time() - T_INICIO_LOOP, resultado["confidence"]))
                # ========================================================
                
                # ========== CAMBIO 3: EARLY CUT INTELIGENTE ==========
                # Si ya hay suficiente voz y silencio moderado, cortar antes del timeout
                if (self.vad.speech_started and 
                    frames_voz_total >= 15 and      # ~1.6s de voz detectada
                    self.vad.silence_frames >= 5 and  # ~400ms de silencio
                    len(buffer) > 16000):            # >2s de audio total
                    
                    T_FIN_ESCUCHA = time.time()
                    frames_silencio_final = self.vad.silence_frames
                    
                    duracion_total = (T_FIN_ESCUCHA - T_INICIO_LOOP) * 1000
                    logger.info(f"⚡ [VAD] EARLY CUT - Suficiente audio capturado")
                    logger.info(f"⏱️ [VAD] Duración: {duracion_total:.0f}ms | Voz: {frames_voz_total} frames | Silencio: {self.vad.silence_frames} frames")
                    break
                # =====================================================
                
                if resultado["speech_ended"] and len(buffer) > 4000:
                    T_FIN_ESCUCHA = time.time()
                    frames_silencio_final = self.vad.silence_frames
                    
                    # ========== LOG DETALLADO DE FIN ==========
                    duracion_total = (T_FIN_ESCUCHA - T_INICIO_LOOP) * 1000
                    duracion_voz = (T_ULTIMA_VOZ - T_PRIMERA_VOZ) * 1000 if T_PRIMERA_VOZ and T_ULTIMA_VOZ else 0
                    tiempo_silencio = (T_FIN_ESCUCHA - T_ULTIMA_VOZ) * 1000 if T_ULTIMA_VOZ else 0
                    
                    logger.info(f"🛑 [VAD] === FIN DE ESCUCHA ===")
                    logger.info(f"⏱️ [VAD] Duración TOTAL loop: {duracion_total:.0f}ms")
                    logger.info(f"⏱️ [VAD] Duración de VOZ: {duracion_voz:.0f}ms ({frames_voz_total} frames)")
                    logger.info(f"⏱️ [VAD] Silencio antes de cortar: {tiempo_silencio:.0f}ms ({frames_silencio_final} frames)")
                    logger.info(f"⏱️ [VAD] Confianza máx: {resultado.get('max_confidence', 0):.2f}")
                    # ==========================================
                    break
                    
            except asyncio.TimeoutError:
                # Verificar si ya terminó de hablar
                if self.vad.speech_started and self.vad.silence_frames >= 10:
                    T_FIN_ESCUCHA = time.time()
                    frames_silencio_final = self.vad.silence_frames
                    
                    duracion_total = (T_FIN_ESCUCHA - T_INICIO_LOOP) * 1000
                    tiempo_silencio = (T_FIN_ESCUCHA - T_ULTIMA_VOZ) * 1000 if T_ULTIMA_VOZ else 0
                    logger.info(f"🛑 [VAD] Corte por timeout interno")
                    logger.info(f"⏱️ [VAD] Duración TOTAL: {duracion_total:.0f}ms | Silencio final: {tiempo_silencio:.0f}ms")
                    break
            except Exception as e:
                logger.error(f"❌ Error escuchando: {e}")
                return None
        
        # ========== ANÁLISIS DE PAUSAS ==========
        if len(picos_voz) >= 2:
            # Detectar pausas entre picos de voz
            pausas = []
            for i in range(1, len(picos_voz)):
                pausa = (picos_voz[i][0] - picos_voz[i-1][0]) * 1000
                if pausa > 200:  # Pausas > 200ms son significativas
                    pausas.append(pausa)
            
            if pausas:
                logger.info(f"📊 [VAD] Pausas detectadas durante habla: {[f'{p:.0f}ms' for p in pausas]}")
        # ========================================
        
        if len(buffer) < 4000 or not self.vad.speech_started:
            T_FIN = time.time()
            logger.warning(f"⚠️ [VAD] Audio insuficiente ({len(buffer)} bytes) | Tiempo total: {(T_FIN - T_INICIO_METODO)*1000:.0f}ms")
            return None

        t_stt_inicio = time.time()
        texto = await self.stt.transcribe(bytes(buffer))
        t_stt_fin = time.time()
        
        # ========== RESUMEN FINAL ==========
        T_FIN_TOTAL = time.time()
        logger.info(f"⏱️ [TIEMPO] === RESUMEN ESCUCHA ===")
        logger.info(f"⏱️ [TIEMPO] 1. Loop VAD: {(T_FIN_ESCUCHA - T_INICIO_LOOP)*1000:.0f}ms" if T_FIN_ESCUCHA else "⏱️ [TIEMPO] 1. Loop VAD: timeout")
        logger.info(f"⏱️ [TIEMPO] 2. Whisper STT: {(t_stt_fin - t_stt_inicio)*1000:.0f}ms")
        logger.info(f"⏱️ [TIEMPO] TOTAL _escuchar_respuesta: {(T_FIN_TOTAL - T_INICIO_METODO)*1000:.0f}ms")
        logger.info(f"⏱️ [TIEMPO] Audio capturado: {len(buffer)} bytes ({len(buffer)/16000:.2f}s de audio)")
        # ===================================

        if texto:
            logger.info(f"👤 Usuario: '{texto}'")
        return texto

    async def _hablar_frases(self, frases: list) -> bool:
        """Reproduce frases usando streaming real"""
        texto_completo = " ".join(frases)
        return await self._hablar_con_streaming_real(texto_completo)

    async def _reproducir_audio_pregenerado(self, audio_wav: bytes) -> bool:
        """Reproduce audio WAV pre-generado (24k) como PCM 8k, CON monitoreo de barge-in.

        Antes esta reproducción hacía send + sleep ciego, sin leer el canal: si el usuario
        contestaba encima o justo al terminar la frase, ese audio se perdía y el eco acumulado
        confundía al VAD en la escucha siguiente (causa de la "doble pregunta"). Ahora el monitor
        de barge-in consume el canal y captura el inicio de la respuesta en self.barge_in_audio,
        que _escuchar_respuesta reutiliza.
        """
        if self.ws.client_state.name != "CONNECTED":
            return False

        # Reset estado de barge-in
        self.barge_in_detected = False
        self.barge_in_audio = bytearray()

        # Convertir WAV 24k → PCM 8k
        audio_24k = np.frombuffer(audio_wav[44:], dtype=np.int16)  # Skip WAV header
        audio_8k = signal.resample_poly(audio_24k, 1, 3)
        audio_8k = np.clip(audio_8k * 1.5, -32768, 32767).astype(np.int16)
        pcm_data = audio_8k.tobytes()
        total_bytes = len(pcm_data)
        chunk_size = 1600  # 100ms chunks

        monitor_task = None
        chunks_enviados = 0

        try:
            # Envío de audio (activa barge-in tras 5 chunks, como el streaming real)
            for i in range(0, len(pcm_data), chunk_size):
                if self.ws.client_state.name != "CONNECTED":
                    return False
                if monitor_task and self.barge_in_detected:
                    logger.info("🛑 [PRE-GEN] Cortando reproducción por barge-in")
                    break
                await self.ws.send_bytes(pcm_data[i:i+chunk_size])
                chunks_enviados += 1
                if chunks_enviados == 5 and monitor_task is None:
                    logger.info("👂 [PRE-GEN] Activando monitoreo barge-in")
                    monitor_task = asyncio.create_task(self._monitorear_barge_in())
                await asyncio.sleep(0.05)

            # Espera de reproducción (con corte por barge-in)
            if not self.barge_in_detected:
                if monitor_task is None:
                    monitor_task = asyncio.create_task(self._monitorear_barge_in())
                tiempo_restante = total_bytes / 16000
                while tiempo_restante > 0:
                    if self.ws.client_state.name != "CONNECTED":
                        return False
                    if self.barge_in_detected:
                        logger.info("🛑 [PRE-GEN] Barge-in durante espera")
                        break
                    await asyncio.sleep(min(0.1, tiempo_restante))
                    tiempo_restante -= 0.1

            return True
        finally:
            if monitor_task:
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass

    def _es_confirmacion_o_backchannel(self, texto: str) -> bool:
        """
        Detecta si el usuario está confirmando/aceptando información.
        Esto NO es una despedida, requiere preguntar si hay más dudas.
        """
        if not texto:
            return False
        
        texto_lower = texto.lower().strip()
        
        # Confirmaciones que NO son despedidas
        confirmaciones = [
            "ok", "okey", "okay", "vale", "bien", "bueno",
            "ah ok", "ah bueno", "ah ya", "ya veo",
            "está bien", "esta bien", "muy bien", 
            "entiendo", "entendido", "perfecto", "genial",
            "claro", "claro que sí", "de acuerdo", "listo",
            "ah bueno está bien", "ah bueno esta bien",
            "ok perfecto", "bien gracias", "ok gracias",
            "ya entendí", "ya entendi", "ahora sí", "ahora si",
        ]
        
        # Verificar coincidencia exacta o casi exacta
        texto_limpio = texto_lower.rstrip('.,!?')
        
        for conf in confirmaciones:
            if texto_limpio == conf or texto_limpio.startswith(conf + " ") or texto_limpio.endswith(" " + conf):
                return True
        
        # Si tiene menos de 5 palabras y NO contiene palabras interrogativas
        palabras = texto_limpio.split()
        if len(palabras) <= 5:
            interrogativas = ["qué", "que", "cuál", "cual", "cómo", "como", 
                            "dónde", "donde", "cuándo", "cuando", "por qué",
                            "quién", "quien", "cuánto", "cuanto"]
            tiene_pregunta = any(q in texto_lower for q in interrogativas)
            
            # Indicadores de querer más info
            quiere_info = ["quisiera", "gustaría", "gustaria", "quiero", 
                          "puedes", "podrías", "podrias", "dime", "necesito",
                          "también", "tambien", "otra", "otro", "más", "mas"]
            quiere_mas = any(q in texto_lower for q in quiere_info)
            
            if not tiene_pregunta and not quiere_mas:
                # Palabras típicas de confirmación
                palabras_confirm = ["ok", "sí", "si", "bueno", "bien", "claro", 
                                   "perfecto", "genial", "entiendo", "ah", "ya"]
                if any(p in palabras for p in palabras_confirm):
                    return True
        
        return False
    

    def _es_despedida_explicita(self, texto: str) -> bool:
        """
        Detecta SOLO despedidas claras y explícitas.
        Más estricto que _es_despedida() para evitar falsos positivos.
        """
        texto_lower = texto.lower().strip()
        
        # Despedidas explícitas (el usuario claramente quiere terminar)
        despedidas_claras = [
            "no, nada más", "no nada más", "no, nada mas", "no nada mas",
            "no tengo más dudas", "no tengo mas dudas",
            "no tengo más preguntas", "no tengo mas preguntas",
            "no, gracias", "no gracias", 
            "eso es todo", "eso era todo", "era todo",
            "ninguna duda", "ninguna pregunta", "ninguna más", "ninguna mas",
            "chau", "chao", "adiós", "adios", "bye", "hasta luego",
            "nos vemos", "me despido", "hasta pronto",
            "no, ya está", "no ya está", "no, ya esta", "no ya esta",
            "listo, gracias", "listo gracias",
            "perfecto, eso es todo", "perfecto eso es todo",
        ]
        
        for despedida in despedidas_claras:
            if despedida in texto_lower:
                return True
        
        # "gracias" + indicador de cierre
        if "gracias" in texto_lower:
            cierres = ["no", "nada", "eso es todo", "era todo", "listo", "ya no"]
            if any(c in texto_lower for c in cierres):
                return True
        
        return False


    async def _monitorear_barge_in(self):
        """
        PASO 1: Solo detectar voz y marcar para cortar TTS.
        No captura audio, no transcribe, no evalúa.
        """
        vad_monitor = VoiceActivityDetector(sample_rate=8000)
        frames_con_voz = 0
        audio_capturado = bytearray()
        
        while not self.barge_in_detected:
            try:
                if self.ws.client_state.name != "CONNECTED":
                    break
                
                data = await asyncio.wait_for(self.ws.receive_bytes(), timeout=0.05)
                resultado = vad_monitor.process_chunk(data)
                
                if resultado["is_speech"] and resultado["confidence"] > 0.7:
                    frames_con_voz += 1
                    audio_capturado.extend(data)
                    if frames_con_voz >= 6:  # ~260ms de voz sostenida
                        logger.info(f"🛑 [BARGE-IN] Voz detectada ({frames_con_voz} frames, {len(audio_capturado)} bytes) - Cortando TTS")
                        self.barge_in_audio = audio_capturado
                        self.barge_in_detected = True
                        break
                else:
                    frames_con_voz = 0
                        
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning(f"⚠️ Error en monitor barge-in: {e}")
                break


    async def _hablar_sin_barge_in(self, texto: str) -> bool:
        """
        Reproduce audio SIN monitorear barge-in.
        Usado para despedidas donde no queremos interrupciones.
        """
        
        if self.ws.client_state.name != "CONNECTED":
            return False
        
        logger.info(f"🎤 [FINAL] Reproduciendo: '{texto[:40]}...'")
        
        buffer_resample = bytearray()
        total_bytes_8k = 0
        
        try:
            async for chunk in self.tts.synthesize_stream(texto):
                buffer_resample.extend(chunk)
                
                while len(buffer_resample) >= 4800:
                    bloque = bytes(buffer_resample[:4800])
                    buffer_resample = buffer_resample[4800:]
                    
                    audio_24k = np.frombuffer(bloque, dtype=np.int16)
                    audio_8k = signal.resample_poly(audio_24k, 1, 3)
                    audio_8k = np.clip(audio_8k * 1.5, -32768, 32767).astype(np.int16)
                    
                    if self.ws.client_state.name != "CONNECTED":
                        return False
                    
                    await self.ws.send_bytes(audio_8k.tobytes())
                    total_bytes_8k += len(audio_8k.tobytes())
                    await asyncio.sleep(0.01)
            
            # Procesar resto
            if len(buffer_resample) > 0:
                audio_24k = np.frombuffer(bytes(buffer_resample), dtype=np.int16)
                if len(audio_24k) > 3:
                    audio_8k = signal.resample_poly(audio_24k, 1, 3)
                    audio_8k = np.clip(audio_8k * 1.5, -32768, 32767).astype(np.int16)
                    await self.ws.send_bytes(audio_8k.tobytes())
                    total_bytes_8k += len(audio_8k.tobytes())
            
            # Esperar reproducción completa
            duracion = total_bytes_8k / 16000
            await asyncio.sleep(duracion)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error en audio final: {e}")
            return False


    async def _hablar_con_streaming_real(self, texto: str) -> bool:
        """
        Usa xttsv2 con streaming real.
        NUEVO: Monitorea audio entrante para detectar barge-in.
        MEJORADO: Activa barge-in solo después de enviar primeros chunks.
        """
        
        if self.ws.client_state.name != "CONNECTED":
            return False
        
        logger.info(f"🎤 [STREAM] Reproduciendo: '{texto[:40]}...'")
        
        # Reset estado de barge-in
        self.barge_in_detected = False
        self.barge_in_audio = bytearray()
        
        buffer_resample = bytearray()
        total_bytes_8k = 0
        chunks_enviados = 0
        
        # NO iniciar monitor aún - esperar a enviar primeros chunks
        monitor_task = None
        
        try:
            async for chunk in self.tts.synthesize_stream(texto):
                # Verificar si usuario interrumpió (solo si monitor está activo)
                if monitor_task and self.barge_in_detected:
                    logger.info("🛑 [STREAM] Cortando por barge-in")
                    break
                
                buffer_resample.extend(chunk)
                
                while len(buffer_resample) >= 4800:
                    # Verificar barge-in solo si monitor está activo
                    if monitor_task and self.barge_in_detected:
                        logger.info("🛑 [STREAM] Cortando envío por barge-in")
                        break
                    
                    bloque = bytes(buffer_resample[:4800])
                    buffer_resample = buffer_resample[4800:]
                    
                    audio_24k = np.frombuffer(bloque, dtype=np.int16)
                    audio_8k = signal.resample_poly(audio_24k, 1, 3)
                    audio_8k = np.clip(audio_8k * 1.5, -32768, 32767).astype(np.int16)
                    
                    if self.ws.client_state.name != "CONNECTED":
                        return False
                    
                    await self.ws.send_bytes(audio_8k.tobytes())
                    total_bytes_8k += len(audio_8k.tobytes())
                    chunks_enviados += 1
                    
                    # NUEVO: Activar barge-in después del 5to chunk (~300ms de audio)
                    if chunks_enviados == 5 and monitor_task is None:
                        logger.info("👂 [STREAM] Activando monitoreo barge-in")
                        monitor_task = asyncio.create_task(self._monitorear_barge_in())
                    
                    await asyncio.sleep(0.01)
            
            # Procesar resto del buffer (solo si no hubo barge-in)
            if not self.barge_in_detected and len(buffer_resample) > 0:
                audio_24k = np.frombuffer(bytes(buffer_resample), dtype=np.int16)
                if len(audio_24k) > 3:
                    audio_8k = signal.resample_poly(audio_24k, 1, 3)
                    audio_8k = np.clip(audio_8k * 1.5, -32768, 32767).astype(np.int16)
                    await self.ws.send_bytes(audio_8k.tobytes())
                    total_bytes_8k += len(audio_8k.tobytes())
            
            # Calcular duración
            duracion = total_bytes_8k / 16000
            logger.info(f"✅ [STREAM] Enviado {total_bytes_8k} bytes, esperando {duracion:.1f}s")
            
            # Esperar mientras se reproduce (solo si no hubo barge-in)
            if not self.barge_in_detected:
                tiempo_restante = duracion
                warmup_disparado = False
                
                # Si no se activó monitor antes (mensaje muy corto), activarlo ahora
                if monitor_task is None:
                    logger.info("👂 [STREAM] Activando monitoreo barge-in (mensaje corto)")
                    monitor_task = asyncio.create_task(self._monitorear_barge_in())
                
                while tiempo_restante > 0:
                    if self.ws.client_state.name != "CONNECTED":
                        return False
                    if self.barge_in_detected:
                        logger.info("🛑 [STREAM] Barge-in durante espera")
                        break
                    
                    # NUEVO: Warmup del LLM 2 segundos antes de terminar (si duración > 5s)
                    if not warmup_disparado and duracion > 5 and tiempo_restante <= 2:
                        asyncio.create_task(self.llm.keepalive())
                        warmup_disparado = True
                        logger.debug("🔥 [STREAM] Warmup LLM disparado")
                    
                    await asyncio.sleep(min(0.1, tiempo_restante))
                    tiempo_restante -= 0.1
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error en streaming: {e}")
            return False
        finally:
            # Cancelar monitor si existe
            if monitor_task:
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass


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

    def _registrar_turno(self, rol: str, texto: str, categoria: str = None, confianza: float = None):
        """Registra turno de conversación para fine-tuning"""
        if not texto or len(texto) < 2:
            return
        
        self.turno_conversacion += 1
        
        try:
            pg = get_postgres_db()
            if pg.connect():
                pg.registrar_turno_conversacion(
                    empleado_id=self.employee_id,
                    llamada_id=self.llamada_id,
                    turno=self.turno_conversacion,
                    rol=rol,
                    texto=texto,
                    categoria=categoria,
                    confianza_vad=confianza
                )
                pg.disconnect()
        except Exception as e:
            logger.warning(f"⚠️ Error registrando turno: {e}")


    def _actualizar_resultado_postgres(self, resultado: str):
        """Actualiza el resultado de la llamada en PostgreSQL"""
        if self.resultado_registrado:
            logger.debug(f"⏭️ Resultado ya registrado, ignorando: {resultado}")
            return
        
        try:
            pg = get_postgres_db()
            if pg.connect():
                if resultado == "EXITO":
                    pg.marcar_exito(self.employee_id)
                    pg.actualizar_llamada(self.employee_id, "completada")
                else:
                    pg.marcar_intento_fallido(self.employee_id, minutos_espera=5)
                    pg.actualizar_llamada(self.employee_id, "fallida")
                
                pg.disconnect()
                logger.info(f"📊 PostgreSQL actualizado: {resultado}")
                self.resultado_registrado = True
        except Exception as e:
            logger.error(f"❌ Error actualizando PostgreSQL: {e}")

    def _colgar(self):
        """Ordena colgar al sip-service"""
        try:
            requests.get("http://sip-service:8000/?b", timeout=0.5)
            logger.info("📞 Comando colgar enviado")
        except requests.exceptions.Timeout:
            logger.info("📞 Llamada ya finalizada")
        except Exception as e:
            logger.warning(f"⚠️ Colgar: {e}")

    async def _actualizar_resumen(self):
        """Comprime el historial cada 3 turnos en un resumen"""
        if len(self.historial_llm) >= 6:  # 3 pares user/assistant = 6 mensajes
            logger.info("📝 Generando resumen del historial...")

            historial_para_resumir = [
                m for m in self.historial_llm 
                if m['role'] == 'assistant'
            ]
            
            nuevo_resumen = ""
            if historial_para_resumir:
                nuevo_resumen = await self.llm.summarize(historial_para_resumir)

            if nuevo_resumen:
                self.resumen_conversacion = nuevo_resumen
                self.historial_llm = []  # vaciar, el resumen lo reemplaza
                self.turnos_desde_ultimo_resumen = 0
                logger.info(f"✅ Historial comprimido. Resumen: '{nuevo_resumen[:80]}...'")