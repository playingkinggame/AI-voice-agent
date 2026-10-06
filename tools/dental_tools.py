"""Appointment and clinic-information tools used by the voice agent.

Every public function returns a plain dict and NEVER raises: errors become
{"success": False, "message": "..."} so the agent can explain them honestly.
"""
from __future__ import annotations

import functools
import logging
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from database.appointments import (
    AppointmentDB,
    AppointmentError,
    ValidationError,
)
from tools.knowledge import ClinicKnowledge, fmt_time

logger = logging.getLogger("dentalvoice.tools")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --------------------------------------------------------------------------
# Parsing / validation helpers
# --------------------------------------------------------------------------
def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        raise ValidationError(
            "That phone number doesn't look right. I need a valid 10-digit Indian mobile number."
        )
    return digits


def validate_name(raw: str) -> str:
    name = re.sub(r"\s+", " ", (raw or "").strip())
    if len(name) < 2 or not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", name):
        raise ValidationError("I need the patient's full name, using letters only.")
    return name.title()


def validate_email(raw: str) -> str:
    email = (raw or "").strip()
    if email and not _EMAIL_RE.match(email):
        raise ValidationError("That email address doesn't look valid. We can also skip the email if you prefer.")
    return email


def parse_date(raw: str, today: date) -> date:
    text = (raw or "").strip().lower()
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValidationError("I couldn't understand that date. Could you tell me the day and month again?")


def parse_time(raw: str) -> time:
    text = (raw or "").strip().lower().replace(".", "")
    if text in {"noon", "midday"}:
        return time(12, 0)
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if not match:
        raise ValidationError("I couldn't understand that time. Could you say it like 4 PM or 4:30 PM?")
    hour, minute, meridian = int(match.group(1)), int(match.group(2) or 0), match.group(3)
    if minute > 59 or hour > 23:
        raise ValidationError("That isn't a valid time. Could you say it again?")
    if meridian == "pm" and hour < 12:
        hour += 12
    elif meridian == "am" and hour == 12:
        hour = 0
    elif meridian is None and 1 <= hour <= 8:
        hour += 12  # clinic hours run 9 AM - 8 PM, so a bare "4" means 4 PM
    return time(hour, minute)


def _fail(message: str, **extra) -> dict:
    return {"success": False, "message": message, **extra}


