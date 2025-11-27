from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from contextlib import asynccontextmanager
from app.database import EmployeeRepository
from app.stt import get_stt
from app.llm import warmup_llm
import requests
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup y shutdown del servidor"""
    # ==================== STARTUP ====================
    logger.info("🚀 Iniciando servicios...")
    
    # Pre-cargar Whisper en GPU
    logger.info("🎤 Cargando Whisper...")
    get_stt()
    
    # Pre-cargar LLM en GPU (warmup)
    logger.info("🧠 Haciendo warmup del LLM...")
    await warmup_llm()
    
    logger.info("✅ Todos los servicios listos!")
    
    yield  # La aplicación corre aquí
    
    # ==================== SHUTDOWN ====================
    logger.info("👋 Cerrando servicios...")


app = FastAPI(lifespan=lifespan)
db = EmployeeRepository()

# Variable global para almacenar el ID del empleado actual
CURRENT_CALL_ID = None


@app.post("/call")
def make_call(id: int):
    """
    Inicia llamada a un empleado por su ID.
    
    Params:
        id: ID del empleado en la base de datos
    
    Example:
        POST /call?id=1
    """
    global CURRENT_CALL_ID
    
    # 1. Buscar empleado por ID
    employee = db.get_employee_by_id(id)
    if not employee:
        raise HTTPException(
            status_code=404, 
            detail=f"Empleado con ID {id} no encontrado en base de datos"
        )
    
    nombre = employee.get('nombre', 'Desconocido')
    telefono = employee.get('telefono')
    
    if not telefono:
        raise HTTPException(
            status_code=400,
            detail=f"Empleado {nombre} no tiene teléfono registrado"
        )
    
    logger.info(f"📋 Empleado: {nombre} (ID: {id})")
    logger.info(f"📞 Teléfono: {telefono}")
    
    # 2. Guardar ID actual para el WebSocket
    CURRENT_CALL_ID = id
    
    # 3. Llamar con prefijo del proveedor
    numero_completo = f"333{telefono}"
    
    try:
        response = requests.get(
            f"http://sip-service:8000/?d{numero_completo}", 
            timeout=2
        )
        
        if response.status_code == 200:
            return {
                "status": "calling",
                "employee_id": id,
                "nombre": nombre,
                "telefono": telefono
            }
        else:
            raise HTTPException(
                status_code=500,
                detail="Error al iniciar llamada en SIP service"
            )
            
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error conectando con SIP service: {str(e)}"
        )


@app.get("/current_call_id")
def get_current_call_id():
    """
    Retorna el ID del empleado de la llamada actual.
    Usado por bridge.py para saber a quién está llamando.
    """
    global CURRENT_CALL_ID
    
    if CURRENT_CALL_ID is None:
        return {"id": None, "status": "no_active_call"}
    
    return {"id": CURRENT_CALL_ID, "status": "active"}


@app.websocket("/ws/audio")
async def audio_websocket(websocket: WebSocket, id: int, duracion: int = 0):
    """
    WebSocket de audio para la llamada.
    
    Params:
        id: Query param con el ID del empleado
        duracion: Segundos que tardó la llamada en establecerse (para detección buzón)
    """
    await websocket.accept()
    logger.info(f"🔌 WebSocket conectado para empleado ID: {id}")
    
    from app.call_agent import CallAgent
    
    agent = CallAgent(websocket, id)
    agent.duracion_marcado = duracion
    
    try:
        await agent.iniciar_conversacion()
    except WebSocketDisconnect:
        logger.info("Socket desconectado")
    except Exception as e:
        logger.error(f"Error en conversación: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            await websocket.close()
        except:
            pass