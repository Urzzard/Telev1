import torch
import numpy as np
import logging

logger = logging.getLogger("VAD")

_vad_model = None


def get_vad():
    """Carga el modelo Silero VAD (singleton)"""
    global _vad_model
    
    if _vad_model is None:
        logger.info("⏳ Cargando Silero VAD...")
        try:
            model, _ = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                trust_repo=True
            )
            _vad_model = model
            logger.info("✅ Silero VAD cargado")
        except Exception as e:
            logger.error(f"❌ Error cargando Silero VAD: {e}")
    
    return _vad_model


class VoiceActivityDetector:
    """Detector de voz usando Silero VAD"""
    
    # Silero requiere exactamente 256 samples para 8kHz
    CHUNK_SAMPLES = 256
    # Frames de silencio para dar por terminado el turno (~130ms por frame).
    # Palanca 1 (latencia): 8≈1040ms → 6≈780ms; baja ~260ms de "aire muerto" tras hablar.
    # Si corta a gente que pausa mucho, subir a 7.
    SILENCE_END_FRAMES = 6

    def __init__(self, sample_rate: int = 8000):
        self.sample_rate = sample_rate
        self.model = get_vad()
        # 0.5 (antes 0.3): el ruido/eco tenue (conf ~0.35) disparaba falsa "voz" y cortaba la escucha
        # en ~0.7s → re-prompt inmediato. La voz real sale a 0.76+, así que 0.5 la separa limpio.
        self.threshold = 0.5
        self.reset()
    
    def reset(self):
        """Reinicia el estado"""
        self.audio_buffer = np.array([], dtype=np.float32)
        self.speech_frames = 0
        self.silence_frames = 0
        self.speech_started = False
        self.max_confidence = 0.0
        
        # Reset del estado interno de Silero
        if self.model is not None:
            self.model.reset_states()
    
    def process_chunk(self, audio_bytes: bytes) -> dict:
        """Procesa audio y retorna estado de voz"""
        
        if self.model is None:
            return self._fallback_detection(audio_bytes)
        
        # Convertir bytes a float32
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
        audio_float = audio_np.astype(np.float32) / 32768.0
        
        # Acumular en buffer
        self.audio_buffer = np.concatenate([self.audio_buffer, audio_float])
        
        # Procesar chunks de 256 samples
        is_speech = False
        confidence = 0.0
        
        while len(self.audio_buffer) >= self.CHUNK_SAMPLES:
            chunk = self.audio_buffer[:self.CHUNK_SAMPLES]
            self.audio_buffer = self.audio_buffer[self.CHUNK_SAMPLES:]
            
            try:
                tensor = torch.from_numpy(chunk)
                conf = self.model(tensor, self.sample_rate).item()
                confidence = max(confidence, conf)
                self.max_confidence = max(self.max_confidence, conf)
                
                if conf > self.threshold:
                    is_speech = True
            except Exception as e:
                logger.warning(f"⚠️ Error VAD: {e}")
                return self._fallback_detection(audio_bytes)
        
        # Actualizar contadores
        speech_ended = False
        
        if is_speech:
            self.speech_frames += 1
            self.silence_frames = 0
            if self.speech_frames >= 2 and not self.speech_started:
                self.speech_started = True
        else:
            self.silence_frames += 1
            if self.speech_started and self.silence_frames >= self.SILENCE_END_FRAMES:
                speech_ended = True
        
        return {
            "is_speech": is_speech,
            "confidence": confidence,
            "max_confidence": self.max_confidence,
            "speech_started": self.speech_started,
            "speech_ended": speech_ended,
        }
    
    def _fallback_detection(self, audio_bytes: bytes) -> dict:
        """Detección por volumen (fallback)"""
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
        volume = np.abs(audio_np).mean()
        is_speech = volume > 150
        
        if is_speech:
            self.speech_frames += 1
            self.silence_frames = 0
            if not self.speech_started:
                self.speech_started = True
        else:
            self.silence_frames += 1
        
        return {
            "is_speech": is_speech,
            "confidence": min(volume / 500, 1.0),
            "speech_started": self.speech_started,
            "speech_ended": self.speech_started and self.silence_frames >= 15,
        }