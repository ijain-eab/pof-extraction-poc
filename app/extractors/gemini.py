"""Google Gemini extractor (default, free tier).

Sends the PDF inline to Gemini and constrains the response to the ExtractedFields schema.
"""
import json

from app.config import settings
from app.prompts import EXTRACTION_PROMPT
from app.schema import ExtractedFields

from .base import Extractor


class GeminiExtractor(Extractor):
    name = "gemini"

    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        # Imported lazily so the package only needs google-genai when this provider is used.
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model

    def extract(self, pdf_bytes: bytes, file_name: str) -> ExtractedFields:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self.model,
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
