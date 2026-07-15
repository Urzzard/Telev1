#!/usr/bin/env python3
"""
Verifica que el vLLM soporta `guided_json` (struct completo del turn-handler), no solo `guided_choice`.
Es el último riesgo técnico antes de construir el manejador de turno. Ver docs/ARQUITECTURA_CEREBRO_LLM.md

Prueba el esquema {intent, respuesta, terminar} en la fase de DUDAS con frases representativas.
Comprueba: (1) que vLLM acepte guided_json, (2) que la salida sea JSON válido del esquema,
(3) que el 2B llene intent/respuesta/terminar con sentido.

Uso (LLM arriba):
    python3 scripts/test_guided_json.py
    VLLM_URL=http://172.17.0.1:8100 python3 scripts/test_guided_json.py   # si localhost no llega

Solo stdlib. No instala nada.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8100").rstrip("/")
MODEL = os.getenv("VLLM_MODEL")
ENDPOINT = VLLM_URL + "/v1/chat/completions"
MODELS_ENDPOINT = VLLM_URL + "/v1/models"

NOMBRE = "Manuel"

# Esquema del turn-handler para la fase de DUDAS.
TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["PREGUNTA", "DESPEDIDA", "FUERA_DE_TEMA", "CALIBRACION", "ACK"],
        },
        "respuesta": {"type": "string"},
        "terminar": {"type": "boolean"},
    },
    "required": ["intent", "respuesta", "terminar"],
}

SYS_DUDAS = f"""Eres Jorge, asistente telefónico de Recursos Humanos de Salesland. {NOMBRE} ya confirmó su
identidad y está en la fase de DUDAS sobre su incorporación.

CONOCIMIENTO (solo esto; si no lo tienes, no lo inventes):
- Horario: de 9 de la mañana a 6 de la tarde, con descanso de 1 a 2 de la tarde, de lunes a viernes.
- Dirección: Jirón Horacio Cachay Díaz 393, La Victoria, Lima.
- Portal del empleado: peru.salesland.net:8088/salesland-autoservicios-web
- Primer día: preséntate en recepción; Recursos Humanos o tu jefe de área te atenderán.
- Documentos: DNI y los indicados en tu correo de bienvenida.

Por CADA mensaje del usuario devuelve un JSON con:
- intent: PREGUNTA (pide info de su incorporación) | DESPEDIDA (quiere terminar la llamada) |
  FUERA_DE_TEMA (algo no relacionado, o salario/vacaciones/contrato) | CALIBRACION (comenta el audio/conexión) |
  ACK (solo reconoce o agradece).
- respuesta: lo que le hablas, cálido, 1-2 oraciones. Cadena vacía "" si es DESPEDIDA o ACK y no hace falta hablar.
- terminar: true SOLO si el intent es DESPEDIDA; si no, false.

No uses horas en formato numérico (di "9 de la mañana", no "9:00")."""

TESTS = [
    ("¿A qué hora entro a trabajar?", "PREGUNTA"),
    ("Oye, y ¿dónde queda la oficina?", "PREGUNTA"),
    ("Ya, eso sería todo, muchas gracias.", "DESPEDIDA"),
    ("¿Cuánto voy a ganar?", "FUERA_DE_TEMA"),
    ("¿Me escuchas? Se está cortando.", "CALIBRACION"),
    ("Ah, ok, perfecto.", "ACK"),
]


def discover_model():
    try:
        with urllib.request.urlopen(MODELS_ENDPOINT, timeout=8) as r:
            return json.loads(r.read().decode())["data"][0]["id"]
    except Exception as e:
        print(f"⚠️  No pude autodetectar el modelo ({e}). Usa VLLM_MODEL=... explícito.")
        sys.exit(1)


def _post(body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=data, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read().decode("utf-8"))
    dt = (time.time() - t0) * 1000.0
    return resp["choices"][0]["message"]["content"].strip(), dt


def main():
    global MODEL
    if not MODEL:
        MODEL = discover_model()

    print("=" * 70)
    print("  TEST guided_json — struct del turn-handler {intent, respuesta, terminar}")
    print("=" * 70)
    print(f"  vLLM   : {ENDPOINT}")
    print(f"  Modelo : {MODEL}")
    print("=" * 70)

    ok_parse, ok_intent, total = 0, 0, 0
    lat = []
    guided_ok = True

    for frase, exp in TESTS:
        body = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYS_DUDAS},
                {"role": "user", "content": frase},
            ],
            "max_tokens": 200,
            "temperature": 0.3,
            "guided_json": TURN_SCHEMA,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            raw, dt = _post(body)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:200]
            print(f"\n❌ vLLM rechazó guided_json (HTTP {e.code}): {detail}")
            print("   → tu vLLM NO soporta guided_json. Habría que usar guided_choice + generación aparte.")
            guided_ok = False
            break
        except Exception as e:
            print(f"\n❌ Error de conexión: {e}\n   Prueba VLLM_URL=http://172.17.0.1:8100")
            sys.exit(1)

        lat.append(dt)
        total += 1

        # ¿Parsea como JSON del esquema?
        try:
            obj = json.loads(raw)
            campos_ok = (
                isinstance(obj.get("intent"), str)
                and isinstance(obj.get("respuesta"), str)
                and isinstance(obj.get("terminar"), bool)
                and obj["intent"] in TURN_SCHEMA["properties"]["intent"]["enum"]
            )
        except Exception:
            obj, campos_ok = None, False

        if campos_ok:
            ok_parse += 1
            intent_ok = obj["intent"] == exp
            ok_intent += intent_ok
            marca = "✓" if intent_ok else "✗"
            print(f"\n  {marca} \"{frase}\"  (esperaba {exp})  {dt:.0f}ms")
            print(f"      intent={obj['intent']}  terminar={obj['terminar']}")
            print(f"      respuesta='{obj['respuesta'][:90]}'")
        else:
            print(f"\n  ⚠️  \"{frase}\" → JSON inválido o fuera de esquema. Crudo: {raw[:120]}")

    if guided_ok and total:
        print("\n" + "=" * 70)
        print(f"  guided_json SOPORTADO: ✅")
        print(f"  JSON válido del esquema: {ok_parse}/{total}")
        print(f"  intent correcto:        {ok_intent}/{total}")
        print(f"  Latencia media: {sum(lat)/len(lat):.0f}ms")
        print("=" * 70)
        if ok_parse == total:
            print("  🎯 El struct completo funciona → luz verde para construir manejar_turno().")
        else:
            print("  ⚠️  Algún JSON no cumplió el esquema — revisar antes de construir.")

    print()


if __name__ == "__main__":
    main()
