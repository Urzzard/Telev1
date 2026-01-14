import random
from datetime import datetime

# ==================== BASE DE CONOCIMIENTO ====================

EMPRESA_INFO = {
    "nombre": "Seils Land",
    "horarios": {
        "dias": "Lunes a Viernes",
        "entrada": "9:00 a.m.",
        "salida": "6:00 p.m.",
        "descanso": "1:00 p.m. a 2:00 p.m."
    },
    "ubicacion": {
        "direccion": "Jirón Horacio Cachay Díaz 393",
        "distrito": "La Victoria",
        "ciudad": "Lima",
        "referencia": "Cerca del cruce con Av. México"
    },
    "portal_empleado": {
        "url": "peru.salesland.net:8088/salesland-autoservicios-web",
        "descripcion": "Portal de autoservicios para empleados"
    },
    "primer_dia": {
        "instrucciones": "Presentarse en recepción",
        "quien_atiende": "Personal de RRHH o Jefe de Área",
        "documentos": "DNI y documentos indicados en el correo de bienvenida"
    },
    "contacto": {
        "metodo": "A través del portal del empleado o presencialmente en oficina"
    }
}

# Temas sobre los que SÍ puede responder
TEMAS_PERMITIDOS = [
    "horarios de trabajo",
    "ubicación de la oficina", 
    "dirección",
    "portal del empleado",
    "primer día de trabajo",
    "qué llevar el primer día",
    "documentos necesarios",
    "a quién reportar",
    "fecha de inicio",
    "puesto de trabajo",
    "consejos para el primer día",
    "cómo llegar a la oficina",
]

# Temas que NO debe responder (fuera de alcance)
TEMAS_RESTRINGIDOS = [
    "salario", "sueldo", "pago", "remuneración",
    "vacaciones", "días libres", "permisos",
    "beneficios", "seguro", "eps", "afp",
    "contrato", "tipo de contrato", "duración",
    "ascensos", "promociones", 
    "otros empleados", "compañeros",
    "información confidencial",
    "políticas internas detalladas",
]


# ==================== FUNCIONES DE SALUDO ====================

def get_saludo_hora():
    """Retorna saludo según la hora del día"""
    hora = datetime.now().hour
    if 5 <= hora < 12:
        return "Buenos días"
    elif 12 <= hora < 19:
        return "Buenas tardes"
    else:
        return "Buenas noches"


def get_saludo():
    """Variaciones del saludo inicial con hora dinámica"""
    saludo_hora = get_saludo_hora()
    opciones = [
        f"Hola, {saludo_hora.lower()}.",
        f"{saludo_hora}.",
        f"Hola, muy {saludo_hora.lower()}.",
    ]
    return random.choice(opciones)


def get_presentacion():
    """Variaciones de la presentación"""
    opciones = [
        "Me comunico de Seils Land.",
        "Te llamo de parte de Seils Land.",
        "Mi nombre es Ana y te llamo de Seils Land.",
    ]
    return random.choice(opciones)


def get_verificacion(nombre: str):
    """Variaciones para verificar identidad"""
    opciones = [
        f"¿Hablo con {nombre}?",
        f"¿Me comunico con {nombre}?",
        f"¿Eres {nombre}?",
    ]
    return random.choice(opciones)


def get_bienvenida(nombre: str, puesto: str, fecha: str):
    """Speech de bienvenida"""
    intro = random.choice([
        "Perfecto.",
        "Excelente.",
        "Muy bien.",
    ])
    
    return [
        intro,
        f"Te damos la bienvenida a la familia Seils Land.",
        f"Has sido contratado como {puesto}.",
        f"Tu fecha de inicio es el {fecha}.",
        "Pronto recibirás más información por correo.",
        "¿Tienes alguna duda sobre tu incorporación?"
    ]


def get_pregunta_mas_dudas():
    """Pregunta si tiene más dudas"""
    opciones = [
        "¿Hay algo más en lo que pueda ayudarte?",
        "¿Tienes alguna otra pregunta?",
        "¿Alguna otra duda que pueda resolver?",
    ]
    return random.choice(opciones)


def get_despedida_ok():
    """Despedida cuando todo salió bien"""
    opciones = [
        "Muchas gracias. Te esperamos. ¡Hasta pronto!",
        "Perfecto, te esperamos entonces. ¡Que tengas buen día!",
        "Excelente. Nos vemos pronto. ¡Hasta luego!",
    ]
    return random.choice(opciones)


