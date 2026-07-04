"""
Writes the context-assessment signal file that the MQL5 EA reads on its
OnTimer cycle.

Two deliberate design choices, both tying back to earlier decisions in this
project:

1. No "direction" field (no buy/sell/hold). This backend answers "is it
   currently SAFE to trade" — not "which way should we trade". Actual
   directional edge has to come from the statistically validated strategy
   (Fase 2, not built yet). Keeping direction out of this file structurally
   prevents the AI review layer from quietly becoming an unvalidated oracle.

2. Atomic write (write to a .tmp file, then os-level replace). Without this,
   there's a real race window where the EA's OnTimer fires mid-write and
   reads a truncated JSON file. Python's Path.replace() is atomic on both
   Windows and POSIX, so the EA only ever sees a complete old file or a
   complete new one, never a partial one.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def write_signal(
    path: str,
    symbol: str,
    calendar_blackout: bool,
    calendar_reason: Optional[str],
    news_context: dict,
    review: dict,
) -> None:
    payload = {
        "symbol": symbol,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "generated_at_unix": time.time(),
        "calendar_blackout": calendar_blackout,
        "calendar_reason": calendar_reason,
        "news_tone": news_context.get("tone"),
        "notable_events": news_context.get("notable_events", []),
        "safe_to_trade": bool(review.get("safe_to_trade", False)) and not calendar_blackout,
        "review_reason": review.get("reason"),
    }
    tmp_path = Path(f"{path}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2))
    tmp_path.replace(path)  # atomic on Windows and POSIX — EA never sees a partial file
