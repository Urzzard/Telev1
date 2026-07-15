#!/usr/bin/env python3
"""
Prototipo del turn-handler CORREGIDO (dos pasos), fase DUDAS. Ver docs/ARQUITECTURA_CEREBRO_LLM.md

Paso 1: CLASIFICAR con guided_choice (prompt clasificador puro) → intent fiable (~98%).
Paso 2: GENERAR respuesta SOLO si intent ∈ {PREGUNTA, FUERA_DE_TEMA}. Para DESPEDIDA/ACK/CALIBRACION
        el "esqueleto" usa frase canned → NO se llama al LLM para generar.

Demuestra: intent recuperado a ~98% (vs 50% al fusionar), respuesta generada solo cuando toca, y la
latencia real (clasif barato + gen condicional). Solo stdlib, no instala nada.

Uso:  python3 scripts/test_turn_handler.py   (o VLLM_URL=http://172.17.0.1:8100 ...)
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
LABELS = ["PREGUNTA", "DESPEDIDA", "FUERA_DE_TEMA", "CALIBRACION", "ACK"]
GENERAN = {"PREGUNTA"}  # SOLO PREGUNTA genera. FUERA_DE_TEMA pasa a desvío canned (el LLM "seguía el juego").

# Canned del esqueleto para los intents que NO generan (representativo).
CANNED = {
    "DESPEDIDA": "(esqueleto) despedida + colgar",
    "ACK": "(esqueleto) breve '¿algo más?' o nada",
    "CALIBRACION": "(esqueleto) 'Sí, te escucho. ¿Me repites, por favor?'",
    "FUERA_DE_TEMA": "(esqueleto) 'Solo puedo ayudarte con temas de tu incorporación. ¿Alguna duda de tu primer día?'",
}

# --- Paso 1: prompt CLASIFICADOR puro (el que dio 98.3%) ---
SYS_CLASIF = """Eres un clasificador de intención para un teleoperador de RRHH de Salesland.
El usuario YA confirmó su identidad y está en la fase de DUDAS sobre su incorporación.
Los ÚNICOS temas "de su incorporación" son: horario, ubicación/cómo llegar, primer día, documentos a llevar, portal del empleado y motivo de la llamada.
Clasifica su último mensaje en EXACTAMENTE una etiqueta:
- PREGUNTA: pide información sobre alguno de esos temas de su incorporación.
- DESPEDIDA: cierra la conversación o ya no necesita más, dicho de CUALQUIER forma, AUNQUE venga con un agradecimiento ("eso sería todo", "ya estamos", "no tengo más preguntas", "listo gracias", "chau").
- FUERA_DE_TEMA: pregunta algo que NO está en esos temas: noticias, deportes, chistes, clima, política, O temas que se derivan a RRHH presencial (salario, sueldo, vacaciones, beneficios, contrato).
- CALIBRACION: comenta la calidad del audio/conexión o verifica que lo escuchas ("¿me escuchas?", "¿sigues ahí?", "se escucha entrecortado", "no te escucho", "hay bulla o eco").
- ACK: solo reconoce o agradece y la conversación SIGUE abierta ("ok, ya", "ah entiendo", "claro"). Si además cierra o se despide, entonces es DESPEDIDA, no ACK.
Responde SOLO con la etiqueta, en mayúsculas."""

FEWSHOT_CLASIF = [
    ("¿A qué hora es el ingreso?", "PREGUNTA"),
    ("Ya no necesito nada más, gracias", "DESPEDIDA"),
    ("Ya, ok, chau pues", "DESPEDIDA"),
    ("¿Cuánto es el sueldo?", "FUERA_DE_TEMA"),
    ("¿Cómo quedó el partido de ayer?", "FUERA_DE_TEMA"),
    ("Perdona, se cortó, ¿qué decías?", "CALIBRACION"),
    ("Ah ok, perfecto", "ACK"),
]

# --- Paso 2: prompt de GENERACIÓN (respuesta hablada) ---
SYS_GEN = f"""Eres Jorge, de Recursos Humanos de Salesland, en llamada con {NOMBRE} (ya confirmó su identidad).
Responde en 1-2 oraciones, cálido y natural. Datos que tienes:
- Horario: de 9 de la mañana a 6 de la tarde, con descanso de 1 a 2 de la tarde, de lunes a viernes.
- Dirección: Jirón Horacio Cachay Díaz 393, La Victoria, Lima.
- Portal del empleado: peru.salesland.net:8088/salesland-autoservicios-web
- Primer día: preséntate en recepción; RRHH o tu jefe de área te atenderán.
- Documentos: DNI y los indicados en tu correo de bienvenida.
Si te preguntan algo que NO está aquí (nombre del jefe, salario, vacaciones, noticias, etc.), NO lo inventes:
desvía amable ("eso lo verás con Recursos Humanos" / "solo puedo ayudarte con tu incorporación").
No uses horas en formato numérico (di "9 de la mañana"). No te despidas."""

# (frase, intent_esperado) — set variado por intención para medir robustez, no solo estabilidad.
TESTS = [
    # -- PREGUNTA (varias formas; incluye una SIN dato → debe desviar sin inventar) --
    ("¿A qué hora entro a trabajar?", "PREGUNTA"),
    ("Oye, y ¿dónde queda la oficina?", "PREGUNTA"),
    ("¿Qué documentos tengo que llevar el primer día?", "PREGUNTA"),
    ("¿Cómo llego hasta allá?", "PREGUNTA"),
    ("¿Cuál es el portal del empleado?", "PREGUNTA"),
    ("El primer día, ¿a quién busco?", "PREGUNTA"),
    ("¿Cuál es el nombre de mi jefe de área?", "PREGUNTA"),   # sin dato → desviar
    # -- DESPEDIDA --
    ("Ya, eso sería todo, muchas gracias.", "DESPEDIDA"),
    ("No, ya no tengo más preguntas.", "DESPEDIDA"),
    ("Listo, ya estamos entonces.", "DESPEDIDA"),
    ("Ok, chau, gracias.", "DESPEDIDA"),
    ("Ya para qué seguimos, gracias.", "DESPEDIDA"),
    # -- FUERA_DE_TEMA (off-topic y temas que se derivan) --
    ("¿Cuánto voy a ganar?", "FUERA_DE_TEMA"),
    ("¿Cuántos días de vacaciones tengo?", "FUERA_DE_TEMA"),
    ("¿Qué noticias hay hoy?", "FUERA_DE_TEMA"),
    ("¿Me cuentas un chiste?", "FUERA_DE_TEMA"),
    ("¿Cómo va la selección peruana?", "FUERA_DE_TEMA"),
    # -- CALIBRACION (audio/conexión) --
    ("¿Me escuchas? Se está cortando.", "CALIBRACION"),
    ("No te escucho bien, hay eco.", "CALIBRACION"),
    ("¿Sigues ahí?", "CALIBRACION"),
    # -- ACK (reconoce y sigue, sin preguntar ni despedirse) --
    ("Ah, ok, perfecto.", "ACK"),
    ("Ya, me quedó claro.", "ACK"),
    ("Claro, tiene sentido.", "ACK"),
]


def discover_model():
    try:
        with urllib.request.urlopen(MODELS_ENDPOINT, timeout=8) as r:
            return json.loads(r.read().decode())["data"][0]["id"]
    except Exception as e:
        print(f"⚠️  No pude autodetectar el modelo ({e}).")
        sys.exit(1)


def _post(body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=data, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return resp["choices"][0]["message"]["content"].strip(), (time.time() - t0) * 1000.0


def clasificar(texto):
    msgs = [{"role": "system", "content": SYS_CLASIF}]
    for ej, lab in FEWSHOT_CLASIF:
        msgs += [{"role": "user", "content": ej}, {"role": "assistant", "content": lab}]
    msgs.append({"role": "user", "content": texto})
    raw, dt = _post({
        "model": MODEL, "messages": msgs, "max_tokens": 12, "temperature": 0.0,
        "guided_choice": LABELS, "chat_template_kwargs": {"enable_thinking": False},
    })
    up = raw.upper()
    for lab in LABELS:
        if lab in up:
            return lab, dt
    return raw, dt


def generar(texto):
    raw, dt = _post({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYS_GEN}, {"role": "user", "content": texto}],
        "max_tokens": 120, "temperature": 0.5, "chat_template_kwargs": {"enable_thinking": False},
    })
    return raw, dt


def _parse_repeat():
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--repeat" and i + 1 < len(argv):
            return max(1, int(argv[i + 1]))
        if a.startswith("--repeat="):
            return max(1, int(a.split("=", 1)[1]))
    return max(1, int(os.getenv("REPEAT", "1")))


def modo_estabilidad(repeat):
    """Corre SOLO la clasificación (el paso de decisión) N veces y mide estabilidad del intent."""
    from collections import Counter
    print(f"  MODO ESTABILIDAD — clasificación × {repeat} pasadas (la generación no se mide, es no-determinista)\n")
    collected = []
    for frase, exp in TESTS:
        answers = [clasificar(frase)[0] for _ in range(repeat)]
        collected.append((frase, exp, answers))

    total = len(collected)
    print("  Precisión por pasada:")
    for k in range(repeat):
        c = sum(1 for _, exp, ans in collected if ans[k] == exp)
        print(f"    Pasada {k+1}: {c}/{total} ({100.0*c/total:.0f}%)")

    estables = sum(1 for _, _, ans in collected if len(set(ans)) == 1)
    print(f"\n  ESTABILIDAD: {estables}/{total} frases dieron la MISMA etiqueta en las {repeat} pasadas.")
    inest = [(f, e, a) for f, e, a in collected if len(set(a)) > 1]
    if inest:
        print("  ⚠️  Frases inestables:")
        for f, e, a in inest:
            dist = ", ".join(f"{k}×{v}" for k, v in Counter(a).items())
            print(f"    \"{f}\" (esperaba {e}) → {dist}")
    else:
        print("  🎯 100% estable — misma etiqueta en todas las pasadas.")

    ok = sum(1 for _, exp, ans in collected if Counter(ans).most_common(1)[0][0] == exp)
    print(f"\n  intent correcto (voto mayoritario): {ok}/{total}")


def main():
    global MODEL
    if not MODEL:
        MODEL = discover_model()

    repeat = _parse_repeat()

    print("=" * 72)
    print("  PROTOTIPO turn-handler CORREGIDO — clasificar (guided_choice) + generar condicional")
    print("=" * 72)
    print(f"  vLLM: {ENDPOINT}  ·  Modelo: {MODEL}\n")

    if repeat > 1:
        modo_estabilidad(repeat)
        return

    ok_intent, total = 0, 0
    for frase, exp in TESTS:
        intent, t_clasif = clasificar(frase)
        total += 1
        ok = intent == exp
        ok_intent += ok
        marca = "✓" if ok else "✗"

        if intent in GENERAN:
            respuesta, t_gen = generar(frase)
            fuente = f"LLM ({t_gen:.0f}ms)"
            t_total = t_clasif + t_gen
        else:
            respuesta = CANNED.get(intent, "(esqueleto)")
            fuente = "esqueleto (0ms, sin generar)"
            t_total = t_clasif

        terminar = intent == "DESPEDIDA"
        print(f"  {marca} \"{frase}\"  (esperaba {exp})")
        print(f"      intent={intent}  terminar={terminar}  ·  clasif={t_clasif:.0f}ms  gen={fuente}  TOTAL={t_total:.0f}ms")
        print(f"      respuesta → {respuesta[:110]}")
        print("  " + "-" * 68)

    print("=" * 72)
    print(f"  intent correcto: {ok_intent}/{total}   (comparar vs 3/6 al fusionar en guided_json)")
    print("  Nota: DESPEDIDA/ACK/CALIBRACION no llaman al LLM a generar → más rápidos que hoy.")
    print("=" * 72)


if __name__ == "__main__":
    main()
