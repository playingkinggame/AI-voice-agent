"""DentalVoice AI entry point.

Usage (Windows PowerShell or any shell):
    python main.py init-db            Create appointments.db
    python main.py list-appointments  Show stored appointments
    python main.py api                Browser test page on http://127.0.0.1:8000
    python main.py dev                Run the voice agent worker (auto-reload)
    python main.py start              Run the voice agent worker (production mode)
    python main.py console            Talk to the agent in your terminal
"""
from __future__ import annotations

import sys

from voice_agent.config import ConfigError, load_settings, setup_logging

USAGE = __doc__


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""

    if command in {"", "-h", "--help", "help"}:
        print(USAGE)
        return 0

    try:
        if command in {"init-db", "list-appointments"}:
            settings = load_settings(require_livekit=False, require_groq=False)
            setup_logging(settings.log_level)
            from database.appointments import AppointmentDB

            db = AppointmentDB(settings.database_path)
            db.init_db()
            if command == "init-db":
                print(f"Database ready: {settings.database_path}")
            else:
                rows = db.list_all()
                if not rows:
                    print("No appointments yet.")
                for r in rows:
                    print(f"#{r['id']} {r['appointment_date']} {r['appointment_time']} "
                          f"{r['patient_name']} ({r['phone']}) - {r['treatment']} [{r['status']}]")
            return 0

        if command == "api":
            settings = load_settings(require_livekit=True, require_groq=False)
            setup_logging(settings.log_level)
            import uvicorn

            print("Open http://127.0.0.1:8000 in your browser (the agent worker must be running too).")
            uvicorn.run("api:app", host="127.0.0.1", port=8000)
            return 0

        # Everything else (dev / start / console / connect ...) is handled by the LiveKit CLI.
        settings = load_settings(require_livekit=True, require_groq=True)
        setup_logging(settings.log_level)
        from voice_agent.agent import run_worker

        run_worker()
        return 0
    except ConfigError as exc:
        print(f"CONFIGURATION ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
