"""Loads the clinic knowledge base (data/clinic_data.json) and answers lookups."""
from __future__ import annotations

import difflib
import json
import re
from datetime import date, time
from pathlib import Path

DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_STOPWORDS = {
    "a", "an", "the", "do", "you", "your", "i", "is", "are", "can", "what", "how", "to", "of",
    "for", "my", "me", "we", "it", "in", "at", "on", "and", "or", "have", "does", "will", "get",
}


def parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def fmt_time(t: time) -> str:
    hour12 = t.hour % 12 or 12
    suffix = "AM" if t.hour < 12 else "PM"
    return f"{hour12}:{t.minute:02d} {suffix}"


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS}


class ClinicKnowledge:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        with self.path.open("r", encoding="utf-8") as fh:
            self.data = json.load(fh)
        self.treatments: list[dict] = self.data["treatments"]

    # ---- basic info -------------------------------------------------------
    @property
    def name(self) -> str:
        return self.data["clinic"]["name"]

    @property
    def location(self) -> str:
        return self.data["clinic"]["location"]

    @property
    def booking(self) -> dict:
        return self.data.get("booking", {})

    # ---- timings ----------------------------------------------------------
    def hours_for(self, day: date) -> tuple[time, time] | None:
        entry = self.data["timings"].get(DAY_NAMES[day.weekday()])
        if not entry:
            return None
        return parse_hhmm(entry["open"]), parse_hhmm(entry["close"])

    def timings_text(self) -> str:
        groups: list[tuple[list[str], str]] = []
        for day in DAY_NAMES:
            entry = self.data["timings"].get(day)
            label = (
                f"{fmt_time(parse_hhmm(entry['open']))} to {fmt_time(parse_hhmm(entry['close']))}"
                if entry else "closed"
            )
            if groups and groups[-1][1] == label:
                groups[-1][0].append(day.capitalize())
            else:
                groups.append(([day.capitalize()], label))
        parts = []
        for days, label in groups:
            span = days[0] if len(days) == 1 else f"{days[0]} to {days[-1]}"
            parts.append(f"{span}: {label}")
        return "; ".join(parts)

    # ---- treatments -------------------------------------------------------
    def treatment_names(self) -> list[str]:
        return [t["name"] for t in self.treatments]

    def find_treatment(self, query: str) -> dict | None:
        q = re.sub(r"\s+", " ", (query or "").lower().strip())
        if not q:
            return None
        best: tuple[int, dict] | None = None
        for t in self.treatments:
            names = [t["name"].lower(), *[a.lower() for a in t.get("aliases", [])]]
            for n in names:
                if q == n:
                    return t
                if n in q:  # alias appears in what the patient said; prefer the longest alias
                    if best is None or len(n) > best[0]:
                        best = (len(n), t)
        if best:
            return best[1]
        for t in self.treatments:
            names = [t["name"].lower(), *[a.lower() for a in t.get("aliases", [])]]
            if any(q in n for n in names):
                return t
        lookup = {}
        for t in self.treatments:
            lookup[t["name"].lower()] = t
            for a in t.get("aliases", []):
                lookup[a.lower()] = t
        close = difflib.get_close_matches(q, list(lookup), n=1, cutoff=0.75)
        return lookup[close[0]] if close else None

    @staticmethod
    def price_text(t: dict) -> str:
        low, high = t["price_min"], t["price_max"]
        unit = f" {t['price_unit']}" if t.get("price_unit") else ""
        if t.get("starting_price"):
            return f"starting from around {low:,} rupees{unit}"
        if low == high:
            return f"around {low:,} rupees{unit}"
        return f"around {low:,} to {high:,} rupees{unit}"

    # ---- other info -------------------------------------------------------
    def emergency_text(self) -> str:
        e = self.data["emergency"]
        return f"{e['info']} {e['urgent_warning']}"

    def what_to_bring_text(self) -> str:
        return "Please bring: " + "; ".join(self.data["what_to_bring"]) + "."

    def _resolve_faq_answer(self, answer: str) -> str:
        return (
            answer.replace("__TIMINGS__", f"We are open {self.timings_text()}.")
            .replace("__LOCATION__", f"We are located in {self.location}.")
            .replace("__EMERGENCY__", self.emergency_text())
        )

    def search_faq(self, query: str, limit: int = 2) -> list[dict]:
        qt = _tokens(query)
        scored = []
        for faq in self.data["faqs"]:
            score = len(qt & _tokens(faq["question"]))
            if score:
                scored.append((score, faq))
        scored.sort(key=lambda s: -s[0])
        return [
            {"question": f["question"], "answer": self._resolve_faq_answer(f["answer"])}
            for _, f in scored[:limit]
        ]
