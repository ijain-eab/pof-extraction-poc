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
    """One product row of a Program Term table.

    Hierarchy is encoded FLAT: every row is emitted in top-to-bottom reading order and points at
    its visual container via parent_id / parent_name (decided from the printed indentation, NOT
    computed from indent_level). A single row may carry an amount, a quantity, both, or neither, at
    ANY level — put each value on the exact row the PDF prints it on; never force amounts onto the
    top row or drop a quantity that sits on a parent row.
    """
    program: Optional[str] = Field(None, description="Product / row name exactly as printed, e.g. 'Appily Leads', 'Appily Membership', 'Administrative & Travel Fee'")
    detail: Optional[str] = Field(None, description="Membership / configuration criteria printed on this row, verbatim, e.g. 'Grad Years:2027; 2028, States:MA, GPA Minimum:2.50, Zip Codes:select zip codes'. Empty if none.")
    quantity: Optional[str] = Field(None, description="Quantity printed on this row, e.g. '20,000 Inquiries', '5,001 Recipients', '1 destinations', 'Unlimited'. May appear on a parent OR a sub row. Empty if none.")
    currency: Optional[str] = Field(None, description="Currency code for this row's fee, e.g. 'USD'; empty if this row shows no fee")
    fee: Optional[str] = Field(None, description="Fee/amount printed on THIS row as shown, e.g. '53,343.00'. Put it on whatever row the PDF shows it (top product, a fee sub-row, or a child even when the parent shows none). Empty if this row shows no amount.")
    # Hierarchy (flat encoding) — see class docstring
    item_id: Optional[str] = Field(None, description="Stable id for THIS row, unique within the Program Term, assigned in reading order: 'i1','i2','i3',...")
    parent_id: Optional[str] = Field(None, description="item_id of the row this row is visually nested under (its container). Empty string for a top-level product. Decide from the printed indentation/grouping, NOT from indent_level arithmetic.")
    parent_name: Optional[str] = Field(None, description="Name of the parent/container row (cross-check for parent_id). Empty for a top-level product.")
    indent_level: Optional[int] = Field(None, description="How deeply this row is indented (1 = outermost product, 2 = sub, 3 = sub-sub, deeper if printed). Informational only; do NOT use it to infer the parent and do NOT assume a maximum depth.")


