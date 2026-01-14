import httpx
import logging
import os
import json
import requests

logger = logging.getLogger("LLM")


class LLMClient:
    def __init__(self):
        self.base_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        self.model = "phi4-mini"
        logger.info(f"🧠 Cliente LLM configurado ({self.model})")
        self._ensure_model_exists()

    def _ensure_model_exists(self):
        """Verifica si el modelo existe en Ollama, si no, lo descarga."""
        try:
            res = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if res.status_code == 200:
                models = [m['name'] for m in res.json().get('models', [])]
                if any(self.model in m for m in models):
                    logger.info(f"✅ Modelo {self.model} ya está descargado.")
                    return

            logger.warning(f"⚠️ Modelo {self.model} no encontrado. Iniciando descarga...")
            pull_res = requests.post(f"{self.base_url}/api/pull", json={"name": self.model}, stream=True)
            
            if pull_res.status_code == 200:
                logger.info(f"⬇️ Descargando {self.model}...")
                for line in pull_res.iter_lines():
                    if line:
                        status = json.loads(line).get('status')
                        if status == 'success':
                            logger.info(f"✅ Modelo {self.model} descargado exitosamente.")
                            return
            else:
                logger.error(f"❌ Falló la descarga del modelo: {pull_res.text}")

        except Exception as e:
            logger.error(f"❌ Error verificando modelo Ollama: {e}")

    async def warmup(self):
        """Pre-carga el modelo en GPU para evitar latencia en primera llamada"""
        logger.info("🔥 Warming up LLM...")
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": "Hola"}],
                        "stream": False,
                        "options": {"num_predict": 5}
                    }
                )
                if response.status_code == 200:
                    logger.info("✅ LLM warm - modelo cargado en GPU")
                    return True
                else:
                    logger.warning(f"⚠️ Warmup respondió con código: {response.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ Warmup falló: {e}")
        return False

    async def keepalive(self):
        """Ping mínimo para mantener el modelo en GPU"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": "ok"}],
                        "stream": False,
                        "options": {"num_predict": 1}
                    }
                )
                if response.status_code == 200:
                    logger.debug("🔥 LLM keepalive OK")
                    return True
        except Exception as e:
            logger.warning(f"⚠️ LLM keepalive falló: {e}")
        return False

    async def generate_response(self, messages: list) -> str:
        """Genera respuesta del LLM"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                        "options": {
                            "num_predict": 150,
                            "temperature": 0.7,
                            "stop": ["\n\n", "---", "===", "DATOS", "REGLAS"]
                        }
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    texto = data.get("message", {}).get("content", "").strip()
                    
                    # Limpiar respuesta de artefactos
                    texto = self._limpiar_respuesta(texto)
                    
                    logger.info(f"🤖 LLM Respondió: {texto[:50]}...")
                    return texto
                else:
                    logger.error(f"❌ Error LLM: {response.status_code}")
                    return ""
        except Exception as e:
            logger.error(f"❌ Error en generate_response: {e}")
            return ""

    def _limpiar_respuesta(self, texto: str) -> str:
        """Limpia artefactos de la respuesta del LLM"""
        import re
        
        # Eliminar "Ana:" al inicio o en medio
        texto = re.sub(r'\bAna:\s*', '', texto)
        
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
        MAX_CHARS = 250  # Aumentado de 200 a 250
        
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