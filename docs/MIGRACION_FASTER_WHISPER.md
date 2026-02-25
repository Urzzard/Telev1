# Migración Whisper → Faster Whisper

## Estado: ✅ COMPLETADO

> Migración implementada exitosamente. VRAM reducida de ~10.5GB a ~9.5GB.

---

## Contexto

- **Hardware**: RTX 5080 con 16GB VRAM
- **VRAM actual en uso**: ~9GB (incluso ~10GB durante llamadas)
- **Problema a resolver**: Latencia en transcripción, alto consumo de VRAM

---

## Análisis: Whisper vs Faster Whisper

### Faster Whisper - Beneficios

| Aspecto | Whisper actual | Faster Whisper |
|---------|---------------|----------------|
| **Velocidad** | baseline | ~4x más rápido |
| **VRAM (small)** | ~2.5GB | ~1GB |
| **VRAM (medium)** | ~5GB | ~3GB |
| **Dependencias** | ffmpeg obligatorio | no requiere ffmpeg |
| **Motor** | PyTorch | CTranslate2 |

### VRAM Estimada después de migración

| Modelo | VRAM estimada | VRAM libre |
|--------|---------------|------------|
| small | ~1GB | ~5-6GB |
| medium | ~3GB | ~3-4GB |

---

## Ubicación de archivos relevantes

### STT Principal
- **Archivo**: `backend/app/stt.py` (147 líneas)
- **Clase**: `SpeechToText`
- **Patrón**: Singleton (`get_stt()`)

### Integración en call_agent.py
- `_detectar_buzon()` - línea 682
- `_escuchar_respuesta()` - línea 847

### Dependencias
- `backend/requirements.txt` - línea 7: `openai-whisper`
- `backend/Dockerfile` - línea 11: `ffmpeg`

### Variables de entorno
- `WHISPER_MODEL` = "small"
- `WHISPER_DEVICE` = "cuda"
- Volumen: `whisper_cache:/root/.cache/whisper`

---

## Plan de Implementación

### 1. Dependencias (`backend/requirements.txt`)

```diff
- openai-whisper
+ faster-whisper
```

### 2. Código (`backend/app/stt.py`)

Cambios en la clase `SpeechToText`:

```python
# Antes (openai-whisper)
import whisper
self.model = whisper.load_model(self.model_size, device=self.device)
result = self.model.transcribe(tmp_file, fp16=..., language="es", ...)
texto = result["text"].strip()

# Después (faster-whisper)
from faster_whisper import WhisperModel
self.model = WhisperModel(
    self.model_size, 
    device="cuda", 
    compute_type="float16"  # o "int8" para menos VRAM
)
segments, info = self.model.transcribe(
    tmp_file,
    language="es",
    beam_size=5
)
texto = " ".join([s.text for s in segments]).strip()
```

**Importante**: Mantener los filtros de alucinaciones existentes en `_es_texto_valido()`.

### 3. Dockerfile

Opcional: remover ffmpeg ya que faster-whisper decodifica audio con Python.

### 4. Docker Compose

- `whisper_cache` puede eliminarse (faster-whisper maneja su propio cache)

---

## Opciones de modelo

### Recomendación para tu hardware (RTX 5080 16GB):

1. **Opción segura**: `small` → ~1GB VRAM
   - Ahorro: ~1.5GB vs actual
   - Velocidad: 4x más rápido

2. **Opción calidad**: `medium` → ~3GB VRAM
   - Mejor calidad que small
   - VRAM libre: ~3-4GB para otros servicios

3. **Opción premium**: `distil-large-v2` + int8 → ~3-4GB
   - Mejor calidad con VRAM similar a medium

---

## Tests a realizar post-migración

1. Verificar que el modelo carga correctamente
2. Probar transcripción con audio de prueba
3. **Llamada real**: verificar latencia
4. **VRAM**: monitorear consumo durante llamada
5. Verificar filtros de alucinaciones funcionan igual

---

## Notas

- Faster Whisper NO requiere ffmpeg instalado en el sistema
- El prompt de contexto (empresa, horario, etc.) se pasa igual que antes
- Los filtros de alucinaciones deben portarse manualmente
- Compatible con modelos original Whisper (tiny, base, small, medium, large-v2/v3)
