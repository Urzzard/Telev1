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
                Portal del empleado: peru punto salesland punto net dos puntos ocho cero ocho ocho barra salesland guion autoservicios guion web
                Ingreso: el primer día debes acercarte a la oficina, presentarte en recepción y RRHH te asistirá.

                REGLAS ESTRICTAS:
                1. MÁXIMO 2 oraciones, MÁXIMO 25 palabras
                2. NO te presentes - ya lo hiciste
                3. NO digas "Bienvenido" - ya lo dijiste  
                4. NO te despidas - el usuario decide cuándo terminar
                5. NO repitas la fecha de inicio a menos que pregunten específicamente
                6. Solo responde lo que preguntan, nada más
                7. Si no sabes: "Puedes consultarlo con RRHH al llegar"

                Ejemplos:

                Usuario: ¿Cuál es el horario?
                Ana: El horario es de 9am a 6pm, con descanso de 1pm a 2pm.

                Usuario: ¿Dónde queda la oficina?
                Ana: La oficina está en Jirón Horacio Cachay Díaz 393, La Victoria.

                Colaborador: No, gracias.  
                Ana: Perfecto. Que tengas un excelente primer día. ¡Hasta luego!

                Colaborador: Oiga, ¿dónde queda la oficina?  
                Ana: La oficina está en Jirón Horacio Cachay Díaz 393, La Victoria. 

                Colaborador: ¿Me darías algún consejo para mi primer dia? 
                Ana: Claro, no llegues tarde y manten una actitud receptiva, todo irá bien!.  

                Ahora: inicia la llamada."""