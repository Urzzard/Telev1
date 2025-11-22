from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from app.simple_agent import SimpleAudioTester
#from app.agent import CallAgent
import requests
import logging

# Configuración de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Main")

app = FastAPI()

@app.post("/call")
def make_call(numero: str):
    try:
        # Iniciamos la llamada en Baresip
        requests.get(f"http://sip-service:8000/?d{numero}", timeout=1)
        return {"status": "calling", "number": numero}
    except Exception as e:
        return {"error": str(e)}

@app.websocket("/ws/audio")
async def audio_websocket(websocket: WebSocket):
    await websocket.accept()
    logger.info("🔌 Nueva conexión de llamada entrante")
    
    tester = SimpleAudioTester(websocket)
    
    try:
        await tester.run_test()
    except WebSocketDisconnect:
        logger.info("Socket desconectado")
    except Exception as e:
        logger.error(f"Error crítico: {e}")
    finally:
        try:
            await websocket.close()
        except:
            pass