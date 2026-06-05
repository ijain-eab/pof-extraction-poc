"""Provider factory. Selects the extractor based on settings.llm_provider."""
from functools import lru_cache

from app.config import settings

from .base import Extractor


@lru_cache(maxsize=1)
def get_extractor() -> Extractor:
    provider = settings.llm_provider
    if provider == "gemini":
        from .gemini import GeminiExtractor

        return GeminiExtractor()
    if provider == "claude":
        from .claude import ClaudeExtractor

        return ClaudeExtractor()
    raise RuntimeError(
        f"Unknown LLM_PROVIDER '{provider}'. Use 'gemini' or 'claude'."
    )


__all__ = ["Extractor", "get_extractor"]
