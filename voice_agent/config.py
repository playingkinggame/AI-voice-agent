"""Configuration loading and validation for DentalVoice AI.

All secrets come from environment variables (loaded from a local .env file).
Secrets are never logged.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _clean(value: str | None) -> str:
    return (value or "").strip().strip('"').strip("'")


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return (not value) or lowered.startswith("your_") or "your-project-id" in lowered


class Settings(BaseModel):
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_stt_model: str = "whisper-large-v3-turbo"
    groq_tts_model: str = "canopylabs/orpheus-v1-english"
    groq_tts_voice: str = "autumn"
    stt_language: str = "en"
    tts_provider: str = "groq"
    tts_inference_model: str = "cartesia/sonic-2"
    tts_inference_voice: str = "794f9389-aac1-45b6-b726-9d9369183238"
    timezone: str = "Asia/Kolkata"
    log_level: str = "INFO"
    clinic_data_path: Path = PROJECT_ROOT / "data" / "clinic_data.json"
    database_path: Path = PROJECT_ROOT / "appointments.db"


def load_settings(require_livekit: bool = True, require_groq: bool = True) -> Settings:
    """Build Settings from the environment and validate required values."""
    env = os.environ
    settings = Settings(
        livekit_url=_clean(env.get("LIVEKIT_URL")),
        livekit_api_key=_clean(env.get("LIVEKIT_API_KEY")),
        livekit_api_secret=_clean(env.get("LIVEKIT_API_SECRET")),
        groq_api_key=_clean(env.get("GROQ_API_KEY")),
        groq_model=_clean(env.get("GROQ_MODEL")) or "openai/gpt-oss-120b",
        groq_stt_model=_clean(env.get("GROQ_STT_MODEL")) or "whisper-large-v3-turbo",
        groq_tts_model=_clean(env.get("GROQ_TTS_MODEL")) or "canopylabs/orpheus-v1-english",
        groq_tts_voice=_clean(env.get("GROQ_TTS_VOICE")) or "autumn",
        stt_language=_clean(env.get("STT_LANGUAGE")) or "en",
        tts_provider=(_clean(env.get("TTS_PROVIDER")) or "groq").lower(),
        tts_inference_model=_clean(env.get("TTS_INFERENCE_MODEL")) or "cartesia/sonic-2",
        tts_inference_voice=_clean(env.get("TTS_INFERENCE_VOICE")) or "794f9389-aac1-45b6-b726-9d9369183238",
        timezone=_clean(env.get("CLINIC_TIMEZONE")) or "Asia/Kolkata",
        log_level=(_clean(env.get("LOG_LEVEL")) or "INFO").upper(),
        clinic_data_path=Path(_clean(env.get("CLINIC_DATA_PATH")) or PROJECT_ROOT / "data" / "clinic_data.json"),
        database_path=Path(_clean(env.get("DATABASE_PATH")) or PROJECT_ROOT / "appointments.db"),
    )

    required: list[str] = []
    if require_livekit:
        required += ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"]
    if require_groq:
        required += ["GROQ_API_KEY"]

    values = {
        "LIVEKIT_URL": settings.livekit_url,
        "LIVEKIT_API_KEY": settings.livekit_api_key,
        "LIVEKIT_API_SECRET": settings.livekit_api_secret,
        "GROQ_API_KEY": settings.groq_api_key,
    }
    missing = [name for name in required if _is_placeholder(values[name])]
    if missing:
        raise ConfigError(
            "Missing or placeholder environment variable(s): "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill in real values."
        )
    if require_livekit and not settings.livekit_url.startswith(("ws://", "wss://", "http://", "https://")):
        raise ConfigError("LIVEKIT_URL must start with wss:// (for example wss://your-project.livekit.cloud).")
    if not settings.clinic_data_path.exists():
        raise ConfigError(f"Clinic data file not found: {settings.clinic_data_path}")
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings used by the running agent."""
    return load_settings()


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
