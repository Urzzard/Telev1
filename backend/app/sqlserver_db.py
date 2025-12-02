"""
Módulo de conexión a SQL Server
Base de datos externa (solo lectura) para obtener empleados nuevos
"""
import os
import logging
from typing import List, Dict, Any, Optional

import pymssql

logger = logging.getLogger("SQLServer")


class SQLServerDB:
    """Gestor de conexión a SQL Server (solo lectura)"""
    
    def __init__(self):
        self.config = {
            "server": os.getenv("SQLSERVER_HOST", ""),
            "port": os.getenv("SQLSERVER_PORT", "1433"),
            "database": os.getenv("SQLSERVER_DB", "Spring_Pruebas"),
            "user": os.getenv("SQLSERVER_USER", ""),
            "password": os.getenv("SQLSERVER_PASSWORD", ""),
        }
        self.connection = None
    
    def connect(self) -> bool:
        """Establece conexión"""
        try:
            self.connection = pymssql.connect(
                server=self.config["server"],
                port=self.config["port"],
                database=self.config["database"],
                user=self.config["user"],
                password=self.config["password"],
                timeout=30,
                login_timeout=10
            )
            logger.info(f"✅ Conectado a SQL Server: {self.config['server']}")
            return True
        except Exception as e:
            logger.error(f"❌ Error conectando a SQL Server: {e}")
            return False
    
    def disconnect(self):
        """Cierra conexión"""
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
            self.connection = None
    
    def _ensure_connection(self) -> bool:
        """Asegura conexión activa"""
        if not self.connection:
            return self.connect()
        
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return True
        except:
            self.disconnect()
            return self.connect()
    
    def obtener_nuevos_empleados(self, desde_id: int) -> List[Dict[str, Any]]:
        """Obtiene empleados con ID mayor al especificado"""
        if not self._ensure_connection():
            return []
        
        empleados = []
        
        try:
            cursor = self.connection.cursor(as_dict=True)
            
            query = """
                SELECT 
                    emp.Empleado as id_externo,
                    per.Nombrecompleto as nombre,
                    per.Documento as documento,
                    per.Celular as celular,
                    puesto.Descripcion as puesto,
                    emp.FechaIngreso as fecha_ingreso
                FROM dbo.EmpleadoMast as emp 
                JOIN dbo.HR_PuestoEmpresa as puesto 
                    ON emp.CodigoCargo = puesto.CodigoPuesto 
                JOIN dbo.PersonaMast as per 
                    ON per.Persona = emp.Empleado
                WHERE emp.Empleado > %s
                ORDER BY emp.Empleado ASC
            """
            
            cursor.execute(query, (desde_id,))
            rows = cursor.fetchall()
            
            for row in rows:
                celular = row.get("celular")
                if not celular or len(str(celular).strip()) < 9:
                    logger.warning(f"⚠️ Empleado {row.get('id_externo')} sin celular, omitido")
                    continue
                
                # Limpiar celular
                celular_limpio = ''.join(filter(str.isdigit, str(celular).strip()))
                
                # Formato peruano
                if len(celular_limpio) == 9 and celular_limpio.startswith("9"):
                    celular_limpio = "51" + celular_limpio
                
                empleados.append({
                    "id_externo": row["id_externo"],
                    "nombre": str(row.get("nombre", "")).strip(),
                    "documento": str(row.get("documento", "")).strip() if row.get("documento") else None,
                    "celular": celular_limpio,
                    "puesto": str(row.get("puesto", "")).strip() if row.get("puesto") else None,
                    "fecha_ingreso": row.get("fecha_ingreso")
                })
            
            cursor.close()
            
            if empleados:
                logger.info(f"📥 {len(empleados)} empleados nuevos (ID > {desde_id})")
            
            return empleados
            
        except Exception as e:
            logger.error(f"❌ Error en query: {e}")
            self.disconnect()
            return []
    
    def obtener_max_id(self) -> Optional[int]:
        """Obtiene ID máximo actual"""
        if not self._ensure_connection():
            return None
        
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT MAX(Empleado) FROM dbo.EmpleadoMast")
            result = cursor.fetchone()
            cursor.close()
            return result[0] if result else None
        except Exception as e:
            logger.error(f"❌ Error obteniendo max ID: {e}")
            return None


# Instancia global
_sqlserver_instance = None

def get_sqlserver_db() -> SQLServerDB:
    """Retorna instancia única"""
    global _sqlserver_instance
    if _sqlserver_instance is None:
        _sqlserver_instance = SQLServerDB()
    return _sqlserver_instance