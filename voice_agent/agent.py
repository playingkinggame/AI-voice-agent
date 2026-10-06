"""LiveKit voice agent: Groq STT + Groq LLM + Groq TTS with dental tools."""
from __future__ import annotations

import asyncio
import json
import logging

from livekit.agents import (
    Agent,
    inference,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.plugins import groq, silero

from tools import dental_tools
from tools.knowledge import fmt_time
from voice_agent.config import Settings, get_settings, setup_logging
from voice_agent.prompts import build_system_prompt

logger = logging.getLogger("dentalvoice.agent")


def build_tts(settings: Settings):
    """Groq Orpheus by default; TTS_PROVIDER=livekit uses LiveKit Cloud's built-in voices."""
    if settings.tts_provider == "livekit":
        logger.info("Using LiveKit Inference TTS (%s)", settings.tts_inference_model)
        return inference.TTS(model=settings.tts_inference_model, voice=settings.tts_inference_voice)
    logger.info("Using Groq TTS (%s / %s)", settings.groq_tts_model, settings.groq_tts_voice)
    return groq.TTS(model=settings.groq_tts_model, voice=settings.groq_tts_voice)


async def _run_tool(fn, *args, **kwargs) -> str:
    """Run a (blocking, never-raising) tool in a thread and return JSON for the LLM."""
    result = await asyncio.to_thread(fn, *args, **kwargs)
    return json.dumps(result, ensure_ascii=False)


class DentalReceptionist(Agent):
    def __init__(self, settings: Settings):
        service = dental_tools.get_service()
        now = service.now()
        today_text = f"{now.strftime('%A, %d %B %Y')}, {fmt_time(now.time())} ({settings.timezone})"
        super().__init__(
            instructions=build_system_prompt(
                service.kb.name, service.kb.data["clinic"].get("receptionist_name", "Priya"), today_text
            )
        )
        self.clinic_name = service.kb.name

    @function_tool()
    async def check_availability(self, context: RunContext, date: str, time: str = "") -> str:
        """Check open appointment times. Call this before saying any time is available.

        Args:
            date: Appointment date as YYYY-MM-DD (or the words today / tomorrow).
            time: Optional specific time to check, like "4 PM" or "16:30". Leave empty to list open times.
        """
        return await _run_tool(dental_tools.check_availability, date, time)

    @function_tool()
    async def book_appointment(
        self,
        context: RunContext,
        patient_name: str,
        phone: str,
        treatment: str,
        date: str,
        time: str,
        email: str = "",
        notes: str = "",
    ) -> str:
        """Book an appointment. Only call after collecting all details and confirming the phone number.

        Args:
            patient_name: Patient's full name.
            phone: 10-digit Indian mobile number.
            treatment: Treatment name such as "root canal" or "Dental Consultation".
            date: Appointment date as YYYY-MM-DD.
            time: Appointment time such as "4 PM" or "16:00".
            email: Optional email address.
            notes: Optional notes, such as the patient's reason for visiting.
        """
        return await _run_tool(dental_tools.book_appointment, patient_name, phone, treatment, date, time, email, notes)

    @function_tool()
    async def cancel_appointment(self, context: RunContext, appointment_id: int, phone: str) -> str:
        """Cancel an existing appointment.

        Args:
            appointment_id: The numeric appointment ID.
            phone: The phone number used when booking.
        """
        return await _run_tool(dental_tools.cancel_appointment, appointment_id, phone)

    @function_tool()
    async def reschedule_appointment(
        self, context: RunContext, appointment_id: int, phone: str, new_date: str, new_time: str
    ) -> str:
        """Move an existing appointment to a new date and time.

        Args:
            appointment_id: The numeric appointment ID.
            phone: The phone number used when booking.
            new_date: New date as YYYY-MM-DD.
            new_time: New time such as "5 PM" or "17:00".
        """
        return await _run_tool(dental_tools.reschedule_appointment, appointment_id, phone, new_date, new_time)

    @function_tool()
    async def get_appointment(self, context: RunContext, phone: str, appointment_id: int = 0) -> str:
        """Look up a patient's upcoming confirmed appointments.

        Args:
            phone: The phone number used when booking.
            appointment_id: Optional appointment ID; use 0 if unknown.
        """
        return await _run_tool(dental_tools.get_appointment, phone, appointment_id or None)

    @function_tool()
    async def get_treatment_price(self, context: RunContext, treatment: str) -> str:
        """Get the approximate price of a dental treatment from the clinic price list.

        Args:
            treatment: Treatment name, for example "root canal", "cleaning" or "braces".
        """
        return await _run_tool(dental_tools.get_treatment_price, treatment)

    @function_tool()
    async def get_clinic_information(self, context: RunContext, topic: str, question: str = "") -> str:
        """Get clinic information: timings, location, treatments, emergency, what_to_bring, or FAQ answers.

        Args:
            topic: One of timings, location, treatments, emergency, what_to_bring, about, or faq.
            question: The patient's original question (used to search FAQs).
        """
        return await _run_tool(dental_tools.get_clinic_information, topic, question)

    @function_tool()
    async def get_current_datetime(self, context: RunContext) -> str:
        """Get the current date and time at the clinic."""
        return await _run_tool(dental_tools.get_current_datetime)


def prewarm(proc: JobProcess) -> None:
    setup_logging(get_settings().log_level)
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    settings = get_settings()
    logger.info("Agent started for room '%s'", ctx.room.name)

    try:
        await ctx.connect()
    except Exception:
        logger.exception("Could not connect to LiveKit. Check LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET")
        raise
    logger.info("Connected to LiveKit")

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=groq.STT(model=settings.groq_stt_model, language=settings.stt_language),
        llm=groq.LLM(model=settings.groq_model, temperature=0.3),
        tts=build_tts(settings),
    )

    @session.on("error")
    def _on_error(ev) -> None:  # Groq / audio pipeline errors
        logger.error("Voice session error: %s", getattr(ev, "error", ev))

    @session.on("close")
    def _on_close(ev) -> None:
        logger.info("Voice session closed")

    agent = DentalReceptionist(settings)
    await session.start(room=ctx.room, agent=agent)

    try:
        await session.generate_reply(
            instructions=(
                f"Greet the caller warmly as the receptionist of {agent.clinic_name} and ask how you can help. "
                "Keep it to one short sentence."
            )
        )
    except Exception:
        logger.exception("Groq LLM greeting failed; using fallback greeting")
        try:
            await session.say(f"Hello, welcome to {agent.clinic_name}. How can I help you today?")
        except Exception:
            logger.exception("Fallback greeting also failed")


def run_worker() -> None:
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
