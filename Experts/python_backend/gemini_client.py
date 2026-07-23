"""
Thin wrapper around google-genai that adds:
- key rotation across the pool (skipping keys without local quota headroom)
- exponential backoff + jitter on 5xx server errors (errors.ServerError)
- immediate rotation to the next key on 429 (errors.ClientError, code 429),
  since waiting doesn't help a quota error the way it helps a transient 5xx
- quota recording on every ATTEMPT, not just every success

Verified against google-genai's actual exception classes before writing this
(errors.APIError has a .code int attribute; errors.ClientError/ServerError
subclass it) rather than assuming the shape from docs alone.
"""
import logging
import random
import time
from typing import Optional

from google import genai
from google.genai import errors, types

from key_pool import KeyPool

logger = logging.getLogger(__name__)


class AllKeysExhausted(Exception):
    """Every key in the pool is either at its conservative local threshold,
    or just got a real 429 from Google, for this call."""


class GeminiClient:
    def __init__(self, key_pool: KeyPool, max_retries: int = 3, base_delay: float = 2.0):
        self.key_pool = key_pool
        self.max_retries = max_retries
        self.base_delay = base_delay

    def generate(
        self,
        model: str,
        contents,
        config: Optional[types.GenerateContentConfig] = None,
    ):
        tried_keys: set[str] = set()
        last_error: Optional[Exception] = None

        while True:
            entry = self.key_pool.get_available_key(exclude=frozenset(tried_keys))
            if entry is None:
                break  # no untried key has headroom — give up
            tried_keys.add(entry.key_id)

            client = genai.Client(api_key=entry.api_key)

            for attempt in range(1, self.max_retries + 1):
                self.key_pool.record_use(entry.key_id)  # count the attempt, not just success
                try:
                    return client.models.generate_content(model=model, contents=contents, config=config)

                except errors.ClientError as e:
                    last_error = e
                    if e.code == 429:
                        logger.warning("Key '%s' got 429, rotating to next key", entry.key_id)
                        break  # stop retrying THIS key, outer loop tries the next one
                    raise  # other 4xx (bad request, auth, invalid model) won't fix itself on retry

                except errors.ServerError as e:
                    last_error = e
                    if attempt == self.max_retries:
                        logger.warning(
                            "Key '%s': %s after %d attempts, rotating", entry.key_id, e.code, attempt
                        )
                        break  # retries exhausted on this key, outer loop tries the next one
                    delay = self.base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
                    logger.info(
                        "Server error %s on '%s', retry %d/%d in %.1fs",
                        e.code, entry.key_id, attempt, self.max_retries, delay,
                    )
                    time.sleep(delay)

        raise AllKeysExhausted(f"No key could complete the request. Last error: {last_error}")
