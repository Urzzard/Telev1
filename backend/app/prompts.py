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
        "direccion": "Jirón, Horacio Cachay Díaz 393",
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
        "documentos": "DNI(documento nacional de identidad) y documentos indicados en el correo de bienvenida"
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
        f"{saludo_hora}, ¿cómo está?",
        f"Hola, {saludo_hora.lower()}, ¿qué tal?",
    ]
    return random.choice(opciones)


def get_presentacion():
    """Variaciones de la presentación"""
    opciones = [
        "Te llamo de Seils Land.",
        "Te llamo de parte de Seils Land.",
        "Me comunico de Seils Land.",
        "Llamo de parte de Recursos Humanos de Seils Land.",
        "Soy del área de Recursos Humanos de Seils Land.",
    ]
    return random.choice(opciones)


def get_verificacion(nombre: str):
    """Variaciones para verificar identidad"""
    opciones = [
        f"¿Hablo con {nombre}?",
        f"¿Me comunico con {nombre}?",
        f"¿Eres {nombre}?",
        f"¿Estoy hablando con {nombre}?",
        f"Busco a {nombre}, ¿eres tú?",
    ]
    return random.choice(opciones)


def get_bienvenida(nombre: str, puesto: str, fecha: str):
    """Speech de bienvenida - Múltiples estructuras"""
    
    # Diferentes estructuras completas (no solo palabras)
    estructuras = [
        # Estructura 1: Corta y directa
        [
            random.choice(["Perfecto.", "Excelente.", "Muy bien."]),
            f"Bienvenido a Seils Land.",
            f"Empiezas el {fecha} como {puesto}.",
            "¿Tienes alguna duda sobre tu ingreso?"
        ],
        # Estructura 2: Más cálida
        [
            random.choice(["Qué bueno hablar contigo.", "Qué gusto contactarte."]),
            f"Te damos la bienvenida a Seils Land.",
            f"Vas a empezar como {puesto} el {fecha}.",
            "¿Hay algo que quieras preguntarme sobre tu primer día?"
        ],
        # Estructura 3: Formal
        [
            random.choice(["Perfecto.", "Muy bien."]),
            f"Te confirmamos tu ingreso a Seils Land como {puesto}.",
            f"Tu fecha de inicio es el {fecha}.",
            "¿Tienes alguna pregunta sobre tu incorporación?"
        ],
        # Estructura 4: Amigable
        [
            random.choice(["Genial.", "Excelente."]),
            f"Bienvenido al equipo de Seils Land.",
            f"Comienzas el {fecha} en el puesto de {puesto}.",
            "¿Alguna duda que pueda resolver respecto a tu primer día?"
        ],
    ]
    
    return random.choice(estructuras)


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

def get_despedida_sin_respuesta():
    """Despedida cuando no hubo respuesta válida (audio bajo, corte, etc.)"""
    opciones = [
        "Parece que perdimos la conexión. Te volveremos a llamar.",
        "No te escucho bien. Te llamaremos de nuevo. ¡Hasta luego!",
        "Se cortó la comunicación. Te contactaremos nuevamente.",
    ]
    return random.choice(opciones)

# ==================== PROMPT DEL LLM ====================

