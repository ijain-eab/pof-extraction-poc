"""Strict extraction schema for EAB / Seramount Program Order Forms (POFs).

These Pydantic models are passed directly to the LLM as the response schema so the
model is forced to return JSON in exactly this shape. They are intentionally flat and
use simple types (str/bool/list/nested model) for broad provider compatibility.

Convention:
- All dates are normalized by the model to ISO format: "YYYY-MM-DD".
- Any field the model cannot find is returned as null (None), never guessed.
- DocuSign placeholder tokens like "{{Signer1_Name}}" must be treated as "not filled"
  and returned as null.
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class Address(BaseModel):
    street: Optional[str] = Field(None, description="Street line(s) of the customer address")
    city: Optional[str] = Field(None, description="City")
    state: Optional[str] = Field(None, description="State / region code, e.g. 'DC', 'FL'")
    zip: Optional[str] = Field(None, description="Postal / ZIP code")


class ProductLink(BaseModel):
    program_name: Optional[str] = Field(None, description="Program / product name, e.g. 'Appily Leads'")
    url: Optional[str] = Field(None, description="The Program Scope URL for that product")


class LineItem(BaseModel):
    program: Optional[str] = Field(None, description="Program or product name for this line")
    detail: Optional[str] = Field(None, description="Sub-item / description / configuration text")
    quantity: Optional[str] = Field(None, description="Quantity as printed, e.g. '20,000 Inquiries'")
    currency: Optional[str] = Field(None, description="Currency code, e.g. 'USD'")
    fee: Optional[str] = Field(None, description="Fee amount as printed, e.g. '26,000.00'")


class ProgramTerm(BaseModel):
    start_date: Optional[str] = Field(None, description="Program Term start date in ISO YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="Program Term end date in ISO YYYY-MM-DD")
    currency: Optional[str] = Field(None, description="Currency code for the term total")
    total_fee: Optional[str] = Field(None, description="Total fee for this term as printed")
    line_items: List[LineItem] = Field(default_factory=list, description="Line items within this term")


class ExtractedFields(BaseModel):
    # Identity
    proposal_number: Optional[str] = Field(None, description="Proposal number from the 'PROPOSAL | Q-######' footer")
    customer_organization: Optional[str] = Field(None, description="Customer organization from the 'Organization:' field")
    customer_attn_name: Optional[str] = Field(None, description="Contact name from the 'Attn:' line")
    customer_address: Optional[Address] = Field(None, description="Customer mailing address")

    # Products
    product_links: List[ProductLink] = Field(default_factory=list, description="Program Scope product links")

    # Dates
    contract_created_date: Optional[str] = Field(None, description="The 'Date:' near the top of the form (ISO)")
    master_agreement_date: Optional[str] = Field(None, description="The 'Master Agreement dated as of ...' date (ISO)")
    return_by_date: Optional[str] = Field(None, description="The 'no later than ...' return-by date (ISO)")

    # Signatures
    eab_signer_name: Optional[str] = Field(None, description="EAB/Seramount signer name (usually preprinted)")
    eab_signed_date: Optional[str] = Field(None, description="Date signed by EAB/Seramount (ISO)")
    customer_signer_name: Optional[str] = Field(None, description="Actual customer signer name; null if only the {{Signer1_Name}} placeholder is present")
    customer_signer_title: Optional[str] = Field(None, description="Customer signer title; null if only the placeholder is present")
    customer_signed_date: Optional[str] = Field(None, description="Date the customer signed (ISO); null if unsigned")

    # Commercials
    program_terms: List[ProgramTerm] = Field(default_factory=list, description="One entry per Program Term block")
    invoicing_terms: Optional[str] = Field(None, description="Verbatim text of the Invoicing section")
    invoice_frequency: Optional[str] = Field(None, description="Normalized billing cadence: Annual, Quarterly, Monthly, One-Time, or Unknown")

    # Opt-out / termination
    opt_out_type: Optional[str] = Field(None, description="Opt-out / termination type if stated; otherwise null")
    opt_out_date: Optional[str] = Field(None, description="Opt-out / termination deadline date (ISO) if stated; otherwise null")

    # Meta
    is_signed: Optional[bool] = Field(None, description="True only if a real customer signature/name/date is present (not the placeholder)")
    additional_terms: Optional[str] = Field(None, description="Verbatim 'Additional Terms' / modifications text, if any")
    low_confidence_fields: List[str] = Field(default_factory=list, description="Names of fields the model is unsure about")
    extraction_notes: Optional[str] = Field(None, description="Any caveats about the extraction")
