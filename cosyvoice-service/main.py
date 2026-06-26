"""
cosyvoice-service — TTS CosyVoice3 para el Teleoperador.

Contrato calcado de f5-service (drop-in para el backend):
  POST /v1/audio/speech  { input, voice?, response_format?: "pcm"|"wav", speed? }
     - pcm → StreamingResponse octet-stream, int16 PCM crudo SIN cabecera a 24000 Hz
     - wav → Response audio/wav PCM_16
  GET  /health  → estado, voces disponibles
  GET  /voices  → lista de voces registradas (para el "selector de voces")

Selector de voces:
  En /app/voices se ponen pares <nombre>.wav (o .flac/.mp3) + <nombre>.txt (transcripción).
  Al arrancar se registra cada voz (spk_id = nombre del archivo) si no está ya cacheada.
  El campo `voice` de la petición elige la voz; si no existe, cae a DEFAULT_VOICE.
  Agregar/cambiar una voz NO re-descarga el modelo: suelta los 2 archivos y reinicia.

El modelo (~8.5GB) se auto-descarga de ModelScope a un volumen persistente la 1ª vez.
La voz cacheada (spk2info.pt) se guarda en el dir del modelo (también persiste en el volumen).
"""
import os
import sys
import io
import glob
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
import soundfile as sf
import torch
import torchaudio

from fastapi import FastAPI
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel

# Repo CosyVoice (también vía ENV PYTHONPATH, aquí por robustez)
sys.path.append("/workspace/CosyVoice")
sys.path.append("/workspace/CosyVoice/third_party/Matcha-TTS")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("CosyVoice-Service")

MODEL_ID      = os.getenv("COSYVOICE_MODEL_ID", "FunAudioLLM/Fun-CosyVoice3-0.5B-2512")
MODEL_DIR     = os.getenv("COSYVOICE_MODEL_DIR", "/models/Fun-CosyVoice3-0.5B")
VOICES_DIR    = os.getenv("COSYVOICE_VOICES_DIR", "/app/voices")
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "salesland")
DEFAULT_SPEED = float(os.getenv("COSYVOICE_SPEED", "1.0"))
TEXT_FRONTEND = os.getenv("TEXT_FRONTEND", "0") == "1"   # False = números en español nativo
INSTRUCT      = os.getenv("INSTRUCT", "You are a helpful assistant.")
WARMUP        = os.getenv("WARMUP", "1") == "1"

cosyvoice = None
sample_rate = 24000
available_voices: list[str] = []


def _ensure_model():
    """Descarga el modelo a MODEL_DIR si no está (costo único, persiste en el volumen)."""
    if os.path.exists(os.path.join(MODEL_DIR, "cosyvoice3.yaml")):
        logger.info(f"✅ Modelo ya presente en {MODEL_DIR}")
        return
    logger.info(f"⏳ Modelo no encontrado; descargando {MODEL_ID} de ModelScope → {MODEL_DIR} ...")
    from modelscope import snapshot_download
    snapshot_download(MODEL_ID, local_dir=MODEL_DIR)
    logger.info("✅ Modelo descargado")


def _to_16k_mono(path: str) -> str:
    """Devuelve un WAV mono 16k (lo que CosyVoice espera para la referencia)."""
    wav, sr = torchaudio.load(path)
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    if sr != 16000:
        wav = torchaudio.transforms.Resample(sr, 16000)(wav)
        out = f"/tmp/_ref_{os.path.basename(path)}_16k.wav"
        torchaudio.save(out, wav, 16000)
        return out
    return path


def _register_voices():
    """Registra cada par <nombre>.txt + <nombre>.(wav|flac|mp3) de VOICES_DIR."""
    global available_voices
    changed = False
    for txt in sorted(glob.glob(os.path.join(VOICES_DIR, "*.txt"))):
        name = os.path.splitext(os.path.basename(txt))[0]
        audio = None
        for ext in (".wav", ".flac", ".mp3"):
            cand = os.path.join(VOICES_DIR, name + ext)
            if os.path.exists(cand):
                audio = cand
                break
        if audio is None:
            logger.warning(f"⚠️  voz '{name}': sin audio (.wav/.flac/.mp3) — la salto")
            continue

        if name in cosyvoice.frontend.spk2info:
            logger.info(f"🎙️  voz '{name}' ya cacheada — reutilizo")
            available_voices.append(name)
            continue

        with open(txt, encoding="utf-8") as f:
            ref_text = f.read().strip()
        prompt_text = f"{INSTRUCT}<|endofprompt|>{ref_text}"
        ref16 = _to_16k_mono(audio)
        logger.info(f"🎙️  registrando voz '{name}' (1ª vez)...")
        cosyvoice.add_zero_shot_spk(prompt_text, ref16, name)
        available_voices.append(name)
        changed = True

    if changed:
        cosyvoice.save_spkinfo()
        logger.info("💾 spk2info.pt guardado")
    logger.info(f"✅ voces disponibles: {available_voices} | por defecto: '{DEFAULT_VOICE}'")


