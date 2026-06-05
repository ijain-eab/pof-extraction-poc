"""Environment-driven settings for the extraction service."""
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv is optional at runtime (e.g. on Railway)
    pass


class Settings:
    # Service auth: when set, callers must send a matching x-api-key header.
    api_key: str | None = os.getenv("API_KEY")

    # Which engine handles extraction: "gemini" (default) or "claude".
    llm_provider: str = os.getenv("LLM_PROVIDER", "gemini").strip().lower()

    # Optional automatic fallback provider when the primary fails with a transient error
    # (e.g. set to "claude" so a Gemini 503 silently fails over). Blank = no fallback.
    llm_fallback_provider: str | None = (
        os.getenv("LLM_FALLBACK_PROVIDER", "").strip().lower() or None
    )

    # Retry-with-backoff on transient provider errors (429/500/503/overloaded).
    extract_max_retries: int = int(os.getenv("EXTRACT_MAX_RETRIES", "4"))
    extract_retry_base_ms: int = int(os.getenv("EXTRACT_RETRY_BASE_MS", "1500"))

    # Gemini. GEMINI_MODEL may be a single model or a comma-separated fallback list
    # (e.g. "gemini-2.5-flash-lite,gemini-2.0-flash"); the extractor rotates to the next
    # model on a transient/overload error.
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    @property
    def gemini_models(self) -> list[str]:
        return [m.strip() for m in self.gemini_model.split(",") if m.strip()]

    # Claude (optional)
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-latest")

    # Limits
    max_file_mb: int = int(os.getenv("MAX_FILE_MB", "10"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024


settings = Settings()
