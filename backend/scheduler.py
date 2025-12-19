"""
Servicio de Sincronización y Dispatcher de Llamadas
- Sincroniza empleados de SQL Server → PostgreSQL
- Dispara llamadas a empleados pendientes
- Marca EN_LLAMADA para evitar llamadas duplicadas
"""
import os
import time
import logging
import requests
from datetime import datetime

from app.postgres_db import get_postgres_db
from app.sqlserver_db import get_sqlserver_db

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Scheduler")

# Configuración
SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL_MINUTES", 5)) * 60
CALL_INTERVAL = int(os.getenv("CALL_INTERVAL_SECONDS", 30))
RETRY_DELAY = int(os.getenv("RETRY_DELAY_MINUTES", 4))
HORARIO_INICIO = int(os.getenv("HORARIO_INICIO", 9))
HORARIO_FIN = int(os.getenv("HORARIO_FIN", 18))
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")


def esta_en_horario() -> bool:
    """Verifica si estamos en horario de llamadas"""
    hora_actual = datetime.now().hour
    return HORARIO_INICIO <= hora_actual < HORARIO_FIN


def sincronizar_empleados():
    """Sincroniza empleados nuevos de SQL Server a PostgreSQL"""
    logger.info("🔄 Iniciando sincronización...")
    
    pg = get_postgres_db()
    sql = get_sqlserver_db()
    
    try:
        if not pg.connect():
            logger.error("❌ No se pudo conectar a PostgreSQL")
            return 0
        
        if not sql.connect():
            logger.error("❌ No se pudo conectar a SQL Server")
            return 0
        
        ultimo_id = pg.get_ultimo_id_externo()
        logger.info(f"📊 Último ID sincronizado: {ultimo_id}")
        
        nuevos = sql.obtener_nuevos_empleados(ultimo_id)
        
        if not nuevos:
            logger.info("📭 Sin empleados nuevos")
            return 0
        
        logger.info(f"📥 {len(nuevos)} empleados nuevos encontrados")
        
        insertados = 0
        max_id = ultimo_id
        
        for emp in nuevos:
            result = pg.insertar_empleado(emp)
            if result:
                insertados += 1
            if emp["id_externo"] > max_id:
                max_id = emp["id_externo"]
        
        if max_id > ultimo_id:
            pg.set_ultimo_id_externo(max_id)
            logger.info(f"📊 Último ID actualizado: {max_id}")
        
        logger.info(f"✅ Sincronización completada: {insertados} insertados")
        return insertados
        
    except Exception as e:
        logger.error(f"❌ Error en sincronización: {e}")
        return 0
    finally:
        pg.disconnect()
        sql.disconnect()


def procesar_cola():
    """Procesa la cola de llamadas pendientes - UNA A LA VEZ"""
    # if not esta_en_horario():
    #     hora = datetime.now().strftime("%H:%M")
    #     logger.debug(f"⏰ Fuera de horario ({hora})")
    #     return
    
    pg = get_postgres_db()
    
    try:
        if not pg.connect():
            return
        
        # Verificar si hay una llamada EN_LLAMADA (activa)
        if pg.hay_llamada_activa():
            logger.info("📞 Hay una llamada activa, esperando...")
            return
        
        # Obtener siguiente pendiente
        empleado = pg.obtener_siguiente_pendiente()
        
        if not empleado:
            return
        
        intento_actual = empleado["intentos"] + 1
        logger.info(f"📋 Procesando: {empleado['nombre']} (intento {intento_actual}/3)")
        
        # MARCAR COMO EN_LLAMADA ANTES de llamar
        pg.marcar_en_llamada(empleado["id"])
        
        # Registrar inicio de llamada
        pg.registrar_llamada(
            empleado_id=empleado["id"],
            intento=intento_actual,
            resultado="en_curso",
            notas="Llamada iniciada"
        )
        
        # Disparar llamada
        try:
            response = requests.post(
                f"{BACKEND_URL}/call",
                params={"id": empleado["id"]},
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Llamada iniciada para {empleado['nombre']}")
            else:
                logger.error(f"❌ Error HTTP: {response.status_code}")
                pg.marcar_intento_fallido(empleado["id"], RETRY_DELAY)
                
        except Exception as e:
            logger.error(f"❌ Error en llamada: {e}")
            pg.marcar_intento_fallido(empleado["id"], RETRY_DELAY)
            
    except Exception as e:
        logger.error(f"❌ Error procesando cola: {e}")
    finally:
        pg.disconnect()


def mostrar_resumen():
    """Muestra resumen de estado"""
    pg = get_postgres_db()
    try:
        if pg.connect():
            resumen = pg.obtener_resumen()
            partes = [f"{k}: {v}" for k, v in resumen.items()]
            logger.info(f"📈 Estado: {' | '.join(partes)}")
    except:
        pass
    finally:
        pg.disconnect()


def main():
    """Loop principal del scheduler"""
    logger.info("=" * 60)
    logger.info("🚀 SCHEDULER INICIADO")
    logger.info("=" * 60)
    logger.info(f"⚙️ Configuración:")
    logger.info(f"   Sync cada: {SYNC_INTERVAL // 60} minutos")
    logger.info(f"   Check llamadas cada: {CALL_INTERVAL} segundos")
    logger.info(f"   Horario: {HORARIO_INICIO}:00 - {HORARIO_FIN}:00")
    logger.info(f"   Reintento después de: {RETRY_DELAY} minutos")
    logger.info("=" * 60)
    
    ultima_sync = 0
    ultimo_resumen = 0
    
    while True:
        try:
            ahora = time.time()
            
            if ahora - ultima_sync >= SYNC_INTERVAL:
                sincronizar_empleados()
                ultima_sync = ahora
            
            procesar_cola()
            
            if ahora - ultimo_resumen >= 300:
                mostrar_resumen()
                ultimo_resumen = ahora
            
            time.sleep(CALL_INTERVAL)
            
        except KeyboardInterrupt:
            logger.info("👋 Scheduler detenido")
            break
        except Exception as e:
            logger.error(f"❌ Error en loop principal: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()