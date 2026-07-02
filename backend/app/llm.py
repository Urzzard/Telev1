import httpx
import logging
import os
import re

logger = logging.getLogger("LLM")


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