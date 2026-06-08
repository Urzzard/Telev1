import os
import io
import re
import logging
import asyncio
from contextlib import asynccontextmanager

import numpy as np
import soundfile as sf
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("F5-Service")

REF_AUDIO = os.getenv("F5_REF_AUDIO", "/app/voices/referencia_24k.wav")
REF_TEXT  = os.getenv("F5_REF_TEXT",  "Netflix está apunto de comprar a Warner, y eso implica que serian los dueños de Batman!. Pero no solamente los dueños de Batman, si Netflix adquiriera Warner tendrían a Harry Potter")
F5_SPEED  = float(os.getenv("F5_SPEED", "0.9"))

tts_model = None


def _load_model():
    global tts_model
    from f5_tts.api import F5TTS
    from huggingface_hub import hf_hub_download

    logger.info("⏳ Descargando modelo F5-Spanish desde HuggingFace...")
    ckpt_file = hf_hub_download(repo_id="jpgallegoar/F5-Spanish", filename="model_1200000.safetensors")
    vocab_file = hf_hub_download(repo_id="jpgallegoar/F5-Spanish", filename="vocab.txt")
    logger.info(f"✅ Archivos descargados")

    tts_model = F5TTS(
        model_type="F5-TTS",
        ckpt_file=ckpt_file,
        vocab_file=vocab_file,
        device="cuda",
    )
    logger.info("✅ F5-Spanish listo en GPU")

    if not os.path.exists(REF_AUDIO):
        logger.warning(f"⚠️  No se encontró voz de referencia en {REF_AUDIO}")
        logger.warning("     Coloca un archivo WAV de 10-15s de voz en español en ese path.")
        logger.warning("     El servicio responderá con errores 503 hasta que exista el archivo.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _load_model)
    yield


app = FastAPI(lifespan=lifespan)


class SpeechRequest(BaseModel):
    input: str
    voice: Optional[str] = "default"
    response_format: Optional[str] = "wav"
    speed: Optional[float] = None


def _split_sentences(text: str) -> list[str]:
    protected = (text
        .replace("a.m.", "a·m·").replace("p.m.", "p·m·")
        .replace("Sr.", "Sr·").replace("Sra.", "Sra·")
        .replace("Dr.", "Dr·").replace("Dra.", "Dra·")
    )
    parts = re.split(r'(?<=[.!?])\s+', protected.strip())
    result = []
    for s in parts:
        s = (s
            .replace("a·m·", "a.m.").replace("p·m·", "p.m.")
            .replace("Sr·", "Sr.").replace("Sra·", "Sra.")
            .replace("Dr·", "Dr.").replace("Dra·", "Dra.")
            .strip()
        )
        if s and len(s) > 2:
            result.append(s)
    return result or [text]


def _infer(text: str, speed: float) -> tuple[np.ndarray, int]:
    wav, sr, _ = tts_model.infer(
        ref_file=REF_AUDIO,
        ref_text=REF_TEXT,
        gen_text=text,
        speed=speed,
    )
    return wav, sr


def _to_wav_bytes(wav: np.ndarray, sr: int) -> bytes:
    import torch
    if isinstance(wav, torch.Tensor):
        wav = wav.cpu().numpy()
    wav = np.array(wav, dtype=np.float32)
    if wav.ndim > 1:
        wav = wav.squeeze()
    buf = io.BytesIO()
    sf.write(buf, wav, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _to_pcm_bytes(wav: np.ndarray) -> bytes:
    return (wav * 32767).astype(np.int16).tobytes()


@app.get("/health")
async def health():
    return {"status": "ok", "model": "F5-Spanish", "ref_audio": os.path.exists(REF_AUDIO)}


@app.post("/v1/audio/speech")
async def synthesize(req: SpeechRequest):
    if tts_model is None:
        return Response(status_code=503, content=b"Model not loaded")
    if not os.path.exists(REF_AUDIO):
        return Response(status_code=503, content=b"Reference audio not found")

    speed = req.speed if req.speed is not None else F5_SPEED

    if req.response_format == "pcm":
        async def stream():
            loop = asyncio.get_event_loop()
            sentences = _split_sentences(req.input)
            logger.info(f"🎤 Streaming {len(sentences)} oraciones: '{req.input[:50]}...'")
            for sentence in sentences:
                wav, _ = await loop.run_in_executor(None, _infer, sentence, speed)
                yield _to_pcm_bytes(wav)
                logger.info(f"   ✅ Oración lista: '{sentence[:40]}'")

        return StreamingResponse(stream(), media_type="application/octet-stream")

    else:
        loop = asyncio.get_event_loop()
        logger.info(f"🎤 Generando WAV: '{req.input[:60]}'")
        wav, sr = await loop.run_in_executor(None, _infer, req.input, speed)
        logger.info(f"✅ WAV generado ({len(wav)} samples, {sr}Hz)")
        return Response(content=_to_wav_bytes(wav, sr), media_type="audio/wav")
