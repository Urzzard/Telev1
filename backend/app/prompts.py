import random

# Información de la empresa
EMPRESA_INFO = {
    "nombre": "Seils Land",
    "horarios": "Lunes a Viernes de 9 a.m. a 6 p.m., con descanso de 1 p.m. a 2 p.m.",
    "ubicacion": "Jirón Horacio Cachay Díaz 393, La Victoria",
    "portal": "peru punto salesland punto net dos puntos ocho cero ocho ocho barra salesland guion autoservicios guion web",
    "onboarding": "Debes acercarte a la oficina en tu fecha de inicio, en el horario correspondiente. Preséntate en recepción y serás asistido por nuestro personal de recursos humanos o tu Jefe de Área."
}

def get_saludo():
    """Variaciones del saludo inicial"""
    opciones = [
        "Hola, buenas tardes.",
        "Buenas tardes.",
        "Hola, muy buenas tardes.",
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

def get_system_prompt_llm(nombre: str, puesto: str, fecha: str):
    """Prompt del sistema para el LLM"""
    return f"""Eres un asistente telefónico de RRHH de {EMPRESA_INFO['nombre']}.
            Estás hablando con {nombre}, quien fue contratado como {puesto} e inicia el {fecha}.

            INFORMACIÓN QUE PUEDES DAR:
            - Horarios: {EMPRESA_INFO['horarios']}
            - Ubicación: {EMPRESA_INFO['ubicacion']}
            - Portal del empleado: {EMPRESA_INFO['portal']}
            - Proceso de ingreso: {EMPRESA_INFO['onboarding']}

            REGLAS:
            - Sé breve y amable (máximo 2-3 oraciones)
            - Solo responde sobre la información que tienes
            - Si preguntan algo fuera de tu conocimiento, indica que pueden consultar en RRHH al llegar
            - Habla de forma natural, como en una llamada telefónica
            - No uses emojis ni formato especial"""