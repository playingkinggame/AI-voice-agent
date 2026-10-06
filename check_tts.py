"""Shows Groq's REAL text-to-speech error message (LiveKit hides it).

Run:  python check_tts.py
"""
import json
import sys
import urllib.error
import urllib.request

from voice_agent.config import ConfigError, load_settings

try:
    s = load_settings(require_livekit=False, require_groq=True)
except ConfigError as exc:
    sys.exit(f"CONFIG ERROR: {exc}")

body = json.dumps({
    "model": s.groq_tts_model, "voice": s.groq_tts_voice,
    "input": "Hello, this is a test.", "response_format": "wav",
}).encode()
req = urllib.request.Request(
    "https://api.groq.com/openai/v1/audio/speech", data=body, method="POST",
    headers={"Authorization": f"Bearer {s.groq_api_key}", "Content-Type": "application/json",
             "User-Agent": "dentalvoice-check/1.0"},
)
print(f"Testing model={s.groq_tts_model} voice={s.groq_tts_voice} ...")
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
        open("tts_test.wav", "wb").write(data)
        print(f"SUCCESS: Groq TTS works ({len(data)} bytes saved to tts_test.wav).")
        print("The problem is then in the LiveKit plugin settings - set TTS_PROVIDER=livekit in .env.")
except urllib.error.HTTPError as e:
    print(f"FAILED: HTTP {e.code}")
    print(e.read().decode(errors="replace"))
    print("\nIf the message mentions 'terms', accept them at https://console.groq.com/playground (Text to Speech).")
    print("Otherwise set TTS_PROVIDER=livekit in .env to use LiveKit's built-in voice instead.")
except Exception as e:  # network etc.
    print("FAILED:", e)
