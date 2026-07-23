"""
Orchestrates one full cycle: calendar check -> news grounding (Gemini) ->
financial sanity-check (Claude) -> write signal file.

HYBRID ARCHITECTURE:
  - Stage 1 (News): Gemini + Google Search (grounded context)
  - Stage 2 (Risk Review): Claude Sonnet 4.6 (superior reasoning)

Run this on a schedule (Windows Task Scheduler, cron, or via the FastAPI
server's APScheduler) at a sensible interval — every 15-30 minutes is plenty.
Repo: https://github.com/AnakTentara/ResearchMetaTrader5-AI_Integrations
"""
import logging
import os
import sys
from pathlib import Path

from claude_client import ClaudeClient
from economic_calendar import EconomicCalendar
from financial_reviewer import review_context
from gemini_client import AllKeysExhausted, GeminiClient
from key_pool import KeyPool
from news_analyst import get_news_context
from quota_tracker import QuotaTracker
from signal_writer import write_signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SYMBOL = os.environ.get("SYMBOL", "NZDUSD")


def default_signal_path() -> str:
    """Resolve signal.json path. On Windows with MT5, uses Common/Files.
    On Linux/Pterodactyl, falls back to local directory."""
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        return str(Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files" / "signal.json")
    # Fallback for Linux/Pterodactyl — write to local directory
    return str(Path(__file__).parent / "signal.json")


SIGNAL_PATH = os.environ.get("SIGNAL_PATH", default_signal_path())


def run_once() -> None:
    # --- Gemini setup (Stage 1: News) ---
    tracker = QuotaTracker()
    tracker.cleanup()
    pool = KeyPool(tracker=tracker)
    gemini = GeminiClient(pool)

    # --- Claude setup (Stage 2: Risk Review) ---
    claude = ClaudeClient()

    # --- Calendar check ---
    calendar = EconomicCalendar()
    # Check both currencies in the pair (e.g. NZDUSD -> NZD + USD)
    base_ccy = SYMBOL[:3]   # e.g. "NZD"
    quote_ccy = SYMBOL[3:]  # e.g. "USD"
    blackout_base, reason_base = calendar.is_blackout(currency=base_ccy)
    blackout_quote, reason_quote = calendar.is_blackout(currency=quote_ccy)
    blackout = blackout_base or blackout_quote
    reason = reason_base or reason_quote

    if blackout:
        logger.info("Calendar blackout active (%s) — skipping AI calls", reason)
        write_signal(
            SIGNAL_PATH, SYMBOL, True, reason,
            news_context={"tone": "n/a", "notable_events": []},
            review={"safe_to_trade": False, "reason": reason},
        )
        return

    try:
        # Stage 1: Gemini + Google Search (news grounding)
        news_context = get_news_context(gemini, SYMBOL)
        logger.info("Stage 1 (Gemini) done: tone=%s", news_context.get("tone"))

        # Stage 2: Claude Sonnet (risk review)
        review = review_context(claude, blackout, news_context)
        logger.info("Stage 2 (Claude) done: safe=%s", review.get("safe_to_trade"))

        write_signal(SIGNAL_PATH, SYMBOL, blackout, reason, news_context, review)
        logger.info(
            "Signal written: safe_to_trade=%s tone=%s",
            review.get("safe_to_trade"), news_context.get("tone"),
        )
    except AllKeysExhausted:
        logger.warning(
            "All Gemini keys exhausted — leaving last signal file untouched. "
            "EA freshness check will treat it as stale (fail-safe)."
        )
    except Exception as e:
        logger.error("Pipeline error: %s — writing safe=False signal", e, exc_info=True)
        write_signal(
            SIGNAL_PATH, SYMBOL, False, None,
            news_context={"tone": "unknown", "notable_events": []},
            review={"safe_to_trade": False, "reason": f"Pipeline error: {e}"},
        )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        SYMBOL = sys.argv[1].upper()
    run_once()