def _safe(func):
    """Convert any exception into a patient-friendly failure dict."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AppointmentError as exc:
            logger.warning("%s failed: %s", func.__name__, exc.user_message)
            return _fail(exc.user_message)
        except Exception:  # noqa: BLE001 - last line of defence for the voice call
            logger.exception("Unexpected error in %s", func.__name__)
            return _fail("Something went wrong on my side. Please try again in a moment.")

    return wrapper


# --------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------
class DentalService:
    def __init__(self, knowledge: ClinicKnowledge, db: AppointmentDB, timezone: str = "Asia/Kolkata"):
        self.kb = knowledge
        self.db = db
        self.tz = ZoneInfo(timezone)
        booking = knowledge.booking
        self.slot_minutes = int(booking.get("slot_minutes", 30))
        self.capacity = int(booking.get("dentists_available", 1))
        self.max_advance_days = int(booking.get("max_advance_days", 60))
        self.min_lead = timedelta(minutes=int(booking.get("min_lead_minutes", 30)))

    def now(self) -> datetime:
        return datetime.now(self.tz)

    # ---- slot logic -------------------------------------------------------
    def _all_slots(self, day: date) -> list[time]:
        hours = self.kb.hours_for(day)
        if hours is None:
            return []
        opening, closing = hours
        step = timedelta(minutes=self.slot_minutes)
        cursor = datetime.combine(day, opening)
        last_start = datetime.combine(day, closing) - step
        slots = []
        while cursor <= last_start:
            slots.append(cursor.time())
            cursor += step
        return slots

    def _validate_day(self, day: date) -> None:
        now = self.now()
        if day < now.date():
            raise ValidationError("That date has already passed. Which upcoming date would you like?")
        if day > now.date() + timedelta(days=self.max_advance_days):
            raise ValidationError(
                f"We can only book up to {self.max_advance_days} days ahead. Could you pick an earlier date?"
            )
        if self.kb.hours_for(day) is None:
            raise ValidationError("The clinic is closed on that day. Would you like another day?")

    def _open_slots(self, day: date) -> list[time]:
        booked = self.db.booked_counts(day.isoformat())
        now = self.now()
        free = []
        for slot in self._all_slots(day):
            if booked.get(slot.strftime("%H:%M"), 0) >= self.capacity:
                continue
            if datetime.combine(day, slot, tzinfo=self.tz) < now + self.min_lead:
                continue
            free.append(slot)
        return free

    def _validate_slot(self, day: date, slot: time) -> None:
        self._validate_day(day)
        if slot not in self._all_slots(day):
            opening, closing = self.kb.hours_for(day)  # type: ignore[misc]
            raise ValidationError(
                f"We take appointments on the half hour between {fmt_time(opening)} and "
                f"{fmt_time(closing)} on that day. Could you choose a time in that range?"
            )
        if datetime.combine(day, slot, tzinfo=self.tz) < self.now() + self.min_lead:
            raise ValidationError("That time is too soon or has already passed. Could you choose a later time?")

    # ---- tools ------------------------------------------------------------
    def check_availability(self, date_str: str, time_str: str = "") -> dict:
        logger.info("Checking appointment availability")
        day = parse_date(date_str, self.now().date())
        self._validate_day(day)
        free = self._open_slots(day)
        day_label = day.strftime("%A, %d %B %Y")
        result: dict = {
            "success": True,
            "date": day.isoformat(),
            "day": day_label,
            "available_times": [fmt_time(s) for s in free][:10],
            "total_open_slots": len(free),
        }
        if time_str.strip():
            slot = parse_time(time_str)
            self._validate_slot(day, slot)
            ok = slot in free
            result["requested_time"] = fmt_time(slot)
            result["requested_time_available"] = ok
            if ok:
                result["message"] = f"{fmt_time(slot)} on {day_label} is available."
            else:
                nearest = sorted(free, key=lambda s: abs(
                    datetime.combine(day, s) - datetime.combine(day, slot)))[:3]
                result["nearest_available"] = [fmt_time(s) for s in sorted(nearest)]
                result["message"] = (
                    f"{fmt_time(slot)} on {day_label} is not available."
                    + (f" Nearby open times: {', '.join(result['nearest_available'])}." if nearest else
                       " There are no open slots left that day.")
                )
        elif free:
            result["message"] = f"Open times on {day_label} include: {', '.join(result['available_times'])}."
        else:
            result["message"] = f"There are no open slots on {day_label}."
        return result

    def book_appointment(
        self, patient_name: str, phone: str, treatment: str, date_str: str, time_str: str,
        email: str = "", notes: str = "",
    ) -> dict:
        logger.info("Booking appointment request received")
        name = validate_name(patient_name)
        phone_n = normalize_phone(phone)
        email_n = validate_email(email)
        t = self.kb.find_treatment(treatment or "Dental Consultation")
        if t is None:
            raise ValidationError(
                "I couldn't match that to one of our treatments. We offer: "
                + ", ".join(self.kb.treatment_names()) + "."
            )
        day = parse_date(date_str, self.now().date())
        slot = parse_time(time_str)
        self._validate_slot(day, slot)
        created = self.db.create(
            patient_name=name, phone=phone_n, email=email_n, treatment=t["name"],
            day=day.isoformat(), slot=slot.strftime("%H:%M"), notes=(notes or "").strip()[:500],
            created_at=self.now().isoformat(timespec="seconds"), capacity=self.capacity,
        )
        logger.info("Appointment booked successfully (id=%s)", created["id"])
        return {
            "success": True,
            "appointment_id": created["id"],
            "appointment": self._describe(created),
            "message": (
                f"Appointment confirmed. ID {created['id']} for {created['patient_name']}, "
                f"{created['treatment']} on {day.strftime('%A, %d %B %Y')} at {fmt_time(slot)}."
            ),
        }

    def get_appointment(self, phone: str, appointment_id: int | None = None) -> dict:
        logger.info("Looking up appointment")
        phone_n = normalize_phone(phone)
        if appointment_id:
            row = self.db.get_by_id(int(appointment_id))
            rows = [row] if row and row["phone"] == phone_n and row["status"] == "confirmed" else []
        else:
            rows = self.db.find_by_phone(phone_n, from_date=self.now().date().isoformat())
        if not rows:
            return _fail("I couldn't find any upcoming confirmed appointment for those details.", appointments=[])
        described = [self._describe(r) for r in rows]
        return {"success": True, "appointments": described,
                "message": f"Found {len(described)} upcoming appointment(s)."}

    def cancel_appointment(self, appointment_id: int, phone: str) -> dict:
        logger.info("Cancelling appointment")
        updated = self.db.cancel(int(appointment_id), normalize_phone(phone))
        logger.info("Appointment cancelled successfully (id=%s)", updated["id"])
        return {"success": True, "appointment_id": updated["id"],
                "message": f"Appointment {updated['id']} has been cancelled."}

    def reschedule_appointment(self, appointment_id: int, phone: str, new_date: str, new_time: str) -> dict:
        logger.info("Rescheduling appointment")
        phone_n = normalize_phone(phone)
        day = parse_date(new_date, self.now().date())
        slot = parse_time(new_time)
        self._validate_slot(day, slot)
        updated = self.db.reschedule(
            int(appointment_id), phone_n, day.isoformat(), slot.strftime("%H:%M"), self.capacity
        )
        logger.info("Appointment rescheduled successfully (id=%s)", updated["id"])
        return {
            "success": True,
            "appointment": self._describe(updated),
            "message": f"Appointment {updated['id']} moved to {day.strftime('%A, %d %B %Y')} at {fmt_time(slot)}.",
        }

    def get_treatment_price(self, treatment: str) -> dict:
        t = self.kb.find_treatment(treatment)
        if t is None:
            return _fail(
                "That treatment isn't in our price list, so I can't quote a price. "
                "We offer: " + ", ".join(self.kb.treatment_names()) + ".",
            )
        return {
            "success": True,
            "treatment": t["name"],
            "price": self.kb.price_text(t),
            "note": t.get("price_note", ""),
            "description": t.get("description", ""),
            "disclaimer": self.kb.data["price_disclaimer"],
        }

    def get_clinic_information(self, topic: str = "", question: str = "") -> dict:
        key = (topic or "").lower()
        kb = self.kb
        if any(w in key for w in ("timing", "hour", "open", "schedule")):
            return {"success": True, "topic": "timings", "information": f"We are open {kb.timings_text()}."}
        if any(w in key for w in ("location", "address", "where", "direction")):
            return {"success": True, "topic": "location", "information": f"We are located in {kb.location}."}
        if any(w in key for w in ("treatment", "service", "procedure", "offer")):
            return {"success": True, "topic": "treatments", "information": "We offer: " + ", ".join(kb.treatment_names()) + "."}
        if "emergenc" in key or "urgent" in key:
            return {"success": True, "topic": "emergency", "information": kb.emergency_text()}
        if "bring" in key or "document" in key or "prepare" in key:
            return {"success": True, "topic": "what_to_bring", "information": kb.what_to_bring_text()}
        if key in {"about", "general", "clinic", "overview"}:
            return {"success": True, "topic": "overview",
                    "information": f"{kb.name} is in {kb.location}. We are open {kb.timings_text()}."}
        faqs = kb.search_faq(f"{topic} {question}")
        if faqs:
            return {"success": True, "topic": "faq", "faqs": faqs}
        return _fail("I don't have that information in my records, so I don't want to guess.")

    def get_current_datetime(self) -> dict:
        n = self.now()
        return {"success": True, "date": n.date().isoformat(), "day": n.strftime("%A"),
                "time": fmt_time(n.time()), "timezone": str(self.tz)}

    # ---- formatting -------------------------------------------------------
    @staticmethod
    def _describe(row: dict) -> dict:
        d = datetime.strptime(row["appointment_date"], "%Y-%m-%d").date()
        t = datetime.strptime(row["appointment_time"], "%H:%M").time()
        return {
            "appointment_id": row["id"], "patient_name": row["patient_name"],
            "treatment": row["treatment"], "date": row["appointment_date"],
            "day": d.strftime("%A, %d %B %Y"), "time": fmt_time(t), "status": row["status"],
        }


# --------------------------------------------------------------------------
# Module-level tool functions (safe wrappers around the default service)
# --------------------------------------------------------------------------
_service: DentalService | None = None


def configure_service(service: DentalService) -> None:
    global _service
    _service = service


def get_service() -> DentalService:
    global _service
    if _service is None:
        from voice_agent.config import get_settings  # local import keeps this module light

        settings = get_settings()
        db = AppointmentDB(settings.database_path)
        db.init_db()
        _service = DentalService(ClinicKnowledge(settings.clinic_data_path), db, settings.timezone)
    return _service


@_safe
def check_availability(date: str, time: str = "") -> dict:
    return get_service().check_availability(date, time)


@_safe
def book_appointment(patient_name: str, phone: str, treatment: str, date: str, time: str,
                     email: str = "", notes: str = "") -> dict:
    return get_service().book_appointment(patient_name, phone, treatment, date, time, email, notes)


@_safe
def cancel_appointment(appointment_id: int, phone: str) -> dict:
    return get_service().cancel_appointment(appointment_id, phone)


@_safe
def reschedule_appointment(appointment_id: int, phone: str, new_date: str, new_time: str) -> dict:
    return get_service().reschedule_appointment(appointment_id, phone, new_date, new_time)


@_safe
def get_appointment(phone: str, appointment_id: int | None = None) -> dict:
    return get_service().get_appointment(phone, appointment_id)


@_safe
def get_treatment_price(treatment: str) -> dict:
    return get_service().get_treatment_price(treatment)


@_safe
def get_clinic_information(topic: str = "", question: str = "") -> dict:
    return get_service().get_clinic_information(topic, question)


@_safe
def get_current_datetime() -> dict:
    return get_service().get_current_datetime()
