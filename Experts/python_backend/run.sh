#!/bin/bash
# ==========================================
# HaikaruTrade Signal Server — Pterodactyl
# ==========================================
# Repo: https://github.com/AnakTentara/ResearchMetaTrader5-AI_Integrations
# Ports available: 2026, 25527-25530
# Primary port: 2026

set -euo pipefail

echo "=========================================="
echo "  HaikaruTrade Signal Server v2.0"
echo "  Hybrid: Gemini (News) + Claude (Review)"
echo "=========================================="

export PYTHONUNBUFFERED=1
export TZ=UTC

# --- Configuration & .env Loading ---
if [ -f ".env" ]; then
    echo "📄 Loading environment variables from .env file..."
    export $(grep -v '^#' .env | xargs)
fi

PORT="${PORT:-2026}"
SYMBOL="${SYMBOL:-NZDUSD}"
INTERVAL_MINUTES="${INTERVAL_MINUTES:-20}"

export SYMBOL
export INTERVAL_MINUTES

echo "Symbol: $SYMBOL"
echo "Port: $PORT"
echo "Interval: ${INTERVAL_MINUTES}min"

# --- Validate Environment ---
if [ -z "${CLAUDE_API_KEY:-}" ]; then
    echo "ERROR: CLAUDE_API_KEY environment variable not set!"
    echo "  Set it in Pterodactyl: Settings > Startup > Environment Variables"
    exit 1
fi
echo "CLAUDE_API_KEY is set"

# --- Install Dependencies ---
echo ""
echo "Installing dependencies..."
pip install --no-cache-dir -q \
    "google-genai>=1.0.0" \
    "tzdata" \
    "openai>=1.0.0" \
    "fastapi>=0.110.0" \
    "uvicorn[standard]>=0.27.0" \
    "apscheduler>=3.10.0"

echo "Dependencies installed"

# --- Validate Config Files ---
echo ""
echo "Checking configuration..."

if [ ! -f "keys.json" ]; then
    echo "ERROR: keys.json not found!"
    echo "  This file contains Gemini API keys for Stage 1 (News Grounding)."
    echo "  Copy keys.example.json -> keys.json and fill in API keys."
    exit 1
fi
echo "keys.json found"

if [ ! -f "calendar_events.json" ]; then
    echo "calendar_events.json not found - creating empty calendar"
    echo "[]" > calendar_events.json
fi
echo "calendar_events.json ready"

# --- Start Server ---
echo ""
echo "Starting HaikaruTrade Signal Server..."
echo "  GET  /signal?symbol=$SYMBOL  -> Signal data"
echo "  GET  /health                 -> Health check"
echo "  GET  /status                 -> Pipeline status"
echo "  POST /trigger               -> Force refresh"
echo ""

exec uvicorn app:app --host 0.0.0.0 --port "$PORT" --log-level info
