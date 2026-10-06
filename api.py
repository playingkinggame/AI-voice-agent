"""Small FastAPI server so you can talk to the agent from your browser.

Serves web/index.html and issues short-lived LiveKit tokens at /api/token.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from livekit import api as lk_api

from tools.knowledge import ClinicKnowledge
from voice_agent.config import ConfigError, load_settings

logger = logging.getLogger("dentalvoice.api")
app = FastAPI(title="DentalVoice AI web client")
WEB_DIR = Path(__file__).resolve().parent / "web"


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/clinic")
async def clinic():
    """Public clinic info for the website, straight from data/clinic_data.json."""
    kb = ClinicKnowledge(load_settings(require_livekit=False, require_groq=False).clinic_data_path)
    return {
        "name": kb.name,
        "location": kb.location,
        "timings": kb.timings_text(),
        "disclaimer": kb.data["price_disclaimer"],
        "treatments": [
            {"name": t["name"], "price": kb.price_text(t).replace("around ", "").replace(" rupees", ""),
             "description": t.get("description", "")}
            for t in kb.treatments
        ],
    }


@app.get("/api/token")
async def token(name: str = "Patient"):
    try:
        settings = load_settings(require_livekit=True, require_groq=False)
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    room = f"dental-{uuid.uuid4().hex[:8]}"
    identity = f"patient-{uuid.uuid4().hex[:6]}"
    jwt = (
        lk_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(name[:40] or "Patient")
        .with_grants(lk_api.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )
    logger.info("Issued token for room %s", room)
    return {"url": settings.livekit_url, "token": jwt, "room": room}
