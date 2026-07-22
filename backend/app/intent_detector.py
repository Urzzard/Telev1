"""
Detector de intenciones - Solo valida si la pregunta es sobre temas permitidos.
NO genera respuestas, solo filtra.
"""
import logging
from typing import Optional

logger = logging.getLogger("IntentDetector")


# Keywords de temas PERMITIDOS
KEYWORDS_PERMITIDOS = {
    "horario": ["horario", "horarios", "hora", "entrada", "salida", "turno", "jornada"],
    "ubicacion": ["dirección", "direccion", "dónde", "donde", "ubicación", "ubicacion", 
                  "oficina", "llegar", "queda", "cómo llego", "como llego"],
    "portal": ["portal", "web", "página", "pagina", "sitio", "plataforma", "sistema", "intranet"],
    "primer_dia": ["primer día", "primer dia", "primero", "llegar", "presentarme", 
                   "qué hago", "que hago", "documentos", "llevar", "traer"],
    "consejos": ["consejo", "consejos", "recomendación", "recomendacion", "tip", "tips", 
                 "sugerencia", "ayuda", "nervioso", "preparar"],
    "puesto": ["puesto", "cargo", "posición", "posicion", "rol", "trabajo"],
    "fecha": ["fecha", "cuándo empiezo", "cuando empiezo", "inicio", "comienzo"],
    "contacto": ["contacto", "comunicarme", "llamar", "preguntas después", "dudas después"],
}

# Keywords de temas RESTRINGIDOS
KEYWORDS_RESTRINGIDOS = {
    "salario": ["salario", "sueldo", "pago", "ganar", "remuneración", "remuneracion", 
                "cuánto pagan", "cuanto pagan", "dinero", "plata"],
    "beneficios": ["beneficio", "beneficios", "seguro", "eps", "afp", "pensión", "pension",
                   "gratificación", "gratificacion", "bono", "bonos"],
    "vacaciones": ["vacaciones", "días libres", "dias libres", "permiso", "permisos", 
                   "descanso médico", "licencia"],
    "contrato": ["contrato", "tipo de contrato", "duración", "duracion", "renovación", 
                 "renovacion", "indefinido", "temporal", "plazo"],
    "otros_empleados": ["compañeros", "companeros", "otros", "alguien más", "equipo", 
                        "gerente", "quien más"],
}


class IntentDetector:
    """Detector que valida si las preguntas son sobre temas permitidos"""
    
    def __init__(self):
        self.preguntas_realizadas: list[str] = []
    
    def es_tema_permitido(self, texto: str) -> bool:
        """Verifica si la pregunta es sobre un tema permitido"""
        if not texto or len(texto) < 3:
            return True  # Dar beneficio de la duda
        
        texto_lower = texto.lower()
        
        # Primero verificar si es tema restringido
        for categoria, keywords in KEYWORDS_RESTRINGIDOS.items():
            for kw in keywords:
                if kw in texto_lower:
                    logger.info(f"🚫 Tema restringido detectado: {categoria} ('{kw}')")
                    return False
        
        # Si no es restringido, es permitido
        return True
    
    def detectar_categoria(self, texto: str) -> Optional[str]:
        """Detecta la categoría de la pregunta (para logging)"""
        if not texto:
            return None
        
        texto_lower = texto.lower()
        
        for categoria, keywords in KEYWORDS_PERMITIDOS.items():
            for kw in keywords:
                if kw in texto_lower:
                    return categoria
        
        return "general"
    
    def registrar_pregunta(self, texto: str):
        """Registra una pregunta realizada"""
        self.preguntas_realizadas.append(texto)
    
    def limpiar(self):
        """Limpia estado para nueva llamada"""
        self.preguntas_realizadas = []


