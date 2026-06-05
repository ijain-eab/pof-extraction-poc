"""Anthropic Claude extractor (optional).

Enabled by setting LLM_PROVIDER=claude and ANTHROPIC_API_KEY. Uses tool-use to force a
structured JSON response that matches the ExtractedFields schema. The anthropic package and
client are imported lazily so they are not required unless this provider is selected.
"""
import base64

from app.config import settings
from app.prompts import EXTRACTION_PROMPT
from app.schema import ExtractedFields

from .base import Extractor

_TOOL_NAME = "record_pof_fields"


class ClaudeExtractor(Extractor):
    name = "claude"

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model

    def extract(self, pdf_bytes: bytes, file_name: str) -> ExtractedFields:
        pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")
        tool = {
            "name": _TOOL_NAME,
            "description": "Record the structured fields extracted from the POF.",
            "input_schema": ExtractedFields.model_json_schema(),
        }

        message = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=0,
            tools=[tool],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_b64,
                            },
                        },
                        {"type": "text", "text": EXTRACTION_PROMPT},
                    ],
                }
            ],
        )

        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == _TOOL_NAME:
                return ExtractedFields.model_validate(block.input)

        raise RuntimeError("Claude did not return a tool_use block with the extracted fields.")
