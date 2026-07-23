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

# --- Navigate to python_backend directory ---
# run.sh may be called from repo root or any parent directory.
# Always cd to the directory containing this script so app.py is importable.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
echo "📁 Working directory: $(pwd)"

# --- Configuration & .env Loading ---
# Search for .env in current dir, parent dir, or Experts/python_backend
ENV_FILE=""
if [ -f ".env" ]; then
    ENV_FILE=".env"
elif [ -f "../.env" ]; then
    ENV_FILE="../.env"
elif [ -f "Experts/python_backend/.env" ]; then
    ENV_FILE="Experts/python_backend/.env"
fi

if [ -n "$ENV_FILE" ]; then
    echo "📄 Loading environment variables from $ENV_FILE..."
    # Convert CRLF to LF and export variables safely
    while IFS='=' read -r key value || [ -n "$key" ]; do
        # Ignore comments and empty lines
        [[ "$key" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$key" ]] && continue
        # Clean carriage returns and quotes
        key=$(echo "$key" | tr -d '\r' | xargs)
        value=$(echo "$value" | tr -d '\r' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
        if [ -n "$key" ]; then
            export "$key=$value"
        fi
    done < "$ENV_FILE"
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

# --- Add Python script paths to PATH ---
export PATH="$PATH:$HOME/.local/bin:/usr/local/bin"

# --- Start Server ---
echo ""
echo "Starting HaikaruTrade Signal Server..."
echo "  GET  /signal?symbol=$SYMBOL  -> Signal data"
echo "  GET  /health                 -> Health check"
echo "  GET  /status                 -> Pipeline status"
echo "  POST /trigger               -> Force refresh"
echo ""

exec python -m uvicorn app:app --host 0.0.0.0 --port "$PORT" --log-level info
