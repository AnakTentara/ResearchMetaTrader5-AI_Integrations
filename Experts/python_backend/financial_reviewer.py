"""
Stage 2: financial sanity-check using Claude Sonnet 4.6 via ai.minervax.dev.

HYBRID ARCHITECTURE: Stage 1 (news grounding) uses Gemini for Google Search,
Stage 2 (risk review) uses Claude for superior reasoning quality.

Deliberately scoped as a CHECKLIST-BASED SANITY CHECK, not a market oracle.
This model is never asked "will price go up" — only "does this context
contradict itself or the stated rules". No LLM has genuine forward-looking
market edge; prompting one to roleplay as a top investor doesn't create that
edge, it just makes ungrounded output sound more confident.
"""
import json
import logging

from claude_client import ClaudeClient

logger = logging.getLogger(__name__)

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
cycle costs nothing, an unreviewed risk can cost real money.

IMPORTANT: Respond with ONLY a JSON object, no markdown formatting, no code
fences, no extra text. The JSON must have exactly this shape:
{"safe_to_trade": true/false, "reason": "your explanation"}"""


def review_context(claude: ClaudeClient, calendar_blackout: bool, news_context: dict) -> dict:
    """Returns {"safe_to_trade": bool, "reason": str}."""
    prompt = (
        f"calendar_blackout: {calendar_blackout}\n"
        f"news_tone: {news_context.get('tone')}\n"
        f"notable_events: {news_context.get('notable_events', [])}\n\n"
        f"Run the checklist and respond with JSON only."
    )
    try:
        text = claude.chat(
            system=SYSTEM_INSTRUCTION,
            user_message=prompt,
            temperature=0.2,
            max_tokens=512,
        )
        # Defensive JSON extraction — handle potential markdown wrappers
        clean = text.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            )
        result = json.loads(clean)
        if "safe_to_trade" not in result or "reason" not in result:
            raise ValueError("Missing required fields in response")
        return {"safe_to_trade": bool(result["safe_to_trade"]), "reason": str(result["reason"])}

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.error("Failed to parse Claude response: %s — defaulting to safe=False", e)
        return {"safe_to_trade": False, "reason": f"Claude response parse error: {e}"}
