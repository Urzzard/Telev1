#!/usr/bin/env python3
"""
Prueba del STREAMING del LLM + troceo por oraciones (Palanca 2, latencia).
Ver docs/PLAN_LATENCIA_Y_STREAMING.md

Pide la respuesta al vLLM con stream:true y simula el troceo del pipeline:
- Un trozo debe tener >= MIN_PALABRAS palabras (evita fragmentos como "¡Manuel," o "¡" sueltos).
- El PRIMER trozo puede cortar en coma/clausula (o a las ~10 palabras) para sacar audio rápido.
- Los siguientes cortan solo por fin de oración ('.', '!', '?') → buena prosodia.
Muestra a qué ms queda listo cada trozo = cuándo CosyVoice podría arrancar ese audio.

Solo stdlib. No instala nada.  Uso:  python3 scripts/test_stream.py
"""
import json
import os
import time
import urllib.request

VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8100").rstrip("/")
MODEL = os.getenv("VLLM_MODEL")
ENDPOINT = VLLM_URL + "/v1/chat/completions"
MODELS_ENDPOINT = VLLM_URL + "/v1/models"

SYS = """Eres Jorge, de Recursos Humanos de Salesland, en llamada con Manuel (ya confirmó su identidad).
Responde BREVE (1-2 oraciones), cálido y natural, solo con estos datos:
- Horario: de 9 de la mañana a 6 de la tarde, con descanso de 1 a 2 de la tarde.
- Dirección: Jirón Horacio Cachay Díaz 393, La Victoria, Lima.
Si no tienes el dato, no lo inventes. No uses horas en formato numérico. No uses markdown. No te despidas."""

PREGUNTAS = [
    "¿A qué hora entro a trabajar?",
    "¿Dónde queda la oficina y cómo llego hasta allá?",
]

MIN_PALABRAS = 2       # un trozo debe tener al menos 2 palabras para hablarse solo
MAX_PALABRAS_1ER = 10  # tope del primer trozo


def discover_model():
    with urllib.request.urlopen(MODELS_ENDPOINT, timeout=8) as r:
        return json.loads(r.read().decode())["data"][0]["id"]


def stream_tokens(pregunta):
    body = {
        "model": MODEL,
        "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": pregunta}],
        "max_tokens": 110, "temperature": 0.4, "stream": True,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=30)
    for raw in resp:                       # HTTPResponse se itera línea por línea → streaming
        line = raw.decode("utf-8").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            delta = json.loads(data)["choices"][0]["delta"].get("content")
        except Exception:
            continue
        if delta:
            yield delta


def _corte_valido(buf, chars, min_pal):
    """Índice de la frontera más temprana (de `chars`) cuyo prefijo tenga >= min_pal palabras, o -1."""
    best = -1
    for c in chars:
        i = buf.find(c)
        while i != -1:
            if len(buf[:i + 1].split()) >= min_pal:
                best = i if best == -1 else min(best, i)
                break
            i = buf.find(c, i + 1)
    return best


def _buscar_corte(buf, es_primero):
    cut = _corte_valido(buf, ".!?", MIN_PALABRAS)      # fin de oración (siempre)
    if cut != -1:
        return cut
    if es_primero:
        cut = _corte_valido(buf, ",;:", MIN_PALABRAS)  # coma/clausula (solo 1er trozo)
        if cut != -1:
            return cut
        if len(buf.split()) >= MAX_PALABRAS_1ER:        # o tope de palabras
            return len(buf) - 1
    return -1


def main():
    global MODEL
    if not MODEL:
        MODEL = discover_model()
    print(f"  vLLM: {ENDPOINT}  ·  Modelo: {MODEL}\n" + "=" * 74)

    for pregunta in PREGUNTAS:
        print(f"\n❓ {pregunta}")
        t0 = time.time()
        buf, chunk_idx, t_first = "", 0, None

        for delta in stream_tokens(pregunta):
            if t_first is None:
                t_first = (time.time() - t0) * 1000
            buf += delta
            while True:
                cut = _buscar_corte(buf, chunk_idx == 0)
                if cut == -1:
                    break
                trozo, buf = buf[:cut + 1], buf[cut + 1:]
                if trozo.strip():
                    chunk_idx += 1
                    dt = (time.time() - t0) * 1000
                    tag = "  ← 1er audio arrancaría AQUÍ" if chunk_idx == 1 else ""
                    print(f"   ⟶ chunk {chunk_idx} a {dt:5.0f}ms: '{trozo.strip()}'{tag}")

        if any(ch.isalpha() for ch in buf):       # cola final (solo si tiene letras, no puntuación suelta)
            chunk_idx += 1
            print(f"   ⟶ chunk {chunk_idx} a {(time.time()-t0)*1000:5.0f}ms: '{buf.strip()}'")

        print(f"   · 1er token a {t_first:.0f}ms · respuesta completa a {(time.time()-t0)*1000:.0f}ms")

    print("\n" + "=" * 74)
    print("  'chunk 1 a Xms' = cuándo CosyVoice podría empezar el 1er audio (hoy esperamos TODO).")


if __name__ == "__main__":
    main()
