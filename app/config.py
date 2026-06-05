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

    # Gemini
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

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
