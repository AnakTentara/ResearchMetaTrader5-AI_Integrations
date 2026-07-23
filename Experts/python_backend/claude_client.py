"""
Claude API client via OpenAI-compatible endpoint (ai.minervax.dev).

Simple wrapper — no key rotation needed (single API key via env var).
Uses the openai package with custom base_url for compatibility.
"""
import logging
import os
import time
from typing import Optional

from openai import OpenAI, APIError, APITimeoutError, RateLimitError

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://ai.minervax.dev/v1"
DEFAULT_MODEL = "mvx/claude-sonnet-4-6"


class ClaudeClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        max_retries: int = 3,
        timeout: float = 60.0,
    ):
        self.api_key = api_key or os.environ.get("CLAUDE_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "Claude API key not found. Set CLAUDE_API_KEY environment variable "
                "or pass api_key to ClaudeClient()."
            )
        self.model = model
        self.max_retries = max_retries
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=base_url,
            timeout=timeout,
        )

    def chat(
        self,
        system: str,
        user_message: str,
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str:
        """Send a chat completion request and return the response text."""
        target_model = model or self.model
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=target_model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content or ""

            except RateLimitError as e:
                last_error = e
                wait = min(2 ** attempt, 30)
                logger.warning("Rate limited (attempt %d/%d), waiting %ds", attempt, self.max_retries, wait)
                time.sleep(wait)

            except APITimeoutError as e:
                last_error = e
                logger.warning("Timeout (attempt %d/%d)", attempt, self.max_retries)
                if attempt == self.max_retries:
                    break
                time.sleep(2)

            except APIError as e:
                last_error = e
                if e.status_code and e.status_code >= 500:
                    logger.warning("Server error %s (attempt %d/%d)", e.status_code, attempt, self.max_retries)
                    if attempt == self.max_retries:
                        break
                    time.sleep(2 ** attempt)
                else:
                    raise  # 4xx errors won't fix themselves

        raise RuntimeError(f"Claude API request failed after {self.max_retries} attempts: {last_error}")
