"""Transient-error detection and retry-with-backoff helper.

LLM providers (especially Gemini's free tier) intermittently return 429/500/503
"overloaded / high demand / try again later" errors. These are transient and should be
retried with exponential backoff rather than surfaced to the caller.
"""
import logging
import random
import time
from typing import Callable, TypeVar

logger = logging.getLogger("pof-extraction-service")

T = TypeVar("T")

_TRANSIENT_TOKENS = (
    "unavailable",
    "overloaded",
    "high demand",
    "try again",
    "rate limit",
    "resource_exhausted",
    "resource exhausted",
    "timeout",
    "timed out",
    "temporarily",
    "internal error",
    "503",
    "502",
    "500",
    "429",
)


def is_transient_error(exc: Exception) -> bool:
    """True if the exception looks like a temporary provider/network condition."""
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    try:
        if int(code) in (429, 500, 502, 503, 504):
            return True
    except (TypeError, ValueError):
        pass
    message = str(exc).lower()
    return any(token in message for token in _TRANSIENT_TOKENS)


def call_with_retries(
    fn: Callable[[], T],
    *,
    attempts: int,
    base_ms: int,
    label: str = "",
    deadline: float | None = None,
) -> T:
    """Call ``fn`` up to ``attempts`` times, backing off on transient errors only.

    If ``deadline`` (a ``time.monotonic()`` value) is given, no new attempt is started and no
    backoff sleep extends past it, so the overall call returns within the time budget.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        if deadline is not None and time.monotonic() >= deadline:
            if last_exc is not None:
                raise last_exc
            raise TimeoutError("Extraction time budget exceeded before any attempt completed.")
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - we re-raise non-transient/last errors
            last_exc = exc
            if attempt >= attempts or not is_transient_error(exc):
                raise
            delay = (base_ms / 1000.0) * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                delay = min(delay, remaining)
            logger.warning(
                "event=retry label=%s attempt=%s/%s delay=%.1fs error=%s",
                label, attempt, attempts, delay, exc,
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc
