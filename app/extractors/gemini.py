"""Google Gemini extractor (default, free tier).

Sends the PDF inline to Gemini and constrains the response to the ExtractedFields schema.
GEMINI_MODEL may be a comma-separated list; on a transient/overload error the extractor
rotates to the next model in the list before giving up.
"""
import json
import logging

from app.config import settings
from app.prompts import EXTRACTION_PROMPT
from app.retry import is_transient_error
from app.schema import ExtractedFields

from .base import Extractor

logger = logging.getLogger("pof-extraction-service")


class GeminiExtractor(Extractor):
    name = "gemini"

    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        # Imported lazily so the package only needs google-genai when this provider is used.
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self.models = settings.gemini_models or [settings.gemini_model]
        # `model` reflects the model that last served a request (for the response payload).
        self.model = self.models[0]

    def _generate(self, model: str, pdf_bytes: bytes) -> ExtractedFields:
        from google.genai import types

        response = self._client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                EXTRACTION_PROMPT,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ExtractedFields,
                temperature=0,
            ),
        )

        # Prefer the SDK's parsed object; fall back to parsing the JSON text.
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, ExtractedFields):
            return parsed
        if parsed is not None:
            return ExtractedFields.model_validate(parsed)

        raw = (response.text or "").strip()
        if not raw:
            raise RuntimeError("Gemini returned an empty response.")
        return ExtractedFields.model_validate(json.loads(raw))

    def extract(self, pdf_bytes: bytes, file_name: str) -> ExtractedFields:
        last_exc: Exception | None = None
        for index, model in enumerate(self.models):
            is_last = index == len(self.models) - 1
            try:
                fields = self._generate(model, pdf_bytes)
                self.model = model
                return fields
            except Exception as exc:
                last_exc = exc
                # Only roll to the next model for transient/overload errors.
                if not is_last and is_transient_error(exc):
                    logger.warning(
                        "event=gemini_model_failover from=%s to=%s error=%s",
                        model, self.models[index + 1], exc,
                    )
                    continue
                raise
        assert last_exc is not None
        raise last_exc
