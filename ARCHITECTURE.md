# POF Validation — Architecture

This document explains the end-to-end architecture of the **Program Order Form (POF) AI
validation** solution: how a contract PDF on a Salesforce Opportunity is read by an LLM,
turned into structured data, and validated against the CPQ Proposal (Quote) and Opportunity.

---

## 1. Problem & approach

EAB / Seramount POFs are semi-structured PDFs (≈90% follow a template) that are signed via
DocuSign. The original approach (MarkItDown OCR + Apex regex/Levenshtein) did not scale: the
linearized text, DocuSign overlays, and template variations broke brittle pattern matching.

The new approach replaces regex parsing with **LLM-based structured extraction**:

- A vision-capable LLM reads the PDF and returns JSON constrained to a strict schema.
- A small external **FastAPI** service hosts the extraction (provider-agnostic).
- **Salesforce Apex** owns all the business logic: it fetches the PDF, calls the service,
  queries CPQ data, and runs the field-by-field comparison.
- A **Lightning Web Component** drives the UX on the Opportunity record page.

Design principle: **the service only extracts; Salesforce decides.** No Salesforce data leaves
the org — only the PDF is sent out, and only structured fields come back.

---

## 2. High-level diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ Salesforce (Opportunity record page)                                  │
│                                                                       │
│  opportunityPdfProcessor (LWC)                                        │
│        │  "Validate POF with AI"                                      │
│        ▼                                                              │
│  PofAiValidationController (Apex)                                     │
│    1. selectPdf()        → ContentVersion (PDF) on the Opportunity    │
│    2. callExtractionService() ──── Named Credential ───────────┐      │
│    3. queryProposalContext() → Quote + Groups + Lines + Opp     │     │
│    4. buildComparisons()    → field-by-field validation         │     │
│        ▲                                                        │     │
│        └──────────── PofValidationResult ──────────────────────┘     │
└────────────────────────────────────────────────────────────────┼────┘
                                                                   │ HTTPS
                                          callout:POF_Extraction_POC_NC
                                          (POST /extract-fields, x-api-key)
                                                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Railway — FastAPI "POF Structured Extraction Service"                 │
│                                                                       │
│  POST /extract-fields                                                 │
│    • auth (x-api-key)                                                  │
│    • decode + size-check PDF                                          │
│    • _extract_with_resilience():                                      │
│         retry w/ backoff  →  provider failover                        │
│    • build deterministic anchor cross-checks                          │
│         │                                                             │
│         ▼                                                             │
│  Extractor (provider-agnostic)                                        │
│    ├── GeminiExtractor  (default, multi-model rotation)  ── Gemini API │
│    └── ClaudeExtractor  (optional)                       ── Anthropic  │
│         returns ExtractedFields (Pydantic schema)                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Components

### 3.1 Lightning Web Component — `opportunityPdfProcessor`
`force-app/main/default/lwc/opportunityPdfProcessor/`

- Lets the user pick which attached PDF to validate (defaults to the latest).
- **"Validate POF with AI"** button → calls `PofAiValidationController.validateOpportunityPof`.
- Renders the result:
  - **Summary** (matches / total, signed yes/no, low-confidence fields).
  - **Comparison table** — leading green-tick / red-error status per row, Salesforce value,
    PDF value, score, and details. Fixed-layout + wrapping so it stays inside the card.
  - **Add-on / non-standard paragraphs** — each highlighted separately for manual review.
  - **All extracted fields** — raw extraction for human review.
- Key getters: `aiComparisonRows` (per-row status/icon/row-class), `aiAddOnParagraphs`.

### 3.2 Apex — `PofAiValidationController`
`force-app/main/default/classes/PofAiValidationController.cls`

The orchestrator and rules engine. Responsibilities:

1. **`selectPdf`** — finds the chosen (or latest) PDF `ContentVersion` linked to the Opportunity,
   with size guard (`MAX_PDF_BYTES`).
2. **`callExtractionService`** — base64-encodes the PDF and POSTs to
   `callout:POF_Extraction_POC_NC/extract-fields` (120s timeout). Auth/endpoint come from the
   Named Credential, so no secrets live in code.
