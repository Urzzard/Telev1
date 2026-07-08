#!/usr/bin/env python3
"""
Evaluación del Qwen-2B como clasificador de intención del "manejador de turno".
Ver diseño: docs/ARQUITECTURA_CEREBRO_LLM.md

QUÉ HACE
--------
Le manda al vLLM (el mismo que usa el bot de GLPI) ~55 frases reales y verifica que
las clasifique en la etiqueta correcta, usando `guided_choice` (per-request: NO toca
la config del server ni afecta a GLPI). Mide precisión por categoría y latencia.

QUÉ NO HACE
-----------
No importa nada del backend, no escribe en la BD, no arranca servicios. Es un .py aparte.

CÓMO CORRERLO
-------------
El LLM (AI-Service) tiene que estar arriba. Luego:

    VLLM_URL=http://localhost:8100 VLLM_MODEL=qwen3.5-2b python3 scripts/eval_intent_2b.py

Si localhost no llega al vLLM, prueba con la IP del bridge docker:
    VLLM_URL=http://172.17.0.1:8100 python3 scripts/eval_intent_2b.py

Defaults: VLLM_URL=http://localhost:8100  ·  VLLM_MODEL=qwen3.5-2b
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8100").rstrip("/")
MODEL = os.getenv("VLLM_MODEL")  # si no se define, se autodetecta de /v1/models
ENDPOINT = VLLM_URL + "/v1/chat/completions"
MODELS_ENDPOINT = VLLM_URL + "/v1/models"

# ---- Etiquetas por estado (mismo set del diseño) --------------------------------
IDENT_LABELS = ["CONFIRMA", "NIEGA", "PREGUNTA_QUIEN_LLAMA", "CALIBRACION", "OTRO"]
# v2: PIDE_REPETIR sale del clasificador → lo maneja la puerta de confianza del STT (stt.py).
# v3: CALIBRACION (meta-conversación de audio/conexión) absorbe parte del difuso OTRO.
DUDAS_LABELS = ["PREGUNTA", "DESPEDIDA", "FUERA_DE_TEMA", "CALIBRACION", "ACK"]

NOMBRE = "Manuel"

# ---- Prompts (con few-shot representativo; NO usa las frases de test) ------------
SYS_IDENT = f"""Eres un clasificador de intención para un teleoperador de RRHH de Salesland.
Estás en la fase de VERIFICACIÓN DE IDENTIDAD: acabas de preguntar "¿hablo con {NOMBRE}?".
Clasifica la respuesta del usuario en EXACTAMENTE una de estas etiquetas:
- CONFIRMA: confirma que es la persona o te invita a seguir ("sí soy yo", "el mismo", "con él habla", "dígame", "cuénteme").
- NIEGA: dice que no es la persona, que se equivocó, o que es número equivocado.
- PREGUNTA_QUIEN_LLAMA: pregunta QUIÉN llama o DE PARTE de quién ("¿de parte?", "¿quién habla?").
- CALIBRACION: comenta la calidad del audio/conexión o verifica que lo escuchas ("¿me escucha?", "¿sigue ahí?", "no le escucho", "se corta", "hay eco o ruido").
- OTRO: pide esperar o nada de lo anterior ("espere un momento", "ya regreso").
Responde SOLO con la etiqueta, en mayúsculas."""

SYS_DUDAS = """Eres un clasificador de intención para un teleoperador de RRHH de Salesland.
El usuario YA confirmó su identidad y está en la fase de DUDAS sobre su incorporación.
Los ÚNICOS temas "de su incorporación" son: horario, ubicación/cómo llegar, primer día, documentos a llevar, portal del empleado y motivo de la llamada.
Clasifica su último mensaje en EXACTAMENTE una de estas etiquetas:
- PREGUNTA: pide información sobre alguno de esos temas de su incorporación.
- DESPEDIDA: cierra la conversación o ya no necesita más, dicho de CUALQUIER forma, AUNQUE venga con un agradecimiento ("eso sería todo", "ya estamos", "no tengo más preguntas", "listo gracias", "chau").
- FUERA_DE_TEMA: pregunta algo que NO está en esos temas: noticias, deportes, chistes, clima, política, O temas que se derivan a RRHH presencial (salario, sueldo, vacaciones, beneficios, contrato).
- CALIBRACION: comenta la calidad del audio/conexión o verifica que lo escuchas ("¿me escuchas?", "¿sigues ahí?", "se escucha entrecortado", "no te escucho", "hay bulla o eco").
- ACK: solo reconoce o agradece y la conversación SIGUE abierta ("ok, ya", "ah entiendo", "claro"). Si además cierra o se despide, entonces es DESPEDIDA, no ACK.
Responde SOLO con la etiqueta, en mayúsculas."""

# Few-shot DIRIGIDO a los pares que se confundían — y DISJUNTO de las frases de test
# (para medir generalización real, no memorización).
FEWSHOT_IDENT = [
    ("Sí, dígame nomás", "CONFIRMA"),
    ("No, se equivocó de número", "NIEGA"),
    ("¿Quién me llama?", "PREGUNTA_QUIEN_LLAMA"),
    ("Se escucha un eco horrible", "CALIBRACION"),
    ("Deme un segundo, ya regreso", "OTRO"),
]
FEWSHOT_DUDAS = [
    ("¿A qué hora es el ingreso?", "PREGUNTA"),
    ("Ya no necesito nada más, gracias", "DESPEDIDA"),
    ("Ya, ok, chau pues", "DESPEDIDA"),
    ("¿Cuánto es el sueldo?", "FUERA_DE_TEMA"),
    ("¿Cómo quedó el partido de ayer?", "FUERA_DE_TEMA"),
    ("Perdona, se cortó, ¿qué decías?", "CALIBRACION"),
    ("Ah ok, perfecto", "ACK"),
]

# ---- Conjunto de prueba (~55 frases) --------------------------------------------
# (frase, estado, etiqueta_esperada, nota_opcional)
TESTS = [
    # ===================== VERIFICACIÓN DE IDENTIDAD =====================
    ("Sí, soy yo", "IDENTIDAD", "CONFIRMA", ""),
    ("Sí, ¿qué tal?", "IDENTIDAD", "CONFIRMA", ""),
    ("El mismo", "IDENTIDAD", "CONFIRMA", ""),
    ("Ajá, dígame", "IDENTIDAD", "CONFIRMA", ""),
    ("Claro, con él habla", "IDENTIDAD", "CONFIRMA", ""),
    ("Sí correcto, soy Manuel", "IDENTIDAD", "CONFIRMA", ""),
    ("Ah sí, buenas", "IDENTIDAD", "CONFIRMA", "puede confundirse con OTRO"),
    ("No, número equivocado", "IDENTIDAD", "NIEGA", ""),
    ("No, no soy yo", "IDENTIDAD", "NIEGA", ""),
    ("Creo que se equivocó", "IDENTIDAD", "NIEGA", ""),
    ("Acá no vive ningún Manuel", "IDENTIDAD", "NIEGA", ""),
    ("No, para nada", "IDENTIDAD", "NIEGA", ""),
    ("¿De parte de quién?", "IDENTIDAD", "PREGUNTA_QUIEN_LLAMA", ""),
    ("¿De parte?", "IDENTIDAD", "PREGUNTA_QUIEN_LLAMA", ""),
    ("¿Quién habla?", "IDENTIDAD", "PREGUNTA_QUIEN_LLAMA", ""),
    ("¿Con quién tengo el gusto?", "IDENTIDAD", "PREGUNTA_QUIEN_LLAMA", ""),
    ("¿De dónde me llaman?", "IDENTIDAD", "PREGUNTA_QUIEN_LLAMA", ""),
    ("Disculpe, ¿quién es usted?", "IDENTIDAD", "PREGUNTA_QUIEN_LLAMA", ""),
    # -- CALIBRACION (audio/conexión) — antes caían en el difuso OTRO --
    ("Aló, aló, no le escucho", "IDENTIDAD", "CALIBRACION", ""),
    ("¿Me escucha bien?", "IDENTIDAD", "CALIBRACION", ""),
    ("No lo escucho, se corta", "IDENTIDAD", "CALIBRACION", ""),
    # -- OTRO (pide esperar / nada de lo anterior) --
    ("Espéreme un momento por favor", "IDENTIDAD", "OTRO", ""),
    ("Un ratito por favor, ya regreso", "IDENTIDAD", "OTRO", ""),

    # ===================== FASE DE DUDAS =====================
    # -- PREGUNTA --
    ("¿A qué hora entro?", "DUDAS", "PREGUNTA", ""),
    ("¿Dónde queda la oficina?", "DUDAS", "PREGUNTA", ""),
    ("Oye, y ¿qué documentos llevo?", "DUDAS", "PREGUNTA", ""),
    ("El primer día ¿a quién busco?", "DUDAS", "PREGUNTA", ""),
    ("Quisiera saber el horario, por favor", "DUDAS", "PREGUNTA", ""),
    ("¿Cómo llego hasta allá?", "DUDAS", "PREGUNTA", ""),
    ("¿Y qué me pongo el primer día?", "DUDAS", "PREGUNTA", ""),
    ("Una pregunta, ¿el portal cuál es?", "DUDAS", "PREGUNTA", ""),
    # -- DESPEDIDA --
    ("No, eso es todo, gracias", "DUDAS", "DESPEDIDA", ""),
    ("Eso sería todo", "DUDAS", "DESPEDIDA", "hoy NO lo reconoce"),
    ("Ya para qué seguimos", "DUDAS", "DESPEDIDA", "cero keywords hoy"),
    ("Nada más por ahora", "DUDAS", "DESPEDIDA", ""),
    ("Listo, muchas gracias", "DUDAS", "DESPEDIDA", "ambigua con ACK"),
    ("Ok, chau", "DUDAS", "DESPEDIDA", ""),
    ("No tengo más preguntas", "DUDAS", "DESPEDIDA", ""),
    ("Ya estamos entonces", "DUDAS", "DESPEDIDA", ""),
    ("Bueno, gracias por todo", "DUDAS", "DESPEDIDA", ""),
    # -- FUERA_DE_TEMA --
    ("¿Qué noticias hay hoy?", "DUDAS", "FUERA_DE_TEMA", ""),
    ("¿Cuánto voy a ganar?", "DUDAS", "FUERA_DE_TEMA", "salario → derivar"),
    ("¿Cómo va la selección peruana?", "DUDAS", "FUERA_DE_TEMA", ""),
    ("¿Me cuentas un chiste?", "DUDAS", "FUERA_DE_TEMA", ""),
    ("¿Cuántos días de vacaciones tengo?", "DUDAS", "FUERA_DE_TEMA", "beneficio → derivar"),
    ("¿Qué opinas de la política?", "DUDAS", "FUERA_DE_TEMA", ""),
    ("¿Tienen algún bono o comisión?", "DUDAS", "FUERA_DE_TEMA", "beneficio → derivar"),
    # -- PIDE_REPETIR: movido a la puerta de confianza del STT (stt.py), fuera del clasificador --
    # -- CALIBRACION (calidad de audio/conexión) --
    ("¿Me escuchas?", "DUDAS", "CALIBRACION", ""),
    ("¿Sigues ahí?", "DUDAS", "CALIBRACION", ""),
    ("Se te escucha entrecortado", "DUDAS", "CALIBRACION", ""),
    ("No te escucho bien", "DUDAS", "CALIBRACION", ""),
    ("Hay mucha bulla acá, no oigo", "DUDAS", "CALIBRACION", ""),
    ("Se está cortando la llamada", "DUDAS", "CALIBRACION", ""),
    # -- ACK / backchannel --
    ("Ok, ya", "DUDAS", "ACK", ""),
    ("Ah ya, entiendo", "DUDAS", "ACK", ""),
    ("Perfecto, gracias", "DUDAS", "ACK", "ambigua con DESPEDIDA"),
    ("Claro, tiene sentido", "DUDAS", "ACK", ""),
    ("Ajá, ya veo", "DUDAS", "ACK", ""),
]


def _build_messages(estado, frase):
    if estado == "IDENTIDAD":
        sys_p, shots = SYS_IDENT, FEWSHOT_IDENT
    else:
        sys_p, shots = SYS_DUDAS, FEWSHOT_DUDAS
    msgs = [{"role": "system", "content": sys_p}]
    for ejem, lab in shots:
        msgs.append({"role": "user", "content": ejem})
        msgs.append({"role": "assistant", "content": lab})
    msgs.append({"role": "user", "content": frase})
    return msgs


def discover_model():
    """Autodetecta el id del modelo servido (solo stdlib, no instala nada)."""
    try:
        with urllib.request.urlopen(MODELS_ENDPOINT, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["data"][0]["id"]
    except Exception as e:
        print(f"⚠️  No pude autodetectar el modelo ({e}). Usa VLLM_MODEL=... explícito.")
        sys.exit(1)


def _post(body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=data,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read().decode("utf-8"))
    dt = (time.time() - t0) * 1000.0
    return resp["choices"][0]["message"]["content"].strip(), dt


# ¿El vLLM soporta guided_choice? Se detecta en la 1ª llamada.
GUIDED = {"ok": True, "probed": False}


def classify(estado, frase, labels):
    msgs = _build_messages(estado, frase)
    base = {
        "model": MODEL, "messages": msgs, "max_tokens": 12,
        "temperature": 0.0, "chat_template_kwargs": {"enable_thinking": False},
    }
    # Intento con guided_choice (per-request, no afecta a GLPI)
    if GUIDED["ok"]:
        try:
            body = dict(base); body["guided_choice"] = labels
            txt, dt = _post(body)
            GUIDED["probed"] = True
            return _norm(txt, labels), dt
        except urllib.error.HTTPError as e:
            if not GUIDED["probed"]:
                print(f"⚠️  guided_choice NO soportado por este vLLM (HTTP {e.code}). "
                      f"Cae a modo texto+parseo.\n")
                GUIDED["ok"] = False
            else:
                raise
    # Fallback: generación normal + parseo
    txt, dt = _post(base)
    return _norm(txt, labels), dt


def _norm(txt, labels):
    """Normaliza la salida a una etiqueta conocida."""
    up = txt.upper()
    for lab in labels:
        if lab in up:
            return lab
    return txt.strip()  # no matcheó ninguna → se reporta tal cual


def _parse_repeat():
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--repeat" and i + 1 < len(argv):
            return max(1, int(argv[i + 1]))
        if a.startswith("--repeat="):
            return max(1, int(a.split("=", 1)[1]))
    return max(1, int(os.getenv("REPEAT", "1")))


def _es_ambiguo(nota):
    return bool(nota) and ("ambigu" in nota or "confund" in nota)


def main():
    from collections import Counter
    global MODEL
    if not MODEL:
        MODEL = discover_model()
    repeat = _parse_repeat()

    print("=" * 70)
    print("  EVALUACIÓN Qwen-2B como clasificador de intención (manejador de turno)")
    print("=" * 70)
    print(f"  vLLM     : {ENDPOINT}")
    print(f"  Modelo   : {MODEL}")
    print(f"  Frases   : {len(TESTS)}" + (f"   ·  pasadas: {repeat}" if repeat > 1 else ""))
    print("=" * 70)

    # Sanity check de conexión
    try:
        _post({"model": MODEL, "messages": [{"role": "user", "content": "ok"}],
               "max_tokens": 1, "chat_template_kwargs": {"enable_thinking": False}})
    except Exception as e:
        print(f"\n❌ No pude conectar al vLLM en {ENDPOINT}\n   {e}")
        print("   ¿Está arriba el AI-Service? Prueba con VLLM_URL=http://172.17.0.1:8100")
        sys.exit(1)

    lat = []
    collected = []  # {estado, frase, exp, nota, answers:[...]}

    for estado in ("IDENTIDAD", "DUDAS"):
        labels = IDENT_LABELS if estado == "IDENTIDAD" else DUDAS_LABELS
        if repeat == 1:
            print(f"\n── {estado} " + "─" * (66 - len(estado)))
        for frase, est, exp, nota in TESTS:
            if est != estado:
                continue
            answers, last_dt = [], 0
            for _ in range(repeat):
                got, dt = classify(estado, frase, labels)
                answers.append(got)
                lat.append(dt)
                last_dt = dt
            collected.append({"estado": estado, "frase": frase, "exp": exp,
                              "nota": nota, "answers": answers})
            if repeat == 1:
                ok = answers[0] == exp
                marca = "✓" if ok else "✗"
                extra = "" if ok else f"  → dio: {answers[0]}"
                notag = f"   ({nota})" if nota else ""
                print(f"  {marca} {exp:<20} {frase[:42]:<42} {last_dt:5.0f}ms{extra}{notag}")

    def rep_answer(r):
        return r["answers"][0] if repeat == 1 else Counter(r["answers"]).most_common(1)[0][0]

    total = len(collected)
    aciertos = sum(1 for r in collected if rep_answer(r) == r["exp"])
    pct = 100.0 * aciertos / total if total else 0

    print("\n" + "=" * 70)
    print(f"  RESULTADO: {aciertos}/{total} correctas  ({pct:.1f}%)"
          + ("   [voto mayoritario]" if repeat > 1 else ""))
    print(f"  Latencia media: {sum(lat)/len(lat):.0f}ms  ·  máx: {max(lat):.0f}ms")
    print(f"  Modo: {'guided_choice ✔ (formato garantizado)' if GUIDED['ok'] else 'texto+parseo (guided NO soportado)'}")
    print("=" * 70)

    # ---- Estabilidad (solo con --repeat > 1) ----
    if repeat > 1:
        print("  Precisión por pasada:")
        for k in range(repeat):
            c = sum(1 for r in collected if r["answers"][k] == r["exp"])
            print(f"    Pasada {k+1}: {c}/{total} ({100.0*c/total:.1f}%)")
        estables = sum(1 for r in collected if len(set(r["answers"])) == 1)
        print(f"\n  ESTABILIDAD: {estables}/{total} frases dieron SIEMPRE la misma etiqueta en las {repeat} pasadas.")
        inest = [r for r in collected if len(set(r["answers"])) > 1]
        if inest:
            print("  ⚠️  Frases INESTABLES (el 2B cambió de opinión entre pasadas):")
            for r in inest:
                dist = ", ".join(f"{k}×{v}" for k, v in Counter(r["answers"]).items())
                print(f"    [{r['estado']}] \"{r['frase']}\"  →  {dist}")
        else:
            print("  🎯 100% estable — misma respuesta en todas las pasadas.")
        print("=" * 70)

    # ---- Precisión por etiqueta ----
    por_label = {}
    for r in collected:
        por_label.setdefault(r["exp"], [0, 0])
        por_label[r["exp"]][1] += 1
        por_label[r["exp"]][0] += (rep_answer(r) == r["exp"])
    print("  Precisión por etiqueta:")
    for lab in sorted(por_label):
        okc, tc = por_label[lab]
        print(f"    {lab:<22} {okc}/{tc}")

    # ---- Fallos ----
    fallos = [r for r in collected if rep_answer(r) != r["exp"]]
    if fallos:
        print("\n  ⚠️  FALLOS (candidatos a afinar prompt / o casos ambiguos):")
        for r in fallos:
            amb = "  [marcado ambiguo]" if _es_ambiguo(r["nota"]) else ""
            print(f"    [{r['estado']}] \"{r['frase']}\"  esperaba {r['exp']}  ·  dio {rep_answer(r)}{amb}")
    else:
        print("\n  🎯 Sin fallos. Clasificación por SIGNIFICADO, no por lista de palabras.")

    print()


if __name__ == "__main__":
    main()
