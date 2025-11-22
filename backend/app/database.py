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

    def get_employee_by_phone(self, phone: str):
        """
        Busca un empleado por teléfono.
        Normaliza el teléfono quitando espacios y símbolos.
        """
        # Limpieza básica del número entrante (ej: +51 999... -> 51999...)
        clean_phone = phone.replace("+", "").replace(" ", "").strip()
        
        if self.db_type == "csv":
            return self._get_from_csv(clean_phone)
        elif self.db_type == "mssql":
            return self._get_from_sql(clean_phone)
        else:
            logger.error("Modo de base de datos no soportado")
            return None

    def _get_from_csv(self, phone):
        try:
            # Leemos el CSV
            if not os.path.exists(self.csv_path):
                logger.error(f"❌ No se encuentra el archivo CSV en {self.csv_path}")
                return None

            df = pd.read_csv(self.csv_path, dtype=str) # Leer todo como string para no perder ceros
            
            # Limpiar columna telefono del CSV
            # Asumimos que la columna se llama 'telefono'
            if 'telefono' not in df.columns:
                logger.error("❌ El CSV no tiene columna 'telefono'")
                return None

            # Búsqueda exacta (puedes mejorarla para buscar 'contains')
            # Normalizamos la columna del CSV también
            df['telefono_clean'] = df['telefono'].astype(str).str.replace("+", "").str.replace(" ", "").str.strip()
            
            resultado = df[df['telefono_clean'] == phone]
            
            if not resultado.empty:
                # Convertimos la fila encontrada a un diccionario
                empleado = resultado.iloc[0].to_dict()
                logger.info(f"✅ Empleado encontrado en CSV: {empleado.get('nombre', 'Sin nombre')}")
                return empleado
            
            logger.warning(f"⚠️ Teléfono {phone} no encontrado en CSV")
            return None

        except Exception as e:
            logger.error(f"❌ Error leyendo CSV: {e}")
            return None

    def _get_from_sql(self, phone):
        # AQUI IMPLEMENTAREMOS SQL SERVER LUEGO
        # Usaremos SQLAlchemy
        logger.info("Consulta SQL aún no implementada")
        return None