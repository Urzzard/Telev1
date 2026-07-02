"""
Módulo de conexión a PostgreSQL
Base de datos local para control de llamadas
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("PostgreSQL")


class PostgresDB:
    """Gestor de conexión a PostgreSQL"""
    
    def __init__(self):
        self.config = {
            "host": os.getenv("POSTGRES_HOST", "postgres"),
            "port": int(os.getenv("POSTGRES_PORT", 5432)),
            "database": os.getenv("POSTGRES_DB", "telefonista"),
            "user": os.getenv("POSTGRES_USER", "telefonista"),
            "password": os.getenv("POSTGRES_PASSWORD", "telefonista123"),
        }
        self.connection = None
    
    def connect(self) -> bool:
        """Establece conexión"""
        try:
            self.connection = psycopg2.connect(**self.config)
            logger.info(f"✅ Conectado a PostgreSQL: BD Interna de llamadas")
            return True
        except Exception as e:
            logger.error(f"❌ Error conectando a PostgreSQL: {e}")
            return False
    
    def disconnect(self):
        """Cierra conexión"""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def _ensure_connection(self):
        """Asegura conexión activa"""
        if not self.connection or self.connection.closed:
            self.connect()
    
    @contextmanager
    def get_cursor(self):
        """Context manager para cursor"""
        self._ensure_connection()
        cursor = self.connection.cursor(cursor_factory=RealDictCursor)
        try:
            yield cursor
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise e
        finally:
            cursor.close()
    
    # ==========================================
    # CONFIGURACIÓN
    # ==========================================
    
    def get_config(self, clave: str) -> Optional[str]:
        """Obtiene valor de configuración"""
        with self.get_cursor() as cur:
            cur.execute("SELECT valor FROM configuracion WHERE clave = %s", (clave,))
            row = cur.fetchone()
            return row["valor"] if row else None
    
    def set_config(self, clave: str, valor: str):
        """Actualiza valor de configuración"""
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO configuracion (clave, valor, actualizado_en)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (clave) DO UPDATE SET 
                    valor = EXCLUDED.valor,
                    actualizado_en = CURRENT_TIMESTAMP
            """, (clave, valor))
    
    def get_ultimo_id_externo(self) -> int:
        """Obtiene último ID sincronizado"""
        valor = self.get_config("ultimo_id_externo")
        return int(valor) if valor else 0
    
    def set_ultimo_id_externo(self, id_externo: int):
        """Actualiza último ID sincronizado"""
        self.set_config("ultimo_id_externo", str(id_externo))
    
    # ==========================================
    # EMPLEADOS
    # ==========================================
    
    def insertar_empleado(self, empleado: Dict[str, Any]) -> Optional[int]:
        """Inserta nuevo empleado, retorna ID o None si ya existe"""
        try:
            with self.get_cursor() as cur:
                cur.execute("""
                    INSERT INTO empleados (
                        id_externo, nombre, documento, celular, 
                        puesto, fecha_ingreso
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id_externo) DO NOTHING
                    RETURNING id
                """, (
                    empleado["id_externo"],
                    empleado["nombre"],
                    empleado.get("documento"),
                    empleado["celular"],
                    empleado.get("puesto"),
                    empleado.get("fecha_ingreso")
                ))
                
                row = cur.fetchone()
                if row:
                    logger.info(f"✅ Empleado insertado: {empleado['nombre']} (ID: {empleado['id_externo']})")
                    return row["id"]
                return None
                
        except Exception as e:
            logger.error(f"❌ Error insertando empleado: {e}")
            return None
    
    def obtener_siguiente_pendiente(self) -> Optional[Dict[str, Any]]:
        """Obtiene siguiente empleado pendiente de llamar"""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT id, id_externo, nombre, celular, puesto, 
                       fecha_ingreso, intentos
                FROM empleados
                WHERE estado = 'PENDIENTE' 
                  AND intentos < 3
                  AND proxima_llamada <= CURRENT_TIMESTAMP
                ORDER BY proxima_llamada ASC
                LIMIT 1
            """)
            row = cur.fetchone()
            return dict(row) if row else None
    
    def contar_pendientes(self) -> int:
        """Cuenta empleados pendientes de llamar"""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as total FROM empleados
                WHERE estado = 'PENDIENTE' AND intentos < 3
            """)
            return cur.fetchone()["total"]
    
    # ==========================================
    # ACTUALIZACIÓN DE ESTADOS
    # ==========================================
    
    def marcar_exito(self, empleado_id: int):
        """Marca llamada como exitosa"""
        with self.get_cursor() as cur:
            cur.execute("""
                UPDATE empleados 
                SET estado = 'EXITO', intentos = intentos + 1
                WHERE id = %s
            """, (empleado_id,))
        logger.info(f"✅ Empleado {empleado_id} → EXITO")
    
    def marcar_intento_fallido(self, empleado_id: int, minutos_espera: int = 5):
        """Incrementa intentos, marca TERMINADO si llega a 3"""
        with self.get_cursor() as cur:
            # Obtener intentos actuales
            cur.execute("SELECT intentos FROM empleados WHERE id = %s", (empleado_id,))
            row = cur.fetchone()
            
            if not row:
                return
            
            nuevos_intentos = row["intentos"] + 1
            
            if nuevos_intentos >= 3:
                cur.execute("""
                    UPDATE empleados 
                    SET estado = 'TERMINADO', intentos = %s, actualizado_en = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (nuevos_intentos, empleado_id))
                logger.warning(f"⚠️ Empleado {empleado_id} → TERMINADO (3 intentos)")
            else:
                # make_interval pasa los minutos como parámetro entero (robusto, sin %s dentro del literal)
                cur.execute("""
                    UPDATE empleados
                    SET estado = 'PENDIENTE',
                        intentos = %s,
                        proxima_llamada = CURRENT_TIMESTAMP + make_interval(mins => %s),
                        actualizado_en = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (nuevos_intentos, minutos_espera, empleado_id))
                logger.info(f"🔄 Empleado {empleado_id}: intento {nuevos_intentos}/3 → PENDIENTE (próximo en {minutos_espera}min)")

    def hay_llamada_activa(self) -> bool:
        """Verifica si hay una llamada EN_LLAMADA activa"""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as total FROM empleados
                WHERE estado = 'EN_LLAMADA'
            """)
            return cur.fetchone()["total"] > 0
    
    def marcar_en_llamada(self, empleado_id: int):
        """Marca empleado como EN_LLAMADA (llamada activa)"""
        with self.get_cursor() as cur:
            cur.execute("""
                UPDATE empleados
                SET estado = 'EN_LLAMADA', actualizado_en = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (empleado_id,))
        logger.info(f"📞 Empleado {empleado_id} → EN_LLAMADA")

    def resetear_llamadas_colgadas(self, minutos: int = 10) -> int:
        """Watchdog: devuelve a PENDIENTE las llamadas EN_LLAMADA colgadas
        (más de `minutos` sin actualizar) para no bloquear la cola para siempre."""
        with self.get_cursor() as cur:
            cur.execute("""
                UPDATE empleados
                SET estado = 'PENDIENTE', actualizado_en = CURRENT_TIMESTAMP
                WHERE estado = 'EN_LLAMADA'
                  AND actualizado_en < CURRENT_TIMESTAMP - make_interval(mins => %s)
            """, (minutos,))
            n = cur.rowcount
        if n:
            logger.warning(f"🐕 Watchdog: {n} llamada(s) colgada(s) devuelta(s) a PENDIENTE (>{minutos}min EN_LLAMADA)")
        return n
    
    # ==========================================
    # REGISTRO DE LLAMADAS
    # ==========================================
    
    def registrar_llamada(self, empleado_id: int, intento: int, 
                          resultado: str, duracion: int = 0, notas: str = None) -> int:
        """Registra intento de llamada en historial"""
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO llamadas (
                    empleado_id, intento, resultado, 
                    duracion_segundos, finalizada_en, notas
                ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                RETURNING id
            """, (empleado_id, intento, resultado, duracion, notas))
            llamada_id = cur.fetchone()["id"]
        logger.info(f"📝 Llamada registrada: emp={empleado_id}, llamada_id={llamada_id}")
        return llamada_id
    
    # ==========================================
    # ESTADÍSTICAS
    # ==========================================
    
    def obtener_resumen(self) -> Dict[str, int]:
        """Resumen de estados"""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT estado, COUNT(*) as total
                FROM empleados GROUP BY estado
            """)
            resumen = {row["estado"]: row["total"] for row in cur.fetchall()}
            
            cur.execute("SELECT COUNT(*) as total FROM empleados")
            resumen["TOTAL"] = cur.fetchone()["total"]
            
            return resumen


    def actualizar_llamada(self, empleado_id: int, resultado: str):
        """Actualiza la última llamada en curso de un empleado"""
        with self.get_cursor() as cur:
            cur.execute("""
                UPDATE llamadas 
                SET resultado = %s, 
                    finalizada_en = CURRENT_TIMESTAMP,
                    duracion_segundos = EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - iniciada_en))::integer
                WHERE id = (
                    SELECT id FROM llamadas 
                    WHERE empleado_id = %s AND resultado = 'en_curso'
                    ORDER BY iniciada_en DESC
                    LIMIT 1
                )
            """, (resultado, empleado_id))
        logger.info(f"📝 Llamada actualizada: emp={empleado_id}, resultado={resultado}")


    # ==========================================
    # CONVERSACIONES (PARA FINE-TUNING)
    # ==========================================
    
    def registrar_turno_conversacion(
        self, 
        empleado_id: int,
        llamada_id: int,
        turno: int,
        rol: str,  # 'usuario' o 'asistente'
        texto: str,
        categoria: str = None,
        confianza_vad: float = None
    ):
        """Registra un turno de conversación para fine-tuning"""
        try:
            with self.get_cursor() as cur:
                cur.execute("""
                    INSERT INTO conversaciones (
                        empleado_id, llamada_id, turno, rol, texto, categoria, confianza_vad
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (empleado_id, llamada_id, turno, rol, texto, categoria, confianza_vad))
        except Exception as e:
            logger.warning(f"⚠️ Error guardando turno: {e}")
    
    def obtener_conversacion(self, empleado_id: int) -> list:
        """Obtiene conversación completa de un empleado (para debug/review)"""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT turno, rol, texto, categoria, timestamp
                FROM conversaciones 
                WHERE empleado_id = %s
                ORDER BY timestamp ASC
            """, (empleado_id,))
            return [dict(row) for row in cur.fetchall()]


# Instancia global
_db_instance = None

def get_postgres_db() -> PostgresDB:
    """Retorna instancia única"""
    global _db_instance
    if _db_instance is None:
        _db_instance = PostgresDB()
    return _db_instance