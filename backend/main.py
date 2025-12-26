from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from contextlib import asynccontextmanager
from app.stt import get_stt
from app.llm import warmup_llm
from app.postgres_db import get_postgres_db
from app.vad import get_vad
import requests
import logging
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Main")

_keepalive_task = None

async def llm_keepalive_loop():
    """Mantiene el LLM caliente haciendo pings cada 2 minutos"""
    from app.llm import get_llm
    llm = get_llm()
    
    while True:
        await asyncio.sleep(60)
        try:
            await llm.keepalive()
        except Exception as e:
            logger.warning(f"⚠️ Error en keepalive loop: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup y shutdown del servidor"""
    global _keepalive_task
    
    logger.info("🚀 Iniciando servicios...")
    
    logger.info("🎤 Cargando Whisper...")
    get_stt()

    logger.info("🔊 Cargando Silero VAD...")
    get_vad()
    
    logger.info("🧠 Haciendo warmup del LLM...")
    await warmup_llm()
    
    logger.info("🔥 Iniciando LLM keepalive task...")
    _keepalive_task = asyncio.create_task(llm_keepalive_loop())
    
    logger.info("✅ Todos los servicios listos!")
    
    yield
    
    if _keepalive_task:
        _keepalive_task.cancel()
        try:
            await _keepalive_task
        except asyncio.CancelledError:
            pass
    
    logger.info("👋 Cerrando servicios...")


app = FastAPI(lifespan=lifespan)

# Variable global para almacenar el ID del empleado actual
CURRENT_CALL_ID = None


def _obtener_empleado_postgres(employee_id: int):
    """Obtiene datos del empleado desde PostgreSQL"""
    try:
        pg = get_postgres_db()
        if pg.connect():
            with pg.get_cursor() as cur:
                cur.execute("""
                    SELECT id, nombre, celular, puesto
                    FROM empleados WHERE id = %s
                """, (employee_id,))
                row = cur.fetchone()
            pg.disconnect()
            
            if row:
                return {
                    "id": row["id"],
                    "nombre": row["nombre"],
                    "telefono": row["celular"],
                    "puesto": row["puesto"]
                }
    except Exception as e:
        logger.error(f"❌ Error consultando PostgreSQL: {e}")
    return None


@app.post("/call")
def make_call(id: int):
    """
    Inicia llamada a un empleado por su ID.
    """
    global CURRENT_CALL_ID
    
    # Buscar empleado en PostgreSQL
    employee = _obtener_empleado_postgres(id)
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
    
    # Guardar ID actual para el WebSocket
    CURRENT_CALL_ID = id
    
    # Llamar con prefijo del proveedor
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
    """Retorna el ID del empleado de la llamada actual."""
    global CURRENT_CALL_ID
    
    if CURRENT_CALL_ID is None:
        return {"id": None, "status": "no_active_call"}
    
    return {"id": CURRENT_CALL_ID, "status": "active"}


@app.websocket("/ws/audio")
async def audio_websocket(websocket: WebSocket, id: int, duracion: int = 0):
    """WebSocket de audio para la llamada."""
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


@app.post("/call_failed")
async def call_failed(id: int, reason: str = "no_contestado"):
    """Callback cuando una llamada falla (timeout, rechazada, etc.)"""
    logger.warning(f"📴 Llamada fallida para empleado {id}: {reason}")
    
    try:
        pg = get_postgres_db()
        if pg.connect():
            pg.marcar_intento_fallido(id, minutos_espera=5)
            pg.actualizar_llamada(id, "fallida")
            pg.disconnect()
            logger.info(f"📊 Empleado {id}: intento fallido registrado")
            return {"status": "ok"}
    except Exception as e:
        logger.error(f"❌ Error actualizando estado: {e}")
    
    return {"status": "error"}