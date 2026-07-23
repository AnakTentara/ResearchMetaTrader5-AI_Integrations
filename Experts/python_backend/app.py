"""
FastAPI server for HaikaruTrade Signal Backend.

Exposes signal data via HTTP so the MT5 EA can fetch it via WebRequest()
instead of relying on FILE_COMMON (local filesystem).

Hybrid Architecture:
  - Stage 1 (News): Gemini + Google Search
  - Stage 2 (Risk Review): Claude Sonnet 4.6

Designed for deployment on Pterodactyl panel.
Repo: https://github.com/AnakTentara/ResearchMetaTrader5-AI_Integrations
"""
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# --- Signal Cache ---
_signal_cache: dict = {}
_last_run_time: float = 0
_last_run_status: str = "not_run"
_run_count: int = 0

INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "20"))


def _run_pipeline():
    """Execute the orchestrator pipeline and cache results."""
    global _signal_cache, _last_run_time, _last_run_status, _run_count
    try:
        from orchestrator import run_once, SIGNAL_PATH
        run_once()
        # Read the signal file that was just written
        signal_path = Path(SIGNAL_PATH)
        if signal_path.exists():
            _signal_cache = json.loads(signal_path.read_text(encoding="utf-8"))
        _last_run_status = "success"
    except Exception as e:
        logger.error("Pipeline run failed: %s", e, exc_info=True)
        _last_run_status = f"error: {e}"
    finally:
        _last_run_time = time.time()
        _run_count += 1


# --- Scheduler ---
scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run pipeline on startup, then schedule periodic runs."""
    logger.info("Starting initial pipeline run...")
    _run_pipeline()
    scheduler.add_job(
        _run_pipeline,
        "interval",
        minutes=INTERVAL_MINUTES,
        id="signal_pipeline",
        max_instances=1,
    )
    scheduler.start()
    logger.info("Scheduler started: pipeline runs every %d minutes", INTERVAL_MINUTES)
    yield
    scheduler.shutdown()
    logger.info("Scheduler shut down.")


app = FastAPI(
    title="HaikaruTrade Signal Server",
    description="Hybrid AI Risk Filter: Gemini (News) + Claude (Review)",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/signal")
async def get_signal(symbol: str = Query(default="NZDUSD")):
    """Return the latest cached signal for the given symbol."""
    if not _signal_cache:
        return JSONResponse(
            status_code=503,
            content={"error": "No signal available yet. Pipeline may still be initializing."},
        )
    cached_symbol = _signal_cache.get("symbol", "")
    if cached_symbol.upper() != symbol.upper():
        return JSONResponse(
            status_code=404,
            content={"error": f"No signal for {symbol}. Available: {cached_symbol}"},
        )
    return _signal_cache


@app.get("/health")
async def health():
    """Health check for Pterodactyl / monitoring."""
    return {"status": "ok", "uptime_runs": _run_count}


@app.get("/status")
async def status():
    """Detailed pipeline status."""
    age = time.time() - _last_run_time if _last_run_time > 0 else -1
    return {
        "last_run_unix": _last_run_time,
        "last_run_utc": datetime.fromtimestamp(_last_run_time, tz=timezone.utc).isoformat() if _last_run_time > 0 else "never",
        "last_run_status": _last_run_status,
        "signal_age_seconds": round(age, 1),
        "total_runs": _run_count,
        "interval_minutes": INTERVAL_MINUTES,
        "symbol": os.environ.get("SYMBOL", "NZDUSD"),
    }


@app.post("/trigger")
async def trigger():
    """Manually trigger a pipeline run."""
    _run_pipeline()
    return {"status": "triggered", "result": _last_run_status}