class ProgramTerm(BaseModel):
    start_date: Optional[str] = Field(None, description="Program Term start date in ISO YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="Program Term end date in ISO YYYY-MM-DD")
    currency: Optional[str] = Field(None, description="Currency code for the term total")
    total_fee: Optional[str] = Field(None, description="Total fee for this term as printed")
    line_items: List[LineItem] = Field(default_factory=list, description="Line items within this term")


class OneTimeFeeTerm(BaseModel):
    """A 'One Time Fee:' table, scoped to a Program Term (e.g. an Implementation Fee)."""
    start_date: Optional[str] = Field(None, description="Program Term start date for this one-time fee (ISO YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="Program Term end date for this one-time fee (ISO YYYY-MM-DD)")
    currency: Optional[str] = Field(None, description="Currency code for the total, e.g. 'USD'")
    total_fee: Optional[str] = Field(None, description="The 'Total' row for this one-time-fee table as printed")
    line_items: List[LineItem] = Field(default_factory=list, description="One-time fee lines (program + fee description + amount) within this term")


class EstimateItem(BaseModel):
    label: Optional[str] = Field(None, description="Estimate / passthrough category, e.g. 'Estimated Postage Costs', 'Estimated Media Costs', 'Estimated List Costs'")
    currency: Optional[str] = Field(None, description="Currency code, e.g. 'USD'")
    fee: Optional[str] = Field(None, description="Estimated amount as printed, e.g. '5,650.00'")


class EstimatePassthrough(BaseModel):
    """An 'Estimates and Passthroughs' block (or an embedded 'Estimated Postage and Media' table), scoped to a Program Term."""
    start_date: Optional[str] = Field(None, description="Program Term start date for these estimates (ISO YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="Program Term end date for these estimates (ISO YYYY-MM-DD)")
    currency: Optional[str] = Field(None, description="Currency code for the amounts, e.g. 'USD'")
    items: List[EstimateItem] = Field(default_factory=list, description="Estimated / passthrough cost lines within this term")


class SupplementalFeeEntry(BaseModel):
    """One per-unit overage rate line from 'Exhibit A: Supplemental Fees'."""
    program: Optional[str] = Field(None, description="Program / product the rate applies to, e.g. 'Appily Candidates', 'Senior New Names'")
    fee_type: Optional[str] = Field(None, description="Rate type, e.g. 'Additional Program', 'Additional Postage', 'Additional Media'")
    currency: Optional[str] = Field(None, description="Currency code, e.g. 'USD'")
    amount: Optional[str] = Field(None, description="Per-unit rate as printed, e.g. '4,940.00'")
    unit: Optional[str] = Field(None, description="Rate unit exactly as printed: '/M' (per 1,000) or '/C' (per 100)")


class SupplementalFeeTerm(BaseModel):
    """An 'Exhibit A: Supplemental Fees' schedule, scoped to a Program Term."""
    start_date: Optional[str] = Field(None, description="Program Term start date for this schedule (ISO YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="Program Term end date for this schedule (ISO YYYY-MM-DD)")
    entries: List[SupplementalFeeEntry] = Field(default_factory=list, description="Per-unit overage rate lines within this term")


class BillingInfo(BaseModel):
    """The 'OPTIONAL FOR BILLING PURPOSES ONLY' block. Fields are null when only blank underscore lines are present."""
    invoice_email: Optional[str] = Field(None, description="'Invoices should be sent to this Email Address' value; null if the line is blank")
    billing_contact_name: Optional[str] = Field(None, description="'Billing Contact Name' value; null if blank")
    billing_contact_email: Optional[str] = Field(None, description="'Billing Contact Email Address' value; null if blank")
    billing_contact_phone: Optional[str] = Field(None, description="'Billing Contact Phone' value; null if blank")
    purchase_order_number: Optional[str] = Field(None, description="'Purchase Order No. (if applicable)' value; null if blank")


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
    one_time_fees: List[OneTimeFeeTerm] = Field(default_factory=list, description="'One Time Fee' tables (e.g. Implementation Fee), one entry per Program Term; [] if none")
    estimates_passthroughs: List[EstimatePassthrough] = Field(default_factory=list, description="'Estimates and Passthroughs' (and embedded 'Estimated Postage and Media') tables, one entry per Program Term; [] if none")
    invoicing_terms: Optional[str] = Field(None, description="Verbatim text of the Invoicing section")
    invoice_frequency: Optional[str] = Field(None, description="Billing cadence mapped to EXACTLY one Salesforce picklist value: 'Annual', 'Semi-Annual', 'Quarterly', 'Monthly', 'ES-75-25', or 'ES-50-50'. Use null if it cannot be determined.")

    # Opt-out / termination
    opt_out_type: Optional[str] = Field(None, description="Opt-out / termination type mapped to EXACTLY one Salesforce picklist value: 'One Point in Time Opt Out Without Penalty Fee', 'Board Approval Opt Out', 'Annual Opt Out On Anniversary With Stated Penalty Fee', 'Annual Opt Out on Anniversary without penalty fee', 'One Point in Time Opt Out With Stated Penalty Fee', 'Funds Appropriation Opt Out', 'Termination for Convenience', 'Opt In - Point in Time', or 'Opt In - Annual'. Use null if no opt-out/termination clause is present.")
    opt_out_date: Optional[str] = Field(None, description="Opt-out / termination deadline date (ISO) if stated; otherwise null")
    opt_out_penalty_amount: Optional[str] = Field(None, description="Opt-out / early termination penalty or fee amount as printed, if any; otherwise null")

    # Supplemental fees
    supplemental_fees_present: Optional[bool] = Field(None, description="True if a Supplemental Fees statement / exhibit is present in the document")
    supplemental_fees_statement: Optional[str] = Field(None, description="Verbatim text of the Supplemental Fees statement, if present")
    # Exhibit A overage rate schedule (distinct from the supplemental_fees_statement prose above)
    supplemental_fee_schedule: List[SupplementalFeeTerm] = Field(default_factory=list, description="'Exhibit A: Supplemental Fees' per-unit overage rate schedule, one entry per Program Term; [] if no Exhibit A")

    # Billing (optional block)
    billing_info: Optional[BillingInfo] = Field(None, description="'OPTIONAL FOR BILLING PURPOSES ONLY' block; fields are null when only blank underscore lines are present")

    # Meta
    is_signed: Optional[bool] = Field(None, description="True only if a real customer signature/name/date is present (not the placeholder)")
    additional_terms: Optional[str] = Field(None, description="Verbatim 'Additional Terms' / modifications text, if any")
    additional_paragraphs: List[str] = Field(default_factory=list, description="Each add-on / non-standard / negotiated paragraph that is NOT part of the standard template, returned as a separate verbatim string")
    low_confidence_fields: List[str] = Field(default_factory=list, description="Names of fields the model is unsure about")
    extraction_notes: Optional[str] = Field(None, description="Any caveats about the extraction")
