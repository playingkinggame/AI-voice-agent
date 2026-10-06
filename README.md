# AI‑Voice‑Agent / DentalVoice AI  

**An AI‑powered voice receptionist for a dental clinic** – combines **LiveKit**, **Groq** (STT/LLM/TTS) and a small SQLite appointment store.  
Talk to the agent via a web page, the command‑line console, or integrate it into your own telephony system.

---

## Table of Contents  

1. [Features](#features)  
2. [Prerequisites](#prerequisites)  
3. [Installation](#installation)  
4. [Configuration](#configuration)  
5. [Getting Started](#getting-started)  
6. [Running the Web API](#running-the-web-api)  
7. [CLI Commands](#cli-commands)  
8. [API End‑points](#api-end‑points)  
9. [Testing](#testing)  
10. [Project Structure](#project-structure)  
11. [Contributing](#contributing)  

---

## Features  

- **Natural‑language phone receptionist** (voice‑to‑voice) using Groq’s STT, LLM and TTS.  
- **LiveKit integration** – works with LiveKit Cloud or self‑hosted rooms.  
- **SQLite persistence** for appointments (`appointments.db`).  
- **FastAPI web client** (`web/index.html`) that can be opened locally.  
- **Domain‑specific tools** (`tools/dental_tools.py`) for booking, cancelling, and querying clinic info.  
- Simple **CLI** for database management, console chat, and worker control.  

---

## Prerequisites  

- **Python 3.11+**  
- **Git** (to clone the repo)  
- An **OpenAI‑compatible Groq API key** (for STT/LLM/TTS).  
- A **LiveKit server URL + API key/secret** (or use `TTS_PROVIDER=livekit` with LiveKit Cloud).  

---

## Installation  

```bash
# Clone the repository
git clone https://github.com/your‑org/ai-voice-agent.git
cd ai-voice-agent

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
# or, if you prefer PEP‑621:
pip install .
```

---

## Configuration  

All secrets are read from environment variables (loaded automatically from a `.env` file).  
Copy the example and fill in the real values:

```bash
cp .env.example .env
```

### Required variables  

| Variable | Description |
|----------|-------------|
| `LIVEKIT_URL` | Base URL of your LiveKit server (e.g. `wss://demo.livekit.io`) |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | LiveKit credentials |
| `GROQ_API_KEY` | Groq API key |
| `GROQ_MODEL` (optional) | LLM model, default `openai/gpt-oss-120b` |
| `GROQ_STT_MODEL` (optional) | STT model, default `whisper-large-v3-turbo` |
| `GROQ_TTS_MODEL` / `GROQ_TTS_VOICE` (optional) | TTS model & voice, default `canopylabs/orpheus-v1-english` |
| `TTS_PROVIDER` (optional) | `groq` (default) or `livekit` to use LiveKit Cloud TTS |
| `DATABASE_PATH` (optional) | Path to SQLite DB, default `appointments.db` |
| `LOG_LEVEL` (optional) | `INFO`, `DEBUG`, etc. (default `INFO`) |

> **Tip:** Run `python check_tts.py` to verify Groq TTS connectivity before launching the agent.

---

## Getting Started  

```bash
# Initialise the SQLite DB (creates appointments.db)
python main.py init-db
```

### Run the web client  

```bash
python main.py api      # Starts FastAPI on http://127.0.0.1:8000
```

Open a browser and navigate to the address – the page loads `web/index.html` and fetches a short‑lived LiveKit token.

### Run the voice‑agent worker  

*Development (auto‑reload):*

```bash
python main.py dev
```

*Production (single process):*

```bash
python main.py start
```

### Console chat (no audio)  

```bash
python main.py console
```

You can type messages and see the agent’s textual replies – useful for debugging.

---

## CLI Commands  

| Command | Description |
|---------|-------------|
| `init-db` | Create (or reset) the `appointments.db` schema. |
| `list-appointments` | Pretty‑print all stored appointments. |
| `api` | Launch the FastAPI server with the web UI. |
| `dev` | Run the LiveKit worker with hot‑reload (`uvicorn --reload`). |
| `start` | Run the worker in production mode. |
| `console` | Interactive text‑only chat with the agent. |

All commands share the same configuration logic (`voice_agent.config.load_settings`).

---

## API End‑points  

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serves the static web UI (`web/index.html`). |
| `GET` | `/api/health` | `{ "status": "ok" }` – health check. |
| `GET` | `/api/clinic` | Public clinic information (name, location, timings) pulled from `data/clinic_data.json`. |
| `GET` | `/api/token` *(implemented in `api.py` but not shown)* | Returns a short‑lived LiveKit token for the browser client. |

---

## Testing  

The test suite uses the standard library’s `unittest`.

```bash
# Run all tests
python -m unittest discover -s tests -v
```

Tests cover:

- Appointment DB operations (`database/appointments.py`)  
- Dental tools logic (`tools/dental_tools.py`)  
- Knowledge base look‑ups (`tools/knowledge.py`)  

---

## Project Structure  

```
.
├─ .env.example                # Template for environment variables
├─ .gitignore
├─ README.md
├─ api.py                      # FastAPI server
├─ main.py                     # CLI entry point
├─ pyproject.toml / requirements.txt
├─ appointments.db             # SQLite DB (generated)
├─ tts_test.wav                # Sample TTS output (generated by check_tts.py)
├─ data/
│   └─ clinic_data.json        # Clinic facts & treatment list
├─ database/
│   └─ appointments.py         # SQLite persistence layer
├─ tools/
│   ├─ dental_tools.py         # Appointment & info functions (exposed as tools)
│   └─ knowledge.py            # Clinic knowledge base helpers
├─ voice_agent/
│   ├─ agent.py                # LiveKit worker definition
│   ├─ config.py               # Settings loading & validation
│   └─ prompts.py              # System prompt builder
└─ web/
    └─ index.html              # Simple web UI
```

---

## Contributing  

1. Fork the repo and create a feature branch.  
2. Keep the code style consistent (PEP 8, type hints).  
3. Add or extend unit tests for new functionality.  
4. Submit a pull request with a clear description of changes.  

---

**Enjoy building smarter dental front‑desks!**
