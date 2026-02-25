# AGENTS.md - Agent Coding Guidelines

This document provides guidelines for agents working on this codebase.

**Language**: This file is in English only.

---

## Project Overview

**Telefonista AI** - Automatic call assistant for onboarding new collaborators at Salesland.

### System Architecture

| Component | Technology | Function |
|-----------|------------|----------|
| **sip-service** | Baresip (SIP client) + bridge.py (Python) | Phone call handling |
| **SIP Provider** | External server at `149.56.244.21` | Carries calls |
| **backend** | FastAPI + Python | Orchestration, STT, LLM, TTS |
| **STT** | Faster Whisper (CTranslate2) | Speech recognition |
| **LLM** | Ollama (local model) | Response generation |
| **TTS** | Coqui XTTS | Voice synthesis |
| **DB** | PostgreSQL | Stores employees and calls |

### Call Flow

1. **Scheduler** → Detects pending employees in PostgreSQL
2. **Backend** → Receives request, fetches employee data
3. **SIP Service (bridge.py)** → Sends dial command to Baresip
4. **Baresip** → Makes call via external SIP provider
5. **bridge.py** → Detects state (dialing → established)
6. **WebSocket** → Connects bidirectional audio with backend
7. **Backend** → Faster Whisper → Ollama → XTTS → audio back

