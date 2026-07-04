"""
Stage 2: financial sanity-check using Gemma 4 (31B dense) with high thinking.

Deliberately scoped as a CHECKLIST-BASED SANITY CHECK, not a market oracle.
This model is never asked "will price go up" — only "does this context
contradict itself or the stated rules". No LLM has genuine forward-looking
market edge; prompting one to roleplay as a top investor doesn't create that
edge, it just makes ungrounded output sound more confident. Real directional
edge has to come from the statistically validated strategy research (Fase 2
on the roadmap) — this stage's only job is to catch inconsistencies in the
context before they reach the EA.
"""
import json

from google.genai import types

from gemini_client import GeminiClient

MODEL = "gemma-4-31b-it"

SYSTEM_INSTRUCTION = """You are a risk sanity-checker for an automated trading
research pipeline. You do NOT predict market direction and you do not have
genuine forward-looking insight into prices — no model does, and you should
never imply otherwise. Your only job is to check the given context against
this checklist:

1. Does notable_events contain anything that sounds like a scheduled
   high-impact release (central bank decision, jobs report, inflation print)
   that calendar_blackout says is NOT currently active? If so, that's a
   contradiction worth flagging.
2. Is anything in notable_events severe enough on its own (war, sovereign
   default, exchange trading halt, major bank failure) that trading should
   pause even outside a scheduled calendar window?
3. Is news_tone "elevated_uncertainty" without any notable_events explaining
   why? If so, treat that as suspicious rather than reassuring — it may mean
   the news stage failed to parse cleanly.

Only reason from this checklist. When in doubt, do not approve — a missed
cycle costs nothing, an unreviewed risk can cost real money."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "safe_to_trade": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["safe_to_trade", "reason"],
}


def review_context(client: GeminiClient, calendar_blackout: bool, news_context: dict) -> dict:
    """Returns {"safe_to_trade": bool, "reason": str}."""
    prompt = (
        f"calendar_blackout: {calendar_blackout}\n"
        f"news_tone: {news_context.get('tone')}\n"
        f"notable_events: {news_context.get('notable_events', [])}\n\n"
        f"Run the checklist and respond."
    )
    response = client.generate(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH),
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        ),
    )
    return json.loads(response.text)