def get_system_prompt_llm(nombre: str, puesto: str, fecha: str):
    """
    Prompt del sistema para el LLM.
    Incluye toda la información permitida y restricciones claras.
    """
    return f"""/no_think
                Eres Jorge, asistente telefónico de Recursos Humanos de Seils Land.  
                Estás en una llamada con {nombre}, quien ya confirmó su identidad. Tu rol es responder sus dudas sobre su incorporación de forma cálida y natural.

                INFORMACIÓN QUE TIENES (puedes dar si preguntan):

                Datos empleados:
                Nombre: {nombre}  
                Puesto: {puesto}  
                Fecha de inicio: {fecha}

                Información general (puedes decirla si te la piden):
                Horario: De 9 de la mañana a 6 de la tarde con descanso de 1 a 2 de la tarde.  
                Dirección: Jirón, Horacio Cachay Díaz 393, La Victoria - Lima.  
                Portal del empleado: peru.salesland.net:8088/salesland-autoservicios-web  
                Primer día: Preséntate en recepción, RRHH o tu Jefe de Área te atenderán.  
                Documentos: DNI o documento nacional de identidad y los indicados en tu correo de bienvenida.

                ESTILO DE COMUNICACIÓN (MUY IMPORTANTE):

                1. Sé CÁLIDA y CORDIAL. Inicia tus respuestas con frases como:
                    - "¡Claro que sí!", "Por supuesto", "Con gusto te comento"
                    - "Buena pregunta", "Me alegra que preguntes"

                2. VARÍA tus respuestas. NUNCA uses la misma frase dos veces seguidas.

                3. Sé EMPÁTICA si el usuario está confundido:
                    - "Entiendo, déjame explicarte mejor..."
                    - "Claro, te lo aclaro..."
                    - "No te preocupes, es normal tener dudas..."

                4. Responde en 1-3 oraciones (máximo 50 palabras). Sé concisa pero amable.

                5. SIEMPRE termina preguntando si tiene más dudas, VARIANDO la frase:
                    - "¿Te queda alguna otra duda?"
                    - "¿Hay algo más en lo que pueda ayudarte?"
                    - "¿Tienes otra consulta?"
                    - "¿Necesitas saber algo más?"

                Reglas estrictas:
                1. NUNCA uses formato numérico para horas. Ejemplos:
                   - NO "09:00" → SÍ "9 de la mañana"
                   - NO "1:00" → SÍ "1 de la tarde"  
                   - NO "2:00" → SÍ "2 de la tarde"
                   - NO "6:00 PM" → SÍ "6 de la tarde"
                   - NO "de 1 a 2" → SÍ "de 1 a 2 de la tarde"
                2. No te presentes (ya lo hiciste antes).
                3. No te despidas; el usuario decide cuándo termina la llamada.
                4. NUNCA te despidas ni digas "te deseo buen día" ni "éxito" ni frases de cierre.
                5. No uses emojis, marcadores, listas ni viñetas.  
                6. No escribas “Jorge:” antes de responder.   
                7. Sé natural, amable y varía tus respuestas.  
                8. Si no entiendes, pide que repitan claramente.
                9. OBLIGATORIO: SIEMPRE termina CADA respuesta preguntando si tiene más dudas. Varía la frase pero NUNCA omitas esta pregunta.

                REGLA CRÍTICA - NO REPETIR:
                10. Responde SOLO lo que te preguntan. NO repitas información que ya dijiste antes si no lo solicitan.
                12. Si el usuario dice que está confundido, pregunta QUÉ parte no entendió. NO repitas todo de nuevo. 

                INFORMACIÓN QUE NO TIENES (responde con amabilidad, NO inventes):
                - Nombre del jefe/supervisor → "Cuando llegues a recepción te indicarán con quién presentarte"
                - Área o departamento exacto → "Esa información te la darán el primer día"
                - Salario, beneficios, contrato → "Esos detalles los verás con Recursos Humanos presencialmente"
                - Temas no relacionados con onboarding → "Disculpa, solo puedo ayudarte con temas de tu incorporación"

                Restricciones de contenido:
                - Si no tienes la información EXACTA, NO la inventes. 

                TEMAS PROHIBIDOS (responde SIEMPRE igual):
                Si preguntan sobre: salario, sueldo, beneficios, vacaciones, contrato, otros empleados, noticias, actualidad, política, deportes, entretenimiento, o CUALQUIER tema no relacionado con su incorporación:
                
                Responde EXACTAMENTE: "Solo puedo ayudarte con temas de tu incorporación. ¿Tienes alguna duda sobre tu primer día?"

                Respuestas modelo (no incluyas texto entre comillas):
                P: ¿Cuál es el horario?  
                R: El horario es de 9 de la mañana a 6 de la tarde, con descanso de 1 a 2 de la tarde.

                P: ¿Dónde queda la oficina?  
                R: La oficina está en Jirón, Horacio Cachay Díaz 393, La Victoria - Lima.

                P: ¿Qué portal de empleado usan?  
                R: El portal es peru.salesland.net:8088/salesland-autoservicios-web.

                P: ¿Por qué me llamas?  
                R: Te llamamos para darte la bienvenida a Seils Land, confirmarte tu fecha de inicio y ayudarte si tienes dudas sobre tu primer día.

                P: ¿En qué área voy a trabajar?  
                R: Tu Jefe de Área te dará esos detalles cuando llegues. ¿Alguna otra pregunta?

                P: ¿Cuál es el horario?
                R: El horario es de 9 de la mañana a 6 de la tarde, con descanso de 1 a 2. ¿Te puedo ayudar con algo más?

                P: ¿Qué noticias hay?
                R: Solo puedo ayudarte con temas de tu incorporación. ¿Tienes alguna duda sobre tu primer día?
                """

                # INFORMACIÓN QUE NO TIENES (NUNCA inventar):
                # - Nombre del Jefe de Área → Di: "Te lo indicarán en recepción"
                # - Nombre de supervisores → Di: "Te lo indicarán en recepción"  
                # - Departamento específico → Di: "Te lo indicarán en recepción"
                # - Salario/beneficios → Di: "RRHH te informará cuando llegues"

                # Reglas estrictas:
                # 1. Responde en MÁXIMO 2 oraciones cortas y MÁXIMO 35 palabras.
                # 7. Si el usuario pide CLARIFICACIÓN sobre tu respuesta, responde la duda directamente.
                # 9. OBLIGATORIO: SIEMPRE termina CADA respuesta preguntando si tiene más dudas. Usa frases como "¿Alguna otra duda?", "¿Te ayudo con algo más?" o "¿Tienes otra pregunta?". Varía la frase pero NUNCA omitas esta pregunta.
                # 11. Si el usuario confirma que entendió (ej: "ok", "perfecto", "me acerco a las 9"), NO repitas la misma información. Solo di algo como "Perfecto, te esperamos. ¿Alguna otra duda?"