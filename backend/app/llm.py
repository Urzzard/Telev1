import httpx
import logging
import os
import re

logger = logging.getLogger("LLM")


# ==================== TURN-HANDLER: clasificador de intención ====================
# Prompts y sets VALIDADOS (scripts/eval_intent_2b.py 98.3% + test_turn_handler.py 23/23, 100% estable).
# Diseño: docs/ARQUITECTURA_CEREBRO_LLM.md — clasificar (guided_choice) va SEPARADO de generar.

IDENT_LABELS = ["CONFIRMA", "NIEGA", "PREGUNTA_QUIEN_LLAMA", "CALIBRACION", "OTRO"]
DUDAS_LABELS = ["PREGUNTA", "DESPEDIDA", "FUERA_DE_TEMA", "CALIBRACION", "ACK"]

SYS_IDENT = """Eres un clasificador de intención para un teleoperador de RRHH de Salesland.
Estás en la fase de VERIFICACIÓN DE IDENTIDAD: acabas de preguntar "¿hablo con {nombre}?".
Clasifica la respuesta del usuario en EXACTAMENTE una de estas etiquetas:
- CONFIRMA: confirma que es la persona o te invita a seguir ("sí soy yo", "el mismo", "con él habla", "dígame", "cuénteme").
- NIEGA: dice que no es la persona, que se equivocó, o que es número equivocado.
- PREGUNTA_QUIEN_LLAMA: pregunta QUIÉN llama o DE PARTE de quién ("¿de parte?", "¿quién habla?").
- CALIBRACION: comenta la calidad del audio/conexión o verifica que lo escuchas ("¿me escucha?", "¿sigue ahí?", "no le escucho", "se corta", "hay eco o ruido").
- OTRO: pide esperar o nada de lo anterior ("espere un momento", "ya regreso").
Responde SOLO con la etiqueta, en mayúsculas."""

FEWSHOT_IDENT = [
    ("Sí, dígame nomás", "CONFIRMA"),
    ("No, se equivocó de número", "NIEGA"),
    ("¿Quién me llama?", "PREGUNTA_QUIEN_LLAMA"),
    ("Se escucha un eco horrible", "CALIBRACION"),
    ("Deme un segundo, ya regreso", "OTRO"),
]

SYS_DUDAS = """Eres un clasificador de intención para un teleoperador de RRHH de Salesland.
El usuario YA confirmó su identidad y está en la fase de DUDAS sobre su incorporación.
Los ÚNICOS temas "de su incorporación" son: horario, ubicación/cómo llegar, primer día, documentos a llevar, portal del empleado y motivo de la llamada.
Clasifica su último mensaje en EXACTAMENTE una etiqueta:
- PREGUNTA: pide información sobre alguno de esos temas de su incorporación.
- DESPEDIDA: cierra la conversación o ya no necesita más, dicho de CUALQUIER forma, AUNQUE venga con un agradecimiento ("eso sería todo", "ya estamos", "no tengo más preguntas", "listo gracias", "chau").
- FUERA_DE_TEMA: pregunta algo que NO está en esos temas: noticias, deportes, chistes, clima, política, O temas que se derivan a RRHH presencial (salario, sueldo, vacaciones, beneficios, contrato).
- CALIBRACION: comenta la calidad del audio/conexión o verifica que lo escuchas ("¿me escuchas?", "¿sigues ahí?", "se escucha entrecortado", "no te escucho", "hay bulla o eco").
- ACK: solo reconoce o agradece y la conversación SIGUE abierta ("ok, ya", "ah entiendo", "claro"). Si además cierra o se despide, entonces es DESPEDIDA, no ACK.
Responde SOLO con la etiqueta, en mayúsculas."""

FEWSHOT_DUDAS = [
    ("¿A qué hora es el ingreso?", "PREGUNTA"),
    ("Ya no necesito nada más, gracias", "DESPEDIDA"),
    ("Ya, ok, chau pues", "DESPEDIDA"),
    ("¿Cuánto es el sueldo?", "FUERA_DE_TEMA"),
    ("¿Cómo quedó el partido de ayer?", "FUERA_DE_TEMA"),
    ("Perdona, se cortó, ¿qué decías?", "CALIBRACION"),
    ("Ah ok, perfecto", "ACK"),
]

# estado → (system_prompt, few-shot, labels)
_CLASIF = {
    "IDENTIDAD": (SYS_IDENT, FEWSHOT_IDENT, IDENT_LABELS),
    "DUDAS": (SYS_DUDAS, FEWSHOT_DUDAS, DUDAS_LABELS),
}


