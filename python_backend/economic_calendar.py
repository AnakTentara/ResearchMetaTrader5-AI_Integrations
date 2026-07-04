"""
Economic calendar blackout check — deliberately NOT AI-based.

High-impact news timing is structured, scheduled data. Using an LLM for
"is there a big release soon" would be slower, cost quota, and be less
reliable than just checking a schedule.

Honesty note: this ships with a manually-maintained JSON event list as a
starting point, NOT a live connection to any specific calendar provider —
I haven't verified a free, ToS-clean calendar API for you, and I'd rather
leave that placeholder obvious than hand you a fabricated endpoint that
looks real but doesn't work. Swap `_load_events` for a real feed (Trading
Economics, FXStreet, your broker's calendar API, etc.) when you pick one;
nothing else in this module needs to change.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


@dataclass
class CalendarEvent:
    name: str
    time_utc: datetime
    impact: str  # "high", "medium", "low" — only "high" triggers a blackout
    currency: str


class EconomicCalendar:
    def __init__(self, events_path: str = "calendar_events.json", blackout_minutes: int = 15):
        self.blackout_minutes = blackout_minutes
        self.events = self._load_events(events_path)

    @staticmethod
    def _load_events(events_path: str) -> list[CalendarEvent]:
        path = Path(events_path)
        if not path.exists():
            return []
        raw = json.loads(path.read_text())
        return [
            CalendarEvent(
                name=e["name"],
                time_utc=datetime.fromisoformat(e["time_utc"]).replace(tzinfo=timezone.utc),
                impact=e["impact"],
                currency=e["currency"],
            )
            for e in raw
        ]

    def is_blackout(self, currency: Optional[str] = None, now: Optional[datetime] = None) -> tuple[bool, Optional[str]]:
        """Returns (in_blackout, reason). Window is symmetric around the
        event time (blackout_minutes before AND after)."""
        now = now or datetime.now(timezone.utc)
        window = timedelta(minutes=self.blackout_minutes)
        for event in self.events:
            if event.impact != "high":
                continue
            if currency and event.currency != currency:
                continue
            if event.time_utc - window <= now <= event.time_utc + window:
                return True, f"{event.name} ({event.currency}) at {event.time_utc.isoformat()}"
        return False, None
