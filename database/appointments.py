"""SQLite persistence layer for appointments (appointments.db)."""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("dentalvoice.database")

SCHEMA = """
CREATE TABLE IF NOT EXISTS appointments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_name     TEXT NOT NULL,
    phone            TEXT NOT NULL,
    email            TEXT,
    treatment        TEXT NOT NULL,
    appointment_date TEXT NOT NULL,
    appointment_time TEXT NOT NULL,
    notes            TEXT,
    status           TEXT NOT NULL DEFAULT 'confirmed'
                     CHECK (status IN ('confirmed', 'cancelled', 'completed')),
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_appt_slot  ON appointments (appointment_date, appointment_time, status);
CREATE INDEX IF NOT EXISTS idx_appt_phone ON appointments (phone, status);
"""


class AppointmentError(Exception):
    """Base error. `user_message` is safe to read aloud to the patient."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


class ValidationError(AppointmentError):
    pass


class SlotUnavailableError(AppointmentError):
    pass


class DuplicateBookingError(AppointmentError):
    pass


class NotFoundError(AppointmentError):
    pass


class DatabaseError(AppointmentError):
    pass


class AppointmentDB:
    def __init__(self, path: Path | str):
        self.path = str(path)

    # ---- connection helpers ----------------------------------------------
    @contextmanager
    def _connection(self):
        try:
            conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            logger.error("Cannot open database: %s", exc)
            raise DatabaseError("I'm having trouble accessing the appointment system right now.") from exc
        try:
            yield conn
        except sqlite3.Error as exc:
            logger.error("Database error: %s", exc)
            raise DatabaseError("I'm having trouble accessing the appointment system right now.") from exc
        finally:
            conn.close()

    @contextmanager
    def _transaction(self, conn: sqlite3.Connection):
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    def init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(SCHEMA)
        logger.info("Database initialised at %s", self.path)

    # ---- reads ------------------------------------------------------------
    def booked_counts(self, day: str) -> dict[str, int]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT appointment_time, COUNT(*) AS n FROM appointments "
                "WHERE appointment_date = ? AND status = 'confirmed' GROUP BY appointment_time",
                (day,),
            ).fetchall()
        return {r["appointment_time"]: r["n"] for r in rows}

    def get_by_id(self, appointment_id: int) -> dict | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        return dict(row) if row else None

    def find_by_phone(self, phone: str, from_date: str | None = None) -> list[dict]:
        sql = "SELECT * FROM appointments WHERE phone = ? AND status = 'confirmed'"
        args: list = [phone]
        if from_date:
            sql += " AND appointment_date >= ?"
            args.append(from_date)
        sql += " ORDER BY appointment_date, appointment_time"
        with self._connection() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def list_all(self, limit: int = 100) -> list[dict]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM appointments ORDER BY appointment_date DESC, appointment_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- writes -----------------------------------------------------------
    @staticmethod
    def _check_slot_and_duplicates(
        conn: sqlite3.Connection,
        *,
        day: str,
        slot: str,
        phone: str,
        treatment: str | None,
        capacity: int,
        exclude_id: int | None = None,
    ) -> None:
        exclude = exclude_id if exclude_id is not None else -1
        booked = conn.execute(
            "SELECT COUNT(*) FROM appointments WHERE appointment_date = ? AND appointment_time = ? "
            "AND status = 'confirmed' AND id != ?",
            (day, slot, exclude),
        ).fetchone()[0]
        if booked >= capacity:
            raise SlotUnavailableError("That time slot is already fully booked.")
        if treatment is None:
            dup = conn.execute(
                "SELECT id FROM appointments WHERE phone = ? AND appointment_date = ? AND appointment_time = ? "
                "AND status = 'confirmed' AND id != ?",
                (phone, day, slot, exclude),
            ).fetchone()
        else:
            dup = conn.execute(
                "SELECT id FROM appointments WHERE phone = ? AND appointment_date = ? AND status = 'confirmed' "
                "AND (appointment_time = ? OR treatment = ?) AND id != ?",
                (phone, day, slot, treatment, exclude),
            ).fetchone()
        if dup:
            raise DuplicateBookingError(
                f"There is already a confirmed appointment (ID {dup[0]}) for this phone number on that day."
            )

    def create(
        self,
        *,
        patient_name: str,
        phone: str,
        email: str,
        treatment: str,
        day: str,
        slot: str,
        notes: str,
        created_at: str,
        capacity: int,
    ) -> dict:
        with self._connection() as conn:
            with self._transaction(conn):
                self._check_slot_and_duplicates(
                    conn, day=day, slot=slot, phone=phone, treatment=treatment, capacity=capacity
                )
                cur = conn.execute(
                    "INSERT INTO appointments (patient_name, phone, email, treatment, appointment_date, "
                    "appointment_time, notes, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)",
                    (patient_name, phone, email or None, treatment, day, slot, notes or None, created_at),
                )
                new_id = cur.lastrowid
        created = self.get_by_id(new_id)
        if created is None:  # should never happen
            raise DatabaseError("The appointment could not be confirmed in the system.")
        return created

    def _get_owned(self, conn: sqlite3.Connection, appointment_id: int, phone: str) -> dict:
        row = conn.execute(
            "SELECT * FROM appointments WHERE id = ? AND phone = ?", (appointment_id, phone)
        ).fetchone()
        if row is None:
            raise NotFoundError(
                "I couldn't find an appointment with that ID and phone number. Please check both and try again."
            )
        if row["status"] != "confirmed":
            raise NotFoundError(f"That appointment is already {row['status']}.")
        return dict(row)

    def cancel(self, appointment_id: int, phone: str) -> dict:
        with self._connection() as conn:
            with self._transaction(conn):
                self._get_owned(conn, appointment_id, phone)
                conn.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ?", (appointment_id,))
        updated = self.get_by_id(appointment_id)
        if updated is None or updated["status"] != "cancelled":
            raise DatabaseError("I could not confirm the cancellation in the system.")
        return updated

    def reschedule(self, appointment_id: int, phone: str, new_day: str, new_slot: str, capacity: int) -> dict:
        with self._connection() as conn:
            with self._transaction(conn):
                current = self._get_owned(conn, appointment_id, phone)
                if current["appointment_date"] == new_day and current["appointment_time"] == new_slot:
                    raise ValidationError("The appointment is already scheduled for that date and time.")
                self._check_slot_and_duplicates(
                    conn, day=new_day, slot=new_slot, phone=phone, treatment=None,
                    capacity=capacity, exclude_id=appointment_id,
                )
                conn.execute(
                    "UPDATE appointments SET appointment_date = ?, appointment_time = ? WHERE id = ?",
                    (new_day, new_slot, appointment_id),
                )
        updated = self.get_by_id(appointment_id)
        if updated is None or (updated["appointment_date"], updated["appointment_time"]) != (new_day, new_slot):
            raise DatabaseError("I could not confirm the new time in the system.")
        return updated