### Project Services
- **backend/**: FastAPI server with STT, LLM, TTS (Python)
- **sip-service/**: Baresip + bridge.py for SIP calls
- **xtts-service/**: Coqui XTTS text-to-speech service
- **gemini-tts/**: Google Gemini TTS service (currently unused)

The system uses Docker Compose to orchestrate all services with PostgreSQL.

---

## Build & Run Commands

### Running the Full Stack

```bash
# Start all services
docker-compose up -d

# Start with rebuild
docker-compose up -d --build

# View logs
docker-compose logs -f

# Stop all services
docker-compose down
```

### Individual Services

```bash
# Backend (runs on port 5000)
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# SIP Service (runs on port 8000)
cd sip-service && python bridge.py

# XTTS Service (runs on port 8020)
cd xtts-service && python server.py
```

### Dependencies

```bash
# Backend dependencies
pip install -r backend/requirements.txt

# Install in development mode (if available)
pip install -e .
```

---

## Testing

**No test framework is currently set up.** To add tests:

```bash
# Install pytest
pip install pytest pytest-asyncio

# Run all tests
pytest

# Run a single test file
pytest tests/test_llm.py

# Run a single test function
pytest tests/test_llm.py::test_something_specific -v
```

---

## Code Style Guidelines

### General Principles

- **Language**: Python (3.10+)
- **Framework**: FastAPI with async/await
- **Architecture**: Service-oriented with clear separation (app/* modules)

### Imports

```python
# Standard library first
import asyncio
import logging
import re

# Third-party packages
import requests
import numpy as np
from fastapi import FastAPI

# Local application imports (use relative imports within packages)
from app.llm import get_llm
from app.stt import get_stt
```

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Variables | snake_case | `employee_id`, `current_call_id` |
| Functions | snake_case | `get_llm()`, `_obtener_empleado_postgres()` |
| Classes | PascalCase | `CallAgent`, `LLMClient`, `TextToSpeech` |
| Constants | UPPER_SNAKE_CASE | `MAX_CHARS`, `BYTES_PER_SECOND` |
| Private functions | prefix with `_` | `_helper_function()` |

### Type Annotations

Use type hints for function parameters and return values:

```python
# Good
def make_call(id: int) -> dict:
    employee: dict = get_employee(id)
    return {"status": "calling", "id": id}

# Async functions
async def process_audio(websocket: WebSocket, duracion: int = 0) -> None:
```

### Error Handling

Use try/except blocks with specific exception types:

```python
# Good - specific exception handling
try:
    response = requests.get(url, timeout=2)
except requests.exceptions.RequestException as e:
    logger.error(f"Error connecting: {e}")
    raise HTTPException(status_code=500, detail=str(e))

# Use HTTPException for API errors
raise HTTPException(status_code=404, detail="Employee not found")
```

### Logging

Use the logging module with appropriate levels:

```python
logger = logging.getLogger(__name__)

logger.info("Starting service...")
logger.warning(f"Warning: {detail}")
logger.error(f"Error: {e}")
logger.debug(f"Debug info: {data}")
```

### Async/Await

- Use `async def` for functions that do I/O operations
- Use `asyncio` for concurrent operations
- Always handle `CancelledError` in finally blocks:

```python
try:
    await some_async_task()
except asyncio.CancelledError:
    pass  # Clean cancellation
finally:
    await cleanup()
```

### Database Operations

- Use SQLAlchemy for database abstraction
- Always close connections in finally blocks or use context managers:

```python
pg = get_postgres_db()
try:
    if pg.connect():
        with pg.get_cursor() as cur:
            cur.execute("SELECT * FROM empleados WHERE id = %s", (id,))
            result = cur.fetchone()
finally:
    pg.disconnect()
```

### Configuration

- Use environment variables for all configuration
- Never hardcode credentials or URLs
- Use `.env` file for local development (already in `.gitignore`)

### Code Formatting

- Use **Black** for code formatting (line length: 100)
- Use **isort** for import sorting
- Use **ruff** for linting (optional, not currently enforced)

```bash
# If you add these tools
black .
isort .
ruff check .
```

---

## Common Patterns

### Singleton Pattern

Use module-level singletons for shared resources:

```python
_llm_instance = None

def get_llm():
    """Returns singleton LLM instance"""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = LLMClient()
    return _llm_instance
```

### FastAPI Lifespan

Use the lifespan context manager for startup/shutdown:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    initialize_services()
    yield
    # Shutdown
    await cleanup()
```

### WebSocket Handling

Always handle `WebSocketDisconnect`:

```python
try:
    await agent.iniciar_conversacion()
except WebSocketDisconnect:
    logger.info("Socket disconnected")
except Exception as e:
    logger.error(f"Error: {e}")
finally:
    try:
        await websocket.close()
    except:
        pass
```

---

## File Structure

```
/home/usuario/DEV/Telev1/
├── backend/
│   ├── main.py              # FastAPI app entry point
│   ├── scheduler.py         # Background job scheduler
│   ├── requirements.txt     # Python dependencies
│   ├── Dockerfile
│   └── app/
│       ├── llm.py           # LLM client (Ollama)
│       ├── stt.py           # Speech-to-text (Faster Whisper)
│       ├── tts.py           # Text-to-speech
│       ├── vad.py           # Voice activity detection
│       ├── call_agent.py    # Main call handling logic
│       ├── intent_detector.py
│       ├── prompts.py
│       ├── database.py
│       ├── postgres_db.py
│       ├── sqlserver_db.py
│       └── states.py
├── sip-service/
│   ├── bridge.py           # Python bridge for audio and control
│   ├── config              # Baresip configuration
│   ├── accounts            # SIP credentials
│   ├── entrypoint.sh       # Startup script
│   └── Dockerfile
├── xtts-service/
├── gemini-tts/
├── docs/                    # Analysis and planning documents
├── database/
│   ├── init.sql
│   └── data/
└── docker-compose.yml
```

### SIP Service Details

The **sip-service** uses:
- **Baresip**: SIP client compiled from source
- **PulseAudio**: Audio server for stream handling
- **bridge.py**: Python script that:
  - Monitors call states (IDLE, DIALING, ESTABLISHED)
  - Controls Baresip via HTTP
  - Transmits bidirectional audio via WebSocket
  - Handles dial timeouts

**Configured SIP account**: `testsales@149.56.244.21`

**Call states**:
- `IDLE`: No active call
- `DIALING`: Dialing (EARLY)
- `ESTABLISHED`: Call established (answered or voicemail)

---

## Environment Variables

Key environment variables (see `.env`):

| Variable | Description |
|----------|-------------|
| `OLLAMA_URL` | Ollama LLM server URL |
| `TTS_BACKEND` | TTS backend to use (xtts/gemini) |
| `XTTS_URL` | XTTS service URL |
| `POSTGRES_HOST` | PostgreSQL host |
| `SQLSERVER_HOST` | SQL Server host |
| `WHISPER_MODEL` | Whisper model size |
| `WHISPER_DEVICE` | Device for Whisper (cuda/cpu) |
| `SIP_URL` | SIP service URL |

---

## Notes

- **Language**: This file must be in English only (for agent compatibility)
- Faster Whisper does not require ffmpeg installed (can be removed from Dockerfile)
- The volume `whisper_cache` is no longer needed (faster-whisper handles its own cache)
- This is a telephony system - changes may affect live call handling
- The backend exposes WebSocket at `/ws/audio` for real-time audio streaming
- The scheduler runs in a separate container to make periodic calls
- Audio processing uses scipy and numpy
