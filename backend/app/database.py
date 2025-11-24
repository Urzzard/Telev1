import pandas as pd
import os
import logging

# Configuración de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Database")

class EmployeeRepository:
    def __init__(self):
        self.db_type = os.getenv("DB_TYPE", "csv").lower()
        self.csv_path = "/app/data/empleados.csv"
        self.sql_connection = os.getenv("DB_CONNECTION_STRING")
        
        logger.info(f"📂 Inicializando repositorio de empleados. Modo: {self.db_type.upper()}")

    def get_employee_by_id(self, employee_id: int):
        """
        Busca un empleado por ID.
        """
        if self.db_type == "csv":
            return self._get_by_id_from_csv(employee_id)
        elif self.db_type == "mssql":
            return self._get_by_id_from_sql(employee_id)
        else:
            logger.error("Modo de base de datos no soportado")
            return None

    def _get_by_id_from_csv(self, employee_id):
        try:
            if not os.path.exists(self.csv_path):
                logger.error(f"❌ No se encuentra el archivo CSV en {self.csv_path}")
                return None

            df = pd.read_csv(self.csv_path, dtype=str)
            
            if 'id' not in df.columns:
                logger.error("❌ El CSV no tiene columna 'id'")
                return None

            # Buscar por ID
            resultado = df[df['id'] == str(employee_id)]
            
            if not resultado.empty:
                empleado = resultado.iloc[0].to_dict()
                logger.info(f"✅ Empleado encontrado: {empleado.get('nombre', 'Sin nombre')}")
                return empleado
            
            logger.warning(f"⚠️ ID {employee_id} no encontrado en CSV")
            return None

        except Exception as e:
            logger.error(f"❌ Error leyendo CSV: {e}")
            return None
        
        
    def _get_from_sql(self, phone):
        # AQUI IMPLEMENTAREMOS SQL SERVER LUEGO
        # Usaremos SQLAlchemy
        logger.info("Consulta SQL aún no implementada")
        return None