class LLMClient:
    def __init__(self):
        self.base_url = os.getenv("VLLM_URL", "http://vllm:8000")
        self.model = os.getenv("VLLM_MODEL", "qwen3.5-2b")
        logger.info(f"🧠 Cliente LLM configurado → vLLM ({self.model})")

    async def warmup(self):
        """Pre-carga el modelo enviando un request mínimo"""
        logger.info("🔥 Warming up LLM (vLLM)...")
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": "Hola"}],
                        "max_tokens": 5,
                        "chat_template_kwargs": {"enable_thinking": False}
                    }
                )
                if response.status_code == 200:
                    logger.info("✅ LLM warm - vLLM respondiendo")
                    return True
                else:
                    logger.warning(f"⚠️ Warmup respondió: {response.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ Warmup falló: {e}")
        return False

    async def keepalive(self):
        """Ping mínimo para mantener el modelo activo"""
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": "ok"}],
                        "max_tokens": 1,
                        "chat_template_kwargs": {"enable_thinking": False}
                    }
                )
                if response.status_code == 200:
                    logger.debug("🔥 LLM keepalive OK")
                    return True
        except Exception as e:
            logger.warning(f"⚠️ LLM keepalive falló: {e}")
        return False

    async def generate_response(self, messages: list) -> str:
        """Genera respuesta del LLM via vLLM"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "max_tokens": 150,
                        "temperature": 0.7,
                        "chat_template_kwargs": {"enable_thinking": False}
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    # Formato OpenAI-compatible
                    texto_crudo = data["choices"][0]["message"]["content"].strip()

                    logger.info(f"🔍 [DEBUG] Respuesta CRUDA ({len(texto_crudo)} chars): '{texto_crudo[:200]}'")

                    texto = self._limpiar_respuesta(texto_crudo)

                    logger.info(f"🤖 LLM Respondió ({len(texto)} chars): '{texto[:100]}'")
                    return texto
                else:
                    logger.error(f"❌ Error vLLM: {response.status_code} - {response.text[:100]}")
                    return ""
        except Exception as e:
            logger.error(f"❌ Error en generate_response: {e}")
            return ""

    async def clasificar_turno(self, estado: str, texto: str, nombre: str = "usted") -> str:
        """Clasifica la intención del turno con guided_choice (per-request; NO afecta a GLPI).

        Paso 1 del turn-handler (ver docs/ARQUITECTURA_CEREBRO_LLM.md). Va SEPARADO de la
        generación: fusionarlos hunde la precisión (98.3% → 50%). Devuelve UNA etiqueta del
        set del estado, o None si falla (para que el esqueleto decida con un fallback).
        """
        cfg = _CLASIF.get(estado)
        if not cfg:
            logger.error(f"❌ [TURN] estado desconocido: {estado}")
            return None
        sys_tpl, fewshot, labels = cfg
        sys_prompt = sys_tpl.format(nombre=nombre) if "{nombre}" in sys_tpl else sys_tpl

        messages = [{"role": "system", "content": sys_prompt}]
        for ej, lab in fewshot:
            messages.append({"role": "user", "content": ej})
            messages.append({"role": "assistant", "content": lab})
        messages.append({"role": "user", "content": texto})

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "max_tokens": 12,
                        "temperature": 0.0,
                        "guided_choice": labels,   # ← fuerza UNA etiqueta del set
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                )
            if response.status_code == 200:
                raw = response.json()["choices"][0]["message"]["content"].strip().upper()
                for lab in labels:
                    if lab in raw:
                        logger.info(f"🧭 [TURN] {estado} → {lab}  ('{texto[:40]}')")
                        return lab
                logger.warning(f"⚠️ [TURN] intent no reconocido: '{raw}' → None")
            else:
                logger.error(f"❌ [TURN] clasificar HTTP {response.status_code}: {response.text[:120]}")
        except Exception as e:
            logger.error(f"❌ [TURN] Error clasificando: {e}")
        return None

    def _limpiar_respuesta(self, texto: str) -> str:
        """Limpia artefactos de la respuesta del LLM"""

        # ========== NUEVO: Eliminar bloques <think>...</think> de Qwen3 ==========
        # Qwen3 usa modo "thinking" que genera estos bloques
        texto = re.sub(r'<think>.*?</think>', '', texto, flags=re.DOTALL | re.IGNORECASE)
        texto = re.sub(r'<\|think\|>.*?<\|/think\|>', '', texto, flags=re.DOTALL)
        
        # También eliminar si quedó abierto (sin cerrar)
        texto = re.sub(r'<think>.*$', '', texto, flags=re.DOTALL | re.IGNORECASE)
        
        # Eliminar otros tokens especiales de Qwen3
        texto = re.sub(r'<\|.*?\|>', '', texto)
        
        # Eliminar "Ana:" o "Jorge:" al inicio o en medio
        texto = re.sub(r'\bAna:\s*', '', texto)
        texto = re.sub(r'\bJorge:\s*', '', texto)
        
        # Eliminar emojis
        texto = re.sub(r'[🌟😊👋🎉✨💼📧🏢⏰📍]', '', texto)

        # ========== Detectar prompt leak ==========
        patrones_leak = [
            r'═{3,}',
            r'-{5,}',
            r'DATOS DEL EMPLEADO',
            r'REGLAS ESTRICTAS',
            r'TEMAS QUE NO PUEDES',
            r'system prompt',
            r'asistente telefónica',
            r'SOLO RESPOND',
            r'role.*user',
            r'role.*assistant',
            r'\(Recuerda',
            r'no debes compartir',
            r'detalles específicos',
            r'no puedes responder',
            r'INFORMACIÓN QUE',
            r'TEMAS QUE NO',
            r'Estás en llamada con',
            r'siguiendo las reglas',
            r'reglas proporcionadas',
            r'como asistente', 
        ]
        
        for patron in patrones_leak:
            if re.search(patron, texto, re.IGNORECASE):
                logger.warning(f"⚠️ PROMPT LEAK detectado, usando respuesta genérica")
                return "Disculpa, no entendí bien tu pregunta. ¿Podrías repetirla?"

        despedidas = [
            r'¡?Te deseo un buen día!?',
            r'¡?Que tengas buen día!?',
            r'¡?Que tengas un.*$',
            r'¡?Buen día!?',
            r'¡?Hasta pronto!?',
            r'¡?Éxito!?',
            r'¡?Mucho éxito!?',
        ]

        for patron in despedidas:
            texto = re.sub(patron, '', texto, flags=re.IGNORECASE)
        
        # ========== NUEVO: Truncamiento inteligente ==========
        MAX_CHARS = 300  # Aumentado de 250 a 400
        
        if len(texto) > MAX_CHARS:
            # Buscar el último punto FINAL de oración (no p.m., a.m., etc.)
            # Patrón: punto seguido de espacio y mayúscula, o punto final
            texto_cortado = texto[:MAX_CHARS]
            
            # Buscar último punto que termine oración
            ultimo_punto = -1
            for i in range(len(texto_cortado) - 1, 0, -1):
                if texto_cortado[i] == '.':
                    # Verificar que no sea p.m., a.m., etc.
                    antes = texto_cortado[max(0, i-2):i].lower()
                    if antes not in ['p.', 'a.', 'dr', 'sr', 'ra']:
                        ultimo_punto = i
                        break
            
            if ultimo_punto > 80:  # Al menos 80 chars de contenido
                texto = texto[:ultimo_punto + 1]
            else:
                # Si no encontró punto, buscar última coma o punto y coma
                ultimo_separador = max(
                    texto_cortado.rfind(','),
                    texto_cortado.rfind(';'),
                    texto_cortado.rfind('?'),
                    texto_cortado.rfind('!')
                )
                if ultimo_separador > 80:
                    texto = texto[:ultimo_separador + 1]
                else:
                    # Último recurso: cortar en espacio
                    ultimo_espacio = texto_cortado.rfind(' ')
                    if ultimo_espacio > 100:
                        texto = texto[:ultimo_espacio] + "."
                    else:
                        texto = texto_cortado + "."
            
            logger.warning(f"⚠️ Respuesta truncada a {len(texto)} chars")
        
        # Eliminar líneas vacías múltiples
        texto = re.sub(r'\n\s*\n', '\n', texto)
        
        # Eliminar espacios múltiples
        texto = re.sub(r'  +', ' ', texto)
        
        return texto.strip()

    async def summarize(self, historial: list) -> str:
        """Comprime el historial en un resumen conciso"""
        historial_texto = "\n".join([
            f"{'Usuario' if m['role'] == 'user' else 'Asistente'}: {m['content']}"
            for m in historial
        ])
        
        messages = [
            {
                "role": "system",
                "content": """Eres un extractor de información. Lista SOLO los datos concretos mencionados en la conversación.
                                Formato estricto: "[tema]: [dato exacto mencionado]"
                                Ejemplo: "Horario: 9am-6pm con descanso 1-2pm. Dirección: Jirón Cachay 393 La Victoria."
                                PROHIBIDO: inventar datos, agregar interpretaciones, mencionar personas."""
            },
            {
                "role": "user",
                "content": historial_texto
            }
        ]
        
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "max_tokens": 120,  # ~100 tokens de resumen real
                        "temperature": 0.3,  # más determinista para resúmenes
                        "chat_template_kwargs": {"enable_thinking": False}
                    }
                )
                if response.status_code == 200:
                    resumen = response.json()["choices"][0]["message"]["content"].strip()
                    logger.info(f"📝 Resumen generado ({len(resumen)} chars): '{resumen}'")
                    return resumen
        except Exception as e:
            logger.warning(f"⚠️ Error generando resumen: {e}")
        
        return ""


# ==================== SINGLETON ====================

_llm_instance = None

def get_llm():
    """Retorna instancia única del cliente LLM"""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = LLMClient()
    return _llm_instance

async def warmup_llm():
    """Función para hacer warmup del LLM al iniciar"""
    llm = get_llm()
    await llm.warmup()