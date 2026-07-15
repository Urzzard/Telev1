#!/usr/bin/env python3
"""
Banco de pruebas offline del STT (Fase B) — ver docs/PLAN_WHISPER_ENDURECIMIENTO.md

Replaya los WAV capturados (STT_DUMP_DIR) por la MISMA lógica de transcribe + puerta de
confianza e imprime, por cada uno, las métricas y la DECISIÓN (pasa / descartado). Reproducible,
sin hacer llamadas. Sirve para verificar que la puerta NO rechaza el habla buena y sí caza la basura.

Corre DENTRO del contenedor backend (ahí están faster-whisper + CUDA + el modelo ya cargados):

    docker compose cp scripts/stt_replay.py backend:/tmp/stt_replay.py
    docker compose exec backend python /tmp/stt_replay.py

Opcional: STT_SAMPLES_DIR=/app/stt_samples (default).
No instala nada; usa lo que ya está en el contenedor.
"""
import os
import sys
import glob
import logging

# El backend importa como paquete `app`; aseguramos el path aunque el cwd no sea /app.
sys.path.insert(0, "/app")

# Ver en pantalla los logs [STT-CONF] / [STT-GATE] que emite stt.py.
logging.basicConfig(level=logging.INFO, format="%(message)s")

# Evitar que el replay vuelva a volcar WAVs en stt_samples (STT_DUMP_DIR está activo en el contenedor).
os.environ.pop("STT_DUMP_DIR", None)

import numpy as np
import scipy.io.wavfile as wavfile
from app.stt import get_stt

SAMPLES = os.getenv("STT_SAMPLES_DIR", "/app/stt_samples")


def main():
    files = sorted(glob.glob(os.path.join(SAMPLES, "*.wav")))
    if not files:
        print(f"❌ No hay WAVs en {SAMPLES}")
        return

    stt = get_stt()  # carga el modelo (ya en el contenedor)
    print(f"\n🎧 Replayando {len(files)} muestras de {SAMPLES}\n" + "=" * 70)

    pasan, descartadas = 0, 0
    for f in files:
        rate, data = wavfile.read(f)
        audio_bytes = np.asarray(data, dtype=np.int16).tobytes()
        texto = stt._transcribe_sync(audio_bytes)  # misma lógica: métricas + puerta + blocklist
        base = os.path.basename(f)
        if texto:
            pasan += 1
            print(f"✅ PASA      {base}  → '{texto}'\n" + "-" * 70)
        else:
            descartadas += 1
            print(f"🚧 DESCARTA  {base}  → (vacío: silencio/gate/blocklist)\n" + "-" * 70)

    print("=" * 70)
    print(f"  RESUMEN: {pasan} pasan · {descartadas} descartadas · {len(files)} total")
    print("  (revisa arriba que el HABLA BUENA pase y solo caiga la basura/silencio)")


if __name__ == "__main__":
    main()
