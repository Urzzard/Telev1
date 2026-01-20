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
                        "jefe", "gerente", "quien más"],
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


    def es_respuesta_incoherente(self, texto: str) -> bool:
        """
        Detecta si la respuesta es completamente fuera de contexto.
        Retorna True si parece ser ruido/mala transcripción.
        """
        if not texto or len(texto) < 3:
            return True
        
        texto_lower = texto.lower()
        
        # Temas completamente fuera de contexto para una llamada de onboarding
        temas_incoherentes = [
            # Entretenimiento
            "jugar", "juego", "videojuego", "película", "pelicula", "serie", "netflix",
            "fútbol", "futbol", "partido", "gol", "deporte",
            # Comida casual
            "pizza", "hamburguesa", "cerveza", "trago", "fiesta",
            # Otros
            "novio", "novia", "amor", "beso", "bailar",
            "clima", "lluvia", "sol",
            # Frases sin sentido común en transcripciones malas
            "subtítulos", "suscríbete", "like", "comentar",
        ]
        
        # Si contiene tema incoherente Y NO contiene palabras de trabajo
        palabras_trabajo = [
            "horario", "oficina", "trabajo", "puesto", "fecha", "inicio",
            "jefe", "área", "dirección", "portal", "documento", "dni",
            "sí", "no", "gracias", "perfecto", "entiendo", "claro",
            "duda", "pregunta", "información", "ayuda",
        ]
        
        tiene_incoherente = any(t in texto_lower for t in temas_incoherentes)
        tiene_trabajo = any(p in texto_lower for p in palabras_trabajo)
        
        # Es incoherente si tiene tema raro Y no tiene nada de trabajo
        if tiene_incoherente and not tiene_trabajo:
            return True
        
        return False

    def es_pregunta_fuera_de_tema(self, texto: str) -> bool:
        """
        Detecta si la pregunta NO tiene nada que ver con onboarding.
        Retorna True si es completamente fuera de tema.
        """
        if not texto or len(texto) < 5:
            return False
        
        texto_lower = texto.lower()
        
        # Temas de onboarding (permitidos)
        temas_onboarding = [
            "horario", "hora", "entrada", "salida", "turno",
            "dirección", "direccion", "oficina", "ubicación", "ubicacion", "llegar", "queda",
            "portal", "web", "página", "sistema", "intranet",
            "primer día", "primer dia", "primero", "presentarme", "documentos", "llevar",
            "jefe", "área", "area", "supervisor", "reportar",
            "puesto", "cargo", "trabajo", "posición",
            "fecha", "inicio", "comienzo", "empiezo",
            "contacto", "comunicar", "llamar",
            "rrhh", "recursos humanos",
            "dni", "documento",
            # Confirmaciones/despedidas (permitidas)
            "gracias", "ok", "perfecto", "entiendo", "claro", "bien",
            "no", "nada más", "eso es todo", "chau", "adiós",
        ]
        
        # Temas PROHIBIDOS (fuera de alcance total)
        temas_prohibidos = [
            # Noticias/actualidad
            "actualidad", "noticia", "noticias", "política", "politica",
            "elecciones", "presidente", "gobierno", "guerra",
            # Entretenimiento
            "película", "pelicula", "serie", "música", "musica", "canción",
            "juego", "videojuego", "fútbol", "futbol", "deporte",
            # Conocimiento general
            "historia", "geografía", "ciencia", "matemática",
            "receta", "cocina", "comida",
            # Tecnología no relacionada
            "programar", "código", "python", "inteligencia artificial",
            "chatgpt", "openai", "google",
            # Opiniones
            "opinas", "crees", "piensas", "mejor", "peor",
            # Otros
            "chiste", "cuéntame", "háblame de", "qué sabes de",
            "clima", "tiempo", "temperatura",
        ]
        
        # Verificar si tiene algún tema de onboarding
        tiene_tema_onboarding = any(t in texto_lower for t in temas_onboarding)
        
        # Verificar si tiene tema prohibido
        tiene_tema_prohibido = any(t in texto_lower for t in temas_prohibidos)
        
        # Es fuera de tema si:
        # 1. Tiene tema prohibido explícito, O
        # 2. No tiene NADA de onboarding Y es una pregunta (tiene ?)
        if tiene_tema_prohibido:
            return True
        
        if not tiene_tema_onboarding and "?" in texto:
            # Pregunta sin relación a onboarding
            return True
        
        return False