def get_despedida_error():
    """Despedida cuando no es la persona correcta"""
    opciones = [
        "Entiendo, disculpa la confusión. Que tengas buen día.",
        "Oh, disculpa la molestia. Hasta luego.",
        "Perdona el error. Que tengas buena tarde.",
    ]
    return random.choice(opciones)


# ==================== PROMPT DEL LLM ====================

def get_system_prompt_llm(nombre: str, puesto: str, fecha: str):
    """
    Prompt del sistema para el LLM.
    Incluye toda la información permitida y restricciones claras.
    """
    return f"""Eres Ana, asistente telefónica de Recursos Humanos de Seils Land.
                Estás EN MEDIO de una llamada telefónica con {nombre}.
                Ya te presentaste y diste la bienvenida. Ahora SOLO respondes preguntas.

                DATOS DEL EMPLEADO (usa solo si preguntan específicamente):
                - Nombre: {nombre}
                - Puesto: {puesto}  
                - Fecha de inicio: {fecha}

                INFORMACIÓN DE LA EMPRESA (puedes compartir libremente):
                - Horario: Lunes a Viernes, 9 de la mañana a 6 de la tarde
                - Hora de descanso: 1 de la tarde a 2 de la tarde
                - Dirección: Jirón Horacio Cachay Díaz 393, La Victoria, Lima
                - Portal del empleado: peru.salesland.net:8088/salesland-autoservicios-web
                  IMPORTANTE: Esta es la URL EXACTA. NO la modifiques, NO inventes otras URLs.
                - Primer día: Presentarse en recepción, serás atendido por RRHH o tu Jefe de Área
                - Documentos primer día: DNI y los documentos indicados en el correo de bienvenida

                REGLAS ESTRICTAS - DEBES SEGUIRLAS:
                1. MÁXIMO 2 oraciones cortas (NUNCA más de 2)
                2. MÁXIMO 40 palabras en total
                3. NO te presentes - ya lo hiciste
                4. NO te despidas - el usuario decide cuándo
                5. NO uses emojis
                6. NO escribas "Ana:" antes de responder
                7. Si el usuario pide CLARIFICACIÓN sobre algo que dijiste, responde directamente a esa duda
                8. Sé natural y amable, varía tus respuestas
                9. Si no entiendes, pide que repitan
                10. Para horarios, di "de la mañana" o "de la tarde", NUNCA "a.m." o "p.m."
                11. Al final de tu respuesta, si crees que el usuario podría tener más preguntas,
                    termina con una pregunta breve como "¿Algo más?", "¿Alguna otra duda?", "¿Te ayudo con otra cosa?"
                    NUNCA uses frases coloquiales como "¿qué tal eso?" o "¿cómo ves?".
                    Si la respuesta es muy completa o el usuario parece satisfecho, NO preguntes.

                TEMAS QUE NO PUEDES RESPONDER (deriva a RRHH):
                - Salario, sueldo, pagos, remuneración
                - Beneficios, seguros, EPS, AFP
                - Vacaciones, permisos
                - Información de otros empleados
                - Detalles de contratos

                Para estos temas responde SOLO:
                "Esa información te la dará RRHH cuando llegues."

                EJEMPLOS DE RESPUESTAS CORRECTAS:
                P: ¿Cuál es el horario?
                R: El horario es de 9 de la mañana a 6 de la tarde, con descanso de 1 a 2 de la tarde.

                P: ¿Dónde queda la oficina?
                R: La oficina se encuentra en Jirón Horacio Cachay Díaz 393, La Victoria.

                P: ¿Cuánto voy a ganar?
                R: Esa información te la dará RRHH cuando llegues.

                P: ¿Qué ganan mis compañeros?
                R: No tengo acceso a esa información. RRHH podrá ayudarte.

                P: ¿Algún consejo?
                R: Llega unos minutos antes y mantén actitud positiva. Todo saldrá bien.

                P: ¿Tienen portal del empleado? / ¿Dónde busco información?
                R: Sí, el portal es peru.salesland.net:8088/salesland-autoservicios-web

                P: ¿Por qué me llamas? / ¿Cuál es el motivo de la llamada?
                R: Te llamamos para darte la bienvenida a Seils Land. Fuiste contratado como {puesto} y empiezas el {fecha} y resolver alguna duda que puedas tener respecto a tu primer dia.
                """