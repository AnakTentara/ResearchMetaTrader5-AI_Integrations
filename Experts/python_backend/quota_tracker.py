"""
Local quota tracker for Gemini API usage, keyed by API key / project.

Why this exists: we track usage OURSELVES and refuse to call a key that's
near its limit, instead of just firing requests and reacting to 429s. This
keeps the pipeline predictable and avoids burning retry attempts on calls
we already know will fail.

Two dimensions, matching how Google actually enforces Gemini API limits:
- RPM: rolling 60-second window.
- RPD: resets at midnight PACIFIC TIME (not UTC, not local Indonesia time —
  this matches Google's actual reset behaviour, confirmed via
  ai.google.dev/gemini-api/docs/rate-limits).

Backed by SQLite so counts survive a script restart within the same day.
"""
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


class QuotaTracker:
    def __init__(self, db_path: str = "quota.db"):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS requests (
                    key_id TEXT NOT NULL,
                    ts REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_key_ts ON requests(key_id, ts)")

    @staticmethod
    def _start_of_today_pacific_ts() -> float:
        """Unix timestamp for the most recent midnight in US/Pacific."""
        now_pacific = datetime.now(PACIFIC)
        start_pacific = now_pacific.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_pacific.timestamp()

    def record(self, key_id: str) -> None:
        """Call this the moment a request is ATTEMPTED (not just on success) —
        an attempt still counts against RPM/RPD even if it later fails."""
        with self._connect() as conn:
            conn.execute("INSERT INTO requests (key_id, ts) VALUES (?, ?)", (key_id, time.time()))

    def count_last_minute(self, key_id: str) -> int:
        cutoff = time.time() - 60
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM requests WHERE key_id = ? AND ts > ?", (key_id, cutoff)
            ).fetchone()
        return row[0]

    def count_today(self, key_id: str) -> int:
        cutoff = self._start_of_today_pacific_ts()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM requests WHERE key_id = ? AND ts > ?", (key_id, cutoff)
            ).fetchone()
        return row[0]

    def has_headroom(self, key_id: str, rpm_limit: int, rpd_limit: int) -> bool:
        return self.count_last_minute(key_id) < rpm_limit and self.count_today(key_id) < rpd_limit

    def cleanup(self, older_than_hours: float = 26) -> None:
        """Drop rows old enough that they can't affect either window anymore.
        26h gives a safety margin past the 24h RPD window."""
        cutoff = time.time() - older_than_hours * 3600
        with self._connect() as conn:
            conn.execute("DELETE FROM requests WHERE ts < ?", (cutoff,))