def _load():
    """Carga pesada (en executor): modelo + registro de voces + warmup."""
    global cosyvoice, sample_rate
    from cosyvoice.cli.cosyvoice import AutoModel

    _ensure_model()
    logger.info("⏳ Cargando Fun-CosyVoice3-0.5B (fp16)...")
    cosyvoice = AutoModel(model_dir=MODEL_DIR, fp16=True)
    sample_rate = cosyvoice.sample_rate
    logger.info(f"✅ Modelo cargado | sample_rate={sample_rate}")

    _register_voices()

    if WARMUP and available_voices:
        v = DEFAULT_VOICE if DEFAULT_VOICE in available_voices else available_voices[0]
        logger.info(f"🔥 warmup con voz '{v}'...")
        for _ in cosyvoice.inference_zero_shot(
            "Hola, listo.", "", "", zero_shot_spk_id=v, stream=True, text_frontend=TEXT_FRONTEND
        ):
            pass
        logger.info("✅ warmup ok")


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _load)
    yield


app = FastAPI(lifespan=lifespan)


class SpeechRequest(BaseModel):
    input: str
    voice: Optional[str] = None
    response_format: Optional[str] = "wav"
    speed: Optional[float] = None


def _resolve_voice(voice: Optional[str]) -> str:
    if voice and voice in available_voices:
        return voice
    return DEFAULT_VOICE if DEFAULT_VOICE in available_voices else (available_voices[0] if available_voices else "")


def _infer_chunks(text: str, voice: str, speed: float):
    """Generador SÍNCRONO: produce chunks (tensor [1,N]) de inference_zero_shot streaming."""
    for out in cosyvoice.inference_zero_shot(
        text, "", "", zero_shot_spk_id=voice, stream=True, speed=speed, text_frontend=TEXT_FRONTEND
    ):
        yield out["tts_speech"]


def _chunk_to_pcm(chunk) -> bytes:
    arr = chunk.squeeze(0).cpu().numpy()
    arr = np.clip(arr, -1.0, 1.0)
    return (arr * 32767).astype(np.int16).tobytes()


@app.get("/health")
async def health():
    return {
        "status": "ok" if cosyvoice is not None else "loading",
        "model": "Fun-CosyVoice3-0.5B",
        "sample_rate": sample_rate,
        "voices": available_voices,
        "default_voice": DEFAULT_VOICE,
    }


@app.get("/voices")
async def voices():
    return {"voices": available_voices, "default": DEFAULT_VOICE}


@app.post("/v1/audio/speech")
async def synthesize(req: SpeechRequest):
    if cosyvoice is None:
        return Response(status_code=503, content=b"Model not loaded")

    voice = _resolve_voice(req.voice)
    if not voice:
        return Response(status_code=503, content=b"No voices registered")

    speed = req.speed if req.speed is not None else DEFAULT_SPEED

    if req.response_format == "pcm":
        async def stream():
            loop = asyncio.get_event_loop()
            queue: asyncio.Queue = asyncio.Queue()
            SENTINEL = object()

            def produce():
                try:
                    for chunk in _infer_chunks(req.input, voice, speed):
                        loop.call_soon_threadsafe(queue.put_nowait, _chunk_to_pcm(chunk))
                except Exception:
                    logger.exception("error en síntesis pcm")
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

            loop.run_in_executor(None, produce)
            logger.info(f"🎤 [pcm] voz='{voice}' speed={speed}: '{req.input[:50]}...'")
            while True:
                item = await queue.get()
                if item is SENTINEL:
                    break
                yield item

        return StreamingResponse(stream(), media_type="application/octet-stream")

    # wav
    loop = asyncio.get_event_loop()

    def render():
        chunks = list(_infer_chunks(req.input, voice, speed))
        audio = torch.cat(chunks, dim=1).squeeze(0).cpu().numpy()
        audio = np.clip(audio, -1.0, 1.0)
        buf = io.BytesIO()
        sf.write(buf, audio, sample_rate, format="WAV", subtype="PCM_16")
        return buf.getvalue()

    logger.info(f"🎤 [wav] voz='{voice}' speed={speed}: '{req.input[:60]}'")
    data = await loop.run_in_executor(None, render)
    return Response(content=data, media_type="audio/wav")
