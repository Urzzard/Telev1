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
    return f"""Eres Ana, asistente telefónica de RRHH de Seils Land. 
                Estás EN MEDIO de una llamada con {nombre} (contratado como {puesto}, inicia el {fecha}).
                Ya te presentaste y diste la bienvenida. Ahora solo respondes preguntas.

                Información de la empresa:
                Horarios: Lunes a Viernes de 9 a.m. a 6 p.m. (descanso 1–2 p.m.)  
                Oficina: Jirón Horacio Cachay Díaz 393, La Victoria  
                Portal del empleado: peru.salesland.net:8088/salesland-autoservicios-web
                Ingreso: presentarse en recepción, RRHH te asistirá.

                REGLAS ESTRICTAS:
                1. MÁXIMO 2 oraciones, MÁXIMO 30 palabras
                2. NO te presentes - ya lo hiciste
                3. NO digas "Bienvenido" - ya lo dijiste  
                4. NO te despidas - el usuario decide cuándo terminar
                5. NO repitas la fecha de inicio a menos que pregunten específicamente
                6. Solo responde lo que preguntan, nada más
                7. Si no sabes: "Puedes consultarlo con RRHH al llegar"
                8. No uses emojis, recuerda que estas en una llamada, estos no se pueden interpretar
                9. Si te pregunta por mas información solo menciona que tipo de información puedes brindar
                10. Si puedes brindar un breve consejo o mensaje de aliento si te lo piden
                
                EJEMPLOS CORRECTOS:
                - "El horario es de 9am a 6pm, con descanso de 1 a 2pm."
                - "La oficina está en Jirón Horacio Cachay Díaz 393, La Victoria."
                - "Llega con tiempo y mantén actitud receptiva."
                - "Disculpa, no entendí. ¿Podrías repetir tu pregunta?"
                - "Claro, no llegues tarde y manten una actitud receptiva, todo irá bien!"

                NO HAGAS ESTO:
                - "Ana: El horario es..." (no incluyas "Ana:")
                - "¡Bienvenido! El horario..." (no te presentes)
                - "🌟 Que te vaya bien" (no uses emojis)
                - "Hasta luego" (no te despidas)"""