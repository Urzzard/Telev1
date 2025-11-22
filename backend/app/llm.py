import aiohttp
import logging
import os
import json
import requests

logger = logging.getLogger("LLM")

class LLMClient:
    def __init__(self):
        self.ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        self.model = "phi4-mini" # O el modelo que prefieras
        logger.info(f"🧠 Cliente LLM configurado ({self.model})")

        self._ensure_model_exists()

    def _ensure_model_exists(self):
        """Verifica si el modelo existe en Ollama, si no, lo descarga."""
        try:
            # 1. Listar modelos locales
            res = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if res.status_code == 200:
                models = [m['name'] for m in res.json().get('models', [])]
                # Buscamos si nuestro modelo (o con tag :latest) está en la lista
                if any(self.model in m for m in models):
                    logger.info(f"✅ Modelo {self.model} ya está descargado.")
                    return

            # 2. Si no está, forzar descarga (Pull)
            logger.warning(f"⚠️ Modelo {self.model} no encontrado. Iniciando descarga automática... (Esto puede tardar)")
            # Usamos stream=True para no bloquear, aunque el init bloqueará hasta terminar
            # En producción, esto debería ser async, pero para el arranque está bien.
            pull_res = requests.post(f"{self.ollama_url}/api/pull", json={"name": self.model}, stream=True)
            
            if pull_res.status_code == 200:
                logger.info(f"⬇️ Descargando {self.model}...")
                # Consumimos el stream para esperar a que termine
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

    async def generate_response(self, messages: list):
        """
        Envía historial de chat a Ollama y obtiene respuesta.
        """
        url = f"{self.ollama_url}/api/chat"
        
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "num_predict": 100 # Respuestas cortas
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data.get("message", {}).get("content", "")
                        logger.info(f"🤖 LLM Respondió: {content[:50]}...")
                        return content
                    else:
                        logger.error(f"❌ Error Ollama: {response.status}")
                        return "Lo siento, tuve un problema técnico."
        except Exception as e:
            logger.error(f"❌ Error conectando con Ollama: {e}")
            return "Hola, no puedo procesar tu solicitud en este momento."