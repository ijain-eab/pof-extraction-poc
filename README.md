# POF Structured Extraction Service (POC)

A small FastAPI service that turns an EAB / Seramount **Program Order Form (POF)** PDF into
**structured, schema-constrained JSON**, so Salesforce can validate it against Proposal /
Opportunity data deterministically.

This replaces the brittle "MarkItDown text + regex/Levenshtein in Apex" approach. Instead of
parsing linearized text, we send the PDF to a vision-capable LLM and force it to return a
strict JSON schema. The LLM handles the things that broke regex: exploded tables, DocuSign
signature overlays landing out of order, and per-template-version layout differences.

> The service only **extracts**. All Salesforce data and the field-by-field comparison stay in
> Salesforce (the `PofAiValidationController` Apex class).

## Architecture

```
LWC button ─▶ PofAiValidationController (Apex)
                 │  POST callout:POF_Extraction_POC_NC/extract-fields  (PDF base64)
                 ▼
        FastAPI /extract-fields ─▶ LLM (Gemini default, Claude optional)
                 │  strict JSON (ExtractedFields schema)
                 ▼
        Apex compares fields vs Proposal + Opportunity ─▶ result table in LWC
```

## Project layout

```
app/
  main.py          FastAPI: /health + POST /extract-fields
  config.py        env-driven settings
  schema.py        Pydantic models = the strict extraction schema
  prompts.py       template-aware extraction prompt
  anchors.py       deterministic regex cross-check (proposal #, Organization:)
  extractors/
    base.py        Extractor ABC
    gemini.py      GeminiExtractor (default, free tier)
    claude.py      ClaudeExtractor (optional, lazy import)
    __init__.py    get_extractor() factory keyed on LLM_PROVIDER
tests/
  test_anchors.py  offline test against ../Test POFs/Text File (no API calls)
  run_samples.py   live CLI to extract a folder of real PDFs
```

## Local setup

```bash
cd pof-extraction-poc
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # then fill in GEMINI_API_KEY (free at https://aistudio.google.com/app/apikey)
```

### Run the offline test (free, no key needed)

```bash
python tests/test_anchors.py
# or: pytest tests/test_anchors.py
```

### Run the live extractor over the sample PDFs

```bash
python tests/run_samples.py            # uses ../Test POFs
python tests/run_samples.py --out out  # also writes JSON files
```

### Run the API locally

```bash
uvicorn app.main:app --reload --port 8000
# health:
curl http://localhost:8000/health
```

## Environment variables

| Variable            | Required        | Default                     | Notes |
| ------------------- | --------------- | --------------------------- | ----- |
| `API_KEY`           | recommended     | –                           | Must equal the `x-api-key` header the Named Credential sends. |
| `LLM_PROVIDER`      | no              | `gemini`                    | `gemini` or `claude`. |
| `GEMINI_API_KEY`    | if gemini       | –                           | Free tier key from Google AI Studio. |
| `GEMINI_MODEL`      | no              | `gemini-2.5-flash`          | |
| `ANTHROPIC_API_KEY` | if claude       | –                           | |
| `CLAUDE_MODEL`      | no              | `claude-3-5-sonnet-latest`  | |
| `MAX_FILE_MB`       | no              | `10`                        | |

## Deploy on Railway (dedicated Named Credential)

The Salesforce side uses its own `POF_Extraction_POC_NC` Named Credential (backed by the
`POF_Extraction_POC_EC` External Credential), which points at this service's Railway URL and
sends the `x-api-key` header. The `API_KEY` env var here must match that header value.

- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Set env vars: `API_KEY` (same value as the Named Credential header), `GEMINI_API_KEY`,
  optionally `LLM_PROVIDER`, `GEMINI_MODEL`, `MAX_FILE_MB`.

## Request / response contract

`POST /extract-fields`

```json
{ "opportunityId": "006...", "fileName": "OrderForm.pdf", "fileBase64": "JVBERi0..." }
```

Response (trimmed):

```json
{
  "success": true,
  "requestId": "…",
  "provider": "gemini",
  "model": "gemini-2.5-flash",
  "isSigned": true,
  "lowConfidenceFields": [],
  "anchorChecks": { "proposal_number": { "anchor": "Q-460284", "llm": "Q-460284", "agrees": true } },
  "fields": {
    "proposal_number": "Q-460284",
    "customer_organization": "Stetson University",
    "customer_attn_name": "Jeffery Gates",
    "customer_address": { "street": "421 N Woodland Boulevard", "city": "DeLand", "state": "FL", "zip": "32723" },
    "product_links": [ { "program_name": "Appily Leads", "url": "https://scopes.eab.com/appilyleads" } ],
    "contract_created_date": "2026-05-29",
    "customer_signed_date": "2026-05-29",
    "program_terms": [ { "start_date": "2026-09-01", "end_date": "2027-08-31", "currency": "USD", "total_fee": "26,000.00" } ],
    "invoice_frequency": "Annual",
    "opt_out_type": null,
    "opt_out_date": null,
    "is_signed": true
  }
}
```
