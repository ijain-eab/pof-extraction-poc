"""Extractor interface. Swapping providers means swapping the implementation only."""
from abc import ABC, abstractmethod

from app.schema import ExtractedFields


class Extractor(ABC):
    """Turns a PDF (raw bytes) into a structured ExtractedFields object."""

    #: human-readable provider id, e.g. "gemini" / "claude"
    name: str = "base"
    #: the concrete model id used, for logging / response meta
    model: str = ""

    @abstractmethod
    def extract(self, pdf_bytes: bytes, file_name: str) -> ExtractedFields:
        raise NotImplementedError
