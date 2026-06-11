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
import re
import time
import uuid
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app import __version__
from app.anchors import build_anchor_checks
from app.config import settings
from app.extractors import Extractor, get_extractor
from app.retry import call_with_retries, is_transient_error
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
    # Deterministic paragraph segmentation of the PDF text layer. Salesforce diffs
    # `bodyParagraphs` against the Quote Term bodies; `excludedParagraphs` are the
    # structural blocks (headers, fee tables, footers, signatures) surfaced for review.
    bodyParagraphs: list[str] = []
    excludedParagraphs: list[str] = []
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


# --- Paragraph classification (prose clauses vs structural content) ----------
_FOOTER_RE = re.compile(
    r"(PROPOSAL\s*\|)|(Page\s+\d+\s+of\s+\d+)|(^--\s*\d+\s+of\s+\d+\s*--$)",
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(r"\{\{.*?\}\}|Signer\d", re.IGNORECASE)
_UNDERSCORE_RE = re.compile(r"_{3,}")
_MONEY_RE = re.compile(r"\bUSD\b|\$\s*\d", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_MIN_PROSE_WORDS = 6


def _is_structural_line(line: str) -> bool:
    """Heuristic: is this raw text line structural (header/address, fee-table row,
    page footer, signature placeholder, billing underscores) rather than clause prose?"""
    s = line.strip()
    if not s:
        return True
    if _FOOTER_RE.search(s):
        return True
    if _PLACEHOLDER_RE.search(s):
        return True
    if _UNDERSCORE_RE.search(s):
        return True
    if s.count("|") >= 2:  # markdown-style table row, if ever present
        return True
    if _MONEY_RE.search(s) and any(ch.isdigit() for ch in s):
        return True
    if s.lower().startswith("program term:"):
        return True
    # Mostly non-alphabetic (numeric table data, separators)
    letters = sum(1 for ch in s if ch.isalpha())
    if letters / len(s) < 0.5:
        return True
    return False


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _classify_paragraphs(raw_text: str) -> tuple[list[str], list[str]]:
    """Split the PDF text layer into prose clause paragraphs vs structural blocks.

    Consecutive non-structural lines are merged into a paragraph; blank lines and
    structural lines act as separators. Blocks with too few real words (headings,
    labels, addresses) are treated as structural and surfaced for review.
    """
    prose: list[str] = []
    excluded: list[str] = []
    if not raw_text:
        return prose, excluded

    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        para = " ".join(buffer).strip()
        buffer.clear()
        if not para:
            return
        if len(_WORD_RE.findall(para)) >= _MIN_PROSE_WORDS:
            prose.append(para)
        else:
            excluded.append(para)

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if _is_structural_line(line):
            flush()
            excluded.append(line)
        else:
            buffer.append(line)
    flush()

    return _dedupe(prose), _dedupe(excluded)


def _extract_with_resilience(
    pdf_bytes: bytes, file_name: str, request_id: str
) -> tuple[Extractor, ExtractedFields]:
    """Run extraction with backoff retries, falling over to the fallback provider on
    transient failures (e.g. a Gemini 503 fails over to Claude when configured)."""
    providers: list[str] = [settings.llm_provider]
    if settings.llm_fallback_provider and settings.llm_fallback_provider not in providers:
        providers.append(settings.llm_fallback_provider)

    # Hard time budget so we return a clean error before the caller's socket timeout.
    deadline = time.monotonic() + settings.extract_deadline_s

    last_exc: Exception | None = None
    for index, provider in enumerate(providers):
        is_last = index == len(providers) - 1
        if time.monotonic() >= deadline:
            break
        try:
            extractor = get_extractor(provider)
        except Exception as exc:
            last_exc = exc
            logger.warning("request_id=%s event=provider_init_failed provider=%s error=%s",
                           request_id, provider, exc)
            if is_last:
                raise HTTPException(status_code=500, detail=f"Extractor not configured: {exc}") from exc
            continue

        try:
            fields = call_with_retries(
                lambda: extractor.extract(pdf_bytes, file_name, deadline=deadline),
                attempts=settings.extract_max_retries,
                base_ms=settings.extract_retry_base_ms,
                label=f"{request_id}:{provider}",
                deadline=deadline,
            )
            return extractor, fields
        except TimeoutError as exc:
            last_exc = exc
            logger.warning("request_id=%s event=extraction_deadline provider=%s error=%s",
                           request_id, provider, exc)
            if not is_last:
                logger.warning("request_id=%s event=failover from=%s to=%s",
                               request_id, provider, providers[index + 1])
                continue
            raise HTTPException(
                status_code=503,
                detail="Extraction service is busy (all models overloaded). Please try again in a moment.",
            ) from exc
        except Exception as exc:
            last_exc = exc
            logger.exception("request_id=%s event=extraction_failed provider=%s", request_id, provider)
            if not is_last and is_transient_error(exc):
                logger.warning("request_id=%s event=failover from=%s to=%s",
                               request_id, provider, providers[index + 1])
                continue
            raise HTTPException(status_code=502, detail=f"Extraction failed: {exc}") from exc

    # Reached only if the deadline was hit before a provider could run.
    raise HTTPException(
        status_code=503,
        detail="Extraction service is busy (all models overloaded). Please try again in a moment.",
    )


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

    extractor, fields = _extract_with_resilience(pdf_bytes, payload.fileName, request_id)

    raw_text = _extract_raw_text(pdf_bytes)
    anchor_checks = build_anchor_checks(raw_text, fields)
    body_paragraphs, excluded_paragraphs = _classify_paragraphs(raw_text)

    logger.info(
        "request_id=%s event=extracted proposal=%s is_signed=%s low_conf=%s prose=%s excluded=%s",
        request_id, fields.proposal_number, fields.is_signed, fields.low_confidence_fields,
        len(body_paragraphs), len(excluded_paragraphs),
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
        bodyParagraphs=body_paragraphs,
        excludedParagraphs=excluded_paragraphs,
        message="POF processed successfully.",
    )
