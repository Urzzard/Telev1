from enum import Enum

class CallState(Enum):
    DETECTAR_BUZON = "detectar_buzon"
    PRESENTACION = "presentacion"
    ESPERAR_CONFIRMACION = "esperar_confirmacion"
    BIENVENIDA = "bienvenida"
    ESPERAR_DUDAS = "esperar_dudas"
    RESPONDER = "responder"
    DESPEDIDA_OK = "despedida_ok"
    DESPEDIDA_ERROR = "despedida_error"
    FINALIZADO = "finalizado"