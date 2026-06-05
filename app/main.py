"""FastAPI service that turns a POF PDF into structured, schema-constrained JSON.

Endpoints:
  GET  /health         - liveness probe
  POST /extract-fields - { opportunityId, fileName, fileBase64 } -> structured fields

The service ONLY extracts. All Salesforce data and the field-by-field comparison stay in
Salesforce (Apex). The request/response contract matches the existing MarkItDown flow so the
same Named Credential can be reused with a new path.
"""
import base64
import io
import logging
import uuid
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app import __version__
from app.anchors import build_anchor_checks
from app.config import settings
from app.extractors import get_extractor
from app.schema import ExtractedFields

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("pof-extraction-service")

app = FastAPI(title="POF Structured Extraction Service", version=__version__)


class ExtractRequest(BaseModel):
    opportunityId: str = Field(..., min_length=15, max_length=18)
    fileName: str = Field(..., min_length=4, max_length=255)
    fileBase64: str = Field(..., min_length=1)


class ExtractResponse(BaseModel):
    success: bool
    requestId: str
    provider: str
    model: str
    fields: Optional[ExtractedFields] = None
    isSigned: Optional[bool] = None
    lowConfidenceFields: list[str] = []
    anchorChecks: dict = {}
    rawTextChars: int = 0
    message: Optional[str] = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "provider": settings.llm_provider, "version": __version__}


def _extract_raw_text(pdf_bytes: bytes) -> str:
    """Best-effort text layer for the deterministic anchor cross-check."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # never fail the request just because text fallback failed
        logger.warning("event=raw_text_failed error=%s", exc)
        return ""


@app.post("/extract-fields", response_model=ExtractResponse)
def extract_fields(
    payload: ExtractRequest,
    x_api_key: Optional[str] = Header(default=None),
) -> ExtractResponse:
    request_id = str(uuid.uuid4())
    logger.info(
        "request_id=%s event=received opportunity_id=%s file_name=%s provider=%s",
        request_id, payload.opportunityId, payload.fileName, settings.llm_provider,
    )

    if settings.api_key and x_api_key != settings.api_key:
        logger.warning("request_id=%s event=auth_failed", request_id)
        raise HTTPException(status_code=401, detail="Invalid API key.")

    if not payload.fileName.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are supported.")

    try:
        pdf_bytes = base64.b64decode(payload.fileBase64, validate=True)
    except Exception as exc:
        logger.warning("request_id=%s event=invalid_base64 error=%s", request_id, exc)
        raise HTTPException(status_code=400, detail="Invalid Base64 payload.") from exc

    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Decoded PDF file is empty.")
    if len(pdf_bytes) > settings.max_file_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds max allowed size of {settings.max_file_mb} MB.",
        )

    try:
        extractor = get_extractor()
    except Exception as exc:
        logger.exception("request_id=%s event=provider_init_failed", request_id)
        raise HTTPException(status_code=500, detail=f"Extractor not configured: {exc}") from exc

    try:
        fields = extractor.extract(pdf_bytes, payload.fileName)
    except Exception as exc:
        logger.exception("request_id=%s event=extraction_failed", request_id)
        raise HTTPException(status_code=502, detail=f"Extraction failed: {exc}") from exc

    raw_text = _extract_raw_text(pdf_bytes)
    anchor_checks = build_anchor_checks(raw_text, fields)

    logger.info(
        "request_id=%s event=extracted proposal=%s is_signed=%s low_conf=%s",
        request_id, fields.proposal_number, fields.is_signed, fields.low_confidence_fields,
    )

    return ExtractResponse(
        success=True,
        requestId=request_id,
        provider=extractor.name,
        model=extractor.model,
        fields=fields,
        isSigned=fields.is_signed,
        lowConfidenceFields=fields.low_confidence_fields or [],
        anchorChecks=anchor_checks,
        rawTextChars=len(raw_text),
        message="POF processed successfully.",
    )
