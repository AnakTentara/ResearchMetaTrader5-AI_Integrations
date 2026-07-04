"""
Orchestrates one full cycle: calendar check -> news grounding -> financial
sanity-check -> write signal file for the EA.

Run this on a schedule (Windows Task Scheduler, cron, or a simple
sleep-loop) at a sensible interval — NOT on every EA OnTimer tick (60s).
Every 15-30 minutes is plenty for a context filter: news tone doesn't
meaningfully change minute to minute, and calling this every 60 seconds
would burn through a free-tier daily quota in under two hours for no real
benefit. If a calendar blackout is active, we skip the AI calls entirely
and go straight to writing a safe=False signal — no need to spend quota
asking an LLM about something a schedule already answers for free.
"""
import logging
import os
from pathlib import Path

from economic_calendar import EconomicCalendar
from financial_reviewer import review_context
from gemini_client import AllKeysExhausted, GeminiClient
from key_pool import KeyPool
from news_analyst import get_news_context
from quota_tracker import QuotaTracker
from signal_writer import write_signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SYMBOL = "EURUSD"


def default_signal_path() -> str:
    """MQL5's FileOpen() is sandboxed: it cannot open an arbitrary path like
    an E: drive folder directly. It only reads from the terminal's own
    MQL5/Files folder, or from the shared Common/Files folder when the EA
    passes the FILE_COMMON flag. Common/Files is the better target: it is a
    stable path with no per-terminal hash in it, and it works no matter
    which broker or terminal instance is running. This backend writes here,
    and the EA must open it with FILE_COMMON - see the README for the
    matching MQL5 snippet."""
    appdata = os.environ.get("APPDATA", "")
    return str(Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files" / "signal.json")


SIGNAL_PATH = default_signal_path()


def run_once() -> None:
    tracker = QuotaTracker()
    tracker.cleanup()
    pool = KeyPool(tracker=tracker)
    client = GeminiClient(pool)

    calendar = EconomicCalendar()
    blackout, reason = calendar.is_blackout()

    if blackout:
        logger.info("Calendar blackout active (%s) — skipping AI calls", reason)
        write_signal(
            SIGNAL_PATH, SYMBOL, True, reason,
            news_context={"tone": "n/a", "notable_events": []},
            review={"safe_to_trade": False, "reason": reason},
        )
        return

    try:
        news_context = get_news_context(client, SYMBOL)
        review = review_context(client, blackout, news_context)
        write_signal(SIGNAL_PATH, SYMBOL, blackout, reason, news_context, review)
        logger.info(
            "Signal written: safe_to_trade=%s tone=%s",
            review.get("safe_to_trade"), news_context.get("tone"),
        )
    except AllKeysExhausted:
        logger.warning(
            "All keys exhausted for now — leaving the last signal file untouched. "
            "The EA's freshness check will treat it as stale and stay flat, "
            "which is the correct fail-safe behaviour."
        )


if __name__ == "__main__":
    run_once()
