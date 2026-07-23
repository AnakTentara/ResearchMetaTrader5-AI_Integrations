"""
Stage 1: grounded news context using Gemma 4 (26B-A4B) with Google Search.

Important constraint discovered while building this (not documented clearly
up front): the Gemini API rejects requests that combine the google_search
tool with enforced response_schema / controlled generation —
"Unable to submit request because controlled generation is not supported
with google_search tool" (400 INVALID_ARGUMENT). So instead of
response_schema, we ask the model to end its free-text answer with a JSON
tail, and parse that out defensively with regex. If parsing fails, we fail
SAFE (tone="unknown") rather than raising — a parsing hiccup here should
never take down the whole pipeline; the EA's freshness/risk check downstream
is the real safety net, this is just a best-effort context signal.

Scope reminder: this returns a CONTEXT ASSESSMENT, not a trade direction.
"""
import json
import re
from typing import Optional

from google.genai import types

from gemini_client import GeminiClient

MODEL = "gemma-4-26b-a4b-it"

SYSTEM_INSTRUCTION = """You are a market news context assistant. Your only job is
to summarize the current news/sentiment environment for a given symbol, grounded
in real search results. You do NOT predict price direction and you do NOT
recommend trades. Stay factual and stay close to what the search results
actually say. If search results are thin or inconclusive, say so honestly
instead of speculating or filling gaps with assumptions.

After your summary, on its own line, output ONLY a JSON object with this exact
shape and nothing else on that line (no markdown code fences):
{"tone": "calm", "notable_events": ["short description", ...]}
tone must be exactly one of: "calm", "mixed", "elevated_uncertainty"."""

_JSON_RE = re.compile(r"\{[^{}]*\"tone\"[^{}]*\}")
_VALID_TONES = {"calm", "mixed", "elevated_uncertainty"}


def get_news_context(client: GeminiClient, symbol: str) -> dict:
    """Returns {"tone": str, "notable_events": list[str], "raw_summary": str}."""
    prompt = (
        f"Search for and summarize today's most relevant news and market "
        f"commentary for {symbol}. Focus specifically on anything that could "
        f"drive unusual short-term volatility (central bank actions, "
        f"geopolitical shocks, surprise data releases)."
    )
    response = client.generate(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=[{"google_search": {}}],
        ),
    )
    text = response.text or ""
    parsed = _extract_json_tail(text)
    parsed["raw_summary"] = text
    return parsed


def _extract_json_tail(text: str) -> dict:
    match = _JSON_RE.search(text)
    if match:
        try:
            candidate = json.loads(match.group(0))
            tone = candidate.get("tone")
            events = candidate.get("notable_events")
            if tone in _VALID_TONES and isinstance(events, list):
                return {"tone": tone, "notable_events": [str(e) for e in events]}
        except json.JSONDecodeError:
            pass
    return {"tone": "unknown", "notable_events": []}
