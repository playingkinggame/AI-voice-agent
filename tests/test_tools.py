"""Run with:  python -m unittest discover -s tests -v"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.appointments import AppointmentDB  # noqa: E402
from tools import dental_tools as dt  # noqa: E402
from tools.knowledge import ClinicKnowledge  # noqa: E402


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = AppointmentDB(os.path.join(self.tmp.name, "test.db"))
        db.init_db()
        self.service = dt.DentalService(ClinicKnowledge(ROOT / "data" / "clinic_data.json"), db)
        dt.configure_service(self.service)
        day = self.service.now().date() + timedelta(days=3)
        while day.weekday() == 6:  # avoid Sunday for most tests
            day += timedelta(days=1)
        self.day = day.isoformat()
        self.sunday = (day + timedelta(days=(6 - day.weekday()) % 7 or 7)).isoformat()

    def tearDown(self):
        self.tmp.cleanup()

    def book(self, phone="9876543210", time="4 PM", treatment="root canal", day=None):
        return dt.book_appointment("Asha Kumar", phone, treatment, day or self.day, time)

    def test_price_root_canal(self):
        r = dt.get_treatment_price("how much is a root canal")
        self.assertTrue(r["success"])
        self.assertIn("4,000 to 8,000", r["price"])

    def test_price_braces_starting(self):
        r = dt.get_treatment_price("braces")
        self.assertIn("starting from", r["price"])

    def test_unknown_treatment(self):
        self.assertFalse(dt.get_treatment_price("hair transplant")["success"])

    def test_availability_and_booking(self):
        self.assertTrue(dt.check_availability(self.day, "4 PM")["requested_time_available"])
        r = self.book()
        self.assertTrue(r["success"], r)
        self.assertEqual(r["appointment"]["time"], "4:00 PM")

    def test_capacity_and_unavailable(self):
        self.assertTrue(self.book(phone="9876543210")["success"])
        self.assertTrue(self.book(phone="9876543211")["success"])
        r = self.book(phone="9876543212")
        self.assertFalse(r["success"])
        self.assertFalse(dt.check_availability(self.day, "4 PM")["requested_time_available"])

    def test_duplicate(self):
        self.book()
        self.assertFalse(self.book()["success"])

    def test_invalid_inputs(self):
        self.assertFalse(self.book(phone="123")["success"])
        self.assertFalse(self.book(time="11 PM")["success"])
        self.assertFalse(self.book(time="4:15 PM")["success"])
        self.assertFalse(self.book(day="2020-01-01")["success"])
        self.assertFalse(self.book(day="not a date")["success"])
        self.assertFalse(self.book(treatment="hair transplant")["success"])
        self.assertFalse(dt.book_appointment("", "9876543210", "root canal", self.day, "4 PM")["success"])

    def test_sunday_hours(self):
        self.assertFalse(self.book(day=self.sunday, time="5 PM")["success"])
        self.assertTrue(self.book(day=self.sunday, time="11 AM")["success"])

    def test_cancel(self):
        aid = self.book()["appointment_id"]
        self.assertFalse(dt.cancel_appointment(aid, "9000000000")["success"])  # wrong phone
        self.assertTrue(dt.cancel_appointment(aid, "9876543210")["success"])
        self.assertFalse(dt.cancel_appointment(aid, "9876543210")["success"])  # already cancelled

    def test_reschedule_and_lookup(self):
        aid = self.book()["appointment_id"]
        r = dt.reschedule_appointment(aid, "9876543210", self.day, "5 PM")
        self.assertTrue(r["success"], r)
        found = dt.get_appointment("9876543210")
        self.assertEqual(found["appointments"][0]["time"], "5:00 PM")
        self.assertFalse(dt.reschedule_appointment(aid, "9876543210", self.day, "5 PM")["success"])

    def test_clinic_info(self):
        self.assertIn("9:00 AM", dt.get_clinic_information("timings")["information"])
        self.assertIn("Chennai", dt.get_clinic_information("location")["information"])
        self.assertTrue(dt.get_clinic_information("faq", "do you treat children")["success"])
        self.assertIn("112", dt.get_clinic_information("emergency")["information"])

    def test_time_parsing(self):
        self.assertEqual(dt.parse_time("4").hour, 16)
        self.assertEqual(dt.parse_time("10 am").hour, 10)
        self.assertEqual(dt.parse_time("4:30pm").minute, 30)
        self.assertEqual(dt.parse_time("16:00").hour, 16)


if __name__ == "__main__":
    unittest.main()