3. **`queryProposalContext`** — loads the validation context in bulk:
   - Opportunity: `Contract_Signature_Date__c`, `List_of_Product_Families__c`, primary quote.
   - Quote (`SBQQ__Quote__c`): name, institution, contact, address, MSA date, invoice
     frequency, opt-out type/penalty/early-termination date, start/end.
   - **Groups** (`SBQQ__QuoteLineGroup__c`) = the "Program Tables".
   - **Lines** (`SBQQ__QuoteLine__c`) aggregated per group: summed customer total, product
     names, and quantities.
4. **`buildComparisons`** — produces the field-by-field result (see §5).

Result shapes (all `@AuraEnabled`): `PofValidationResult`, `FieldComparison`,
`ExtractedFieldRow`, plus the internal `ProposalContext`.

> `PofClaudeVerificationController` is a thin delegate that calls the same method (kept for the
> pre-existing "Verify with Claude" button).

### 3.3 Connectivity — Named & External Credentials
`force-app/main/default/namedCredentials/POF_Extraction_POC_NC` +
`externalCredentials/POF_Extraction_POC_EC`

- Named Credential stores the Railway base URL.
- External Credential stores the API key, sent as the `x-api-key` header.
- Principal access is granted via the `External_Credential_Principal_Access` permission set.
- The `API_KEY` env var on Railway **must equal** the External Credential secret.

### 3.4 Python service — FastAPI
`pof-extraction-poc/app/`

