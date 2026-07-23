"""
Pool of Gemini API keys, each expected to come from a SEPARATE Google Cloud
project. That separation is what actually matters: Google enforces RPM/TPM/
RPD per project, not per key, so keys sharing one project share one quota
bucket and rotating between them buys nothing. Keys from different projects
each get their own independent bucket, which is what makes rotation useful.

This module doesn't and can't verify that your keys are really in separate
projects — that's on you when you generate them in Google AI Studio /
Cloud Console. If two entries here are secretly the same project, this code
will still run, it'll just fail to actually multiply your headroom.
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from quota_tracker import QuotaTracker


@dataclass
class ApiKeyEntry:
    key_id: str  # human label, e.g. "project-a" — must be unique in the pool
    api_key: str
    rpm_limit: int = 13   # conservative margin under Google's free-tier 15 RPM
    rpd_limit: int = 1490  # conservative margin under Google's free-tier 1500 RPD


class KeyPool:
    def __init__(self, config_path: str = "keys.json", tracker: Optional[QuotaTracker] = None):
        self.tracker = tracker or QuotaTracker()
        self.keys = self._load(config_path)
        if not self.keys:
            raise ValueError(f"No API keys found in {config_path}")
        ids = [k.key_id for k in self.keys]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate key_id values in {config_path}: {ids}")

    @staticmethod
    def _load(config_path: str) -> list[ApiKeyEntry]:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(
                f"{config_path} not found. Copy keys.example.json to {config_path} "
                f"and fill in real API keys (one per separate Google Cloud project)."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        return [ApiKeyEntry(**entry) for entry in data["keys"]]

    def get_available_key(self, exclude: frozenset[str] = frozenset()) -> Optional[ApiKeyEntry]:
        """First key (in config order) that isn't in `exclude` and has headroom."""
        for entry in self.keys:
            if entry.key_id in exclude:
                continue
            if self.tracker.has_headroom(entry.key_id, entry.rpm_limit, entry.rpd_limit):
                return entry
        return None

    def record_use(self, key_id: str) -> None:
        self.tracker.record(key_id)