| File | Role |
|------|------|
| `main.py` | FastAPI app; `GET /health`, `POST /extract-fields`; `_extract_with_resilience`. |
| `config.py` | Env-driven `Settings` (provider, models, API key, retry, limits). |
| `schema.py` | Pydantic `ExtractedFields` — the strict JSON shape the LLM must return. |
| `prompts.py` | Template-aware extraction prompt (anchors, DocuSign handling, picklist mapping). |
| `extractors/base.py` | `Extractor` ABC (`extract(pdf_bytes, file_name) -> ExtractedFields`). |
| `extractors/gemini.py` | Default provider; inline PDF + `response_schema`; multi-model rotation. |
| `extractors/claude.py` | Optional provider; tool-use forces structured output. |
| `extractors/__init__.py` | `get_extractor(provider)` factory (cached). |
| `retry.py` | `is_transient_error` + `call_with_retries` (exponential backoff). |
| `anchors.py` | Deterministic regex cross-checks (proposal #, organization) vs the LLM output. |

Deployment files: `Dockerfile`, `.dockerignore`, `Procfile`, `railway.json`, `requirements.txt`.

---

## 4. Request / response contract

**Request** — `POST /extract-fields` (header `x-api-key`):
```json
{ "opportunityId": "006...", "fileName": "OrderForm_Q-1234.pdf", "fileBase64": "<base64 PDF>" }
```

**Response** (`ExtractResponse`):
```json
{
  "success": true,
  "requestId": "uuid",
  "provider": "gemini",
  "model": "gemini-3.5-flash",
  "fields": { /* ExtractedFields */ },
  "isSigned": true,
  "lowConfidenceFields": ["..."],
  "anchorChecks": { /* deterministic cross-checks */ },
  "rawTextChars": 12345,
  "bodyParagraphs": ["This Program Order Form is made pursuant to ...", "..."],
  "excludedParagraphs": ["EAB Global, Inc.", "Total USD 428,610.00", "PROPOSAL | Q-1234", "..."],
  "message": "POF processed successfully."
}
```

---

## 5. Validation logic (Apex)

`buildComparisons` returns one `FieldComparison` per data point. Matchers:

- `compareText` — normalized (case/punctuation-insensitive) with substring tolerance.
- `comparePicklist` — **exact** normalized equality only (so `Annual` ≠ `Semi-Annual`).
- `compareDate` — ISO date equality.
- `compareAmount` — parses printed amounts (`"53,343.00"` → `53343.00`) and compares.
- `compareCount` / `comparePresence` — counts and boolean assertions.

Data points validated:

| Check | Salesforce source | Rule |
|-------|-------------------|------|
| Proposal Number | `Quote.Name` | text |
| Customer Name | `Primary_Contact_Institution__c` | text |
| Contact Person Name | `PrimaryContactName__c` | text |
| Customer Address | `PrimaryContactAddress__c` | text |
| Master Agreement Date | `Negotiated_MSA_Date__c` | date |
| Invoice Frequency | `Invoice_Frequency__c` | picklist (exact) |
| Number of Program Tables | count of Groups | count |
| Per-table Start / End Date | Group `SBQQ__StartDate__c` / `SBQQ__EndDate__c` | paired by **sequence + date** |
| Per-table Total | sum of group's `SBQQ__CustomerTotal__c` | amount |
| Per-table Products | group's `SBQQ__ProductName__c` | normalized set match |
| Per-table Quantities | group's `SBQQ__Quantity__c` | numeric per product |
| Products vs Families | `Opportunity.List_of_Product_Families__c` | each POF product within approved set |
| Supplemental Fees Statement | (presence) | present = pass |
| Opt Out Type | `Opt_Out__c` | picklist (exact) |
| Opt Out Date | `Contract_Early_Termination_Date__c` | date |
| Opt Out Penalty Amount | `Opt_Out_Penalty_Amount__c` | amount |
| Customer Signature Present | `isSigned` | assertion |
| Customer Signed Date | `Opportunity.Contract_Signature_Date__c` | date |
| Add-on paragraphs | — | each highlighted for review |

Program Tables map to Groups by **sequence index**, then the paired dates must also match
("both" strategy). Product / quantity matching is name-normalized because PDF wording can
differ from `SBQQ__ProductName__c`.

---

## 6. Resilience

LLM providers (especially Gemini's free tier) intermittently return `429/500/503`
("overloaded / high demand"). Three layers handle this transparently:

1. **Backoff retries** — `call_with_retries` retries transient errors with exponential delay
   (`EXTRACT_MAX_RETRIES`, `EXTRACT_RETRY_BASE_MS`).
2. **Multi-model rotation (Gemini)** — `GEMINI_MODEL` may be a comma-separated list; on a
   transient error the extractor rolls to the next model. The model that served the request is
   reported back in `response.model`.
3. **Provider failover** — set `LLM_FALLBACK_PROVIDER` (e.g. `claude`) so a Gemini outage fails
   over to Claude. Only the model that actually answered is reported.

The deterministic **anchor checks** (`anchors.py`) provide a cheap safeguard against
hallucination on high-value fields (proposal number, organization).

---

## 7. Configuration (environment variables)

| Var | Purpose |
|-----|---------|
| `API_KEY` | Shared secret; must match the Salesforce External Credential `x-api-key`. |
| `LLM_PROVIDER` | `gemini` (default) or `claude`. |
| `LLM_FALLBACK_PROVIDER` | Optional automatic failover provider. |
| `GEMINI_API_KEY` | Google AI Studio key. |
| `GEMINI_MODEL` | Single model or comma-separated rotation list. |
| `ANTHROPIC_API_KEY` / `CLAUDE_MODEL` | Only if Claude is used. |
| `EXTRACT_MAX_RETRIES` / `EXTRACT_RETRY_BASE_MS` | Backoff tuning. |
| `MAX_FILE_MB` / `LOG_LEVEL` | Upload limit / logging. |

See `.env.example` for a ready-to-edit template.

---

## 8. Deployment

- **Service**: Railway builds `pof-extraction-poc` (root directory = `pof-extraction-poc`) from
  GitHub on push (or `railway up` via CLI). Verify with `GET /health`.
- **Salesforce**: deploy `PofAiValidationController`, `PofClaudeVerificationController`, the
  `opportunityPdfProcessor` LWC, and the Named/External Credentials + permission set. Place the
  LWC on the Opportunity record page so `recordId` is populated.

---

## 9. Extension points

- **New field**: add it to `schema.py` + `prompts.py`, redeploy the service, then add a
  `FieldComparison` in `buildComparisons`.
- **New provider**: implement `Extractor` and register it in `extractors/__init__.py`.
- **Scope-link URL validation**: replace the `List_of_Product_Families__c` stand-in once the
  approved scope-link master list is available.
