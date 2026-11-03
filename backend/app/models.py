from decimal import Decimal
from typing import Literal, Annotated
from pydantic import BaseModel, Field, ConfigDict

Money = Annotated[Decimal, Field(max_digits=18, decimal_places=4, allow_inf_nan=False)]
Quantity = Annotated[Decimal, Field(max_digits=18, decimal_places=6, allow_inf_nan=False)]


class Evidence(BaseModel):
    document_id: str = ''
    filename: str = ''
    page: int | None = None
    excerpt: str = ''
    method: str = 'text'


class LineItem(BaseModel):
    description: str
    sku: str = ''
    quantity: Quantity | None = None
    unit_price: Money | None = None
    amount: Money | None = None
    evidence: Evidence | None = None


class Invoice(BaseModel):
    model_config = ConfigDict(extra='ignore')
    invoice_number: str = ''
    invoice_date: str = ''
    due_date: str = ''
    vendor_name: str = ''
    vendor_id: str = ''
    tax_id: str = ''
    po_number: str = ''
    currency: str = ''
    subtotal: Money | None = None
    tax_amount: Money | None = None
    total: Money | None = None
    bank_account: str = ''
    tax_inclusive: bool = False
    items: list[LineItem] = Field(default_factory=list)
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    extraction_notes: list[str] = Field(default_factory=list)
    extraction_method: str = 'local'
    ai_runs: list[dict] = Field(default_factory=list)


class Vendor(BaseModel):
    vendor_id: str
    name: str
    status: str = 'unknown'
    tax_id: str = ''
    bank_account: str = ''
    aliases: list[str] = Field(default_factory=list)
    evidence: Evidence = Field(default_factory=Evidence)


class PurchaseOrder(BaseModel):
    po_number: str
    vendor_id: str = ''
    vendor_name: str = ''
    currency: str
    amount: Money
    amount_basis: Literal['net', 'gross']
    status: str = 'unknown'
    valid_from: str = ''
    valid_to: str = ''
    items: list[LineItem] = Field(default_factory=list)
    evidence: Evidence = Field(default_factory=Evidence)


class HistoricalInvoice(BaseModel):
    invoice_number: str
    vendor_id: str
    po_number: str = ''
    currency: str
    subtotal: Money | None = None
    total: Money
    status: str
    document_hash: str = ''
    items: list[LineItem] = Field(default_factory=list)
    evidence: Evidence = Field(default_factory=Evidence)


class Policy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = 'Standard AP review policy'
    amount_tolerance_percent: Decimal = Field(default=Decimal('2'), ge=0, le=20)
    amount_tolerance_absolute: Decimal = Field(default=Decimal('0'), ge=0, le=1000000)
    unit_price_tolerance_percent: Decimal = Field(default=Decimal('0'), ge=0, le=20)
    require_line_items: bool = True
    check_bank_details: bool = True
    max_invoice_age_days: int = Field(default=365, ge=1, le=3650)
    evidence: Evidence = Field(default_factory=lambda: Evidence(filename='Built-in policy', excerpt='2% PO amount tolerance; no unit-price tolerance; line items required.'))


class Check(BaseModel):
    code: str
    title: str
    status: Literal['pass', 'warning', 'fail', 'info']
    message: str
    route: Literal['ready', 'clarification', 'procurement', 'hold'] = 'ready'
    evidence: list[Evidence] = Field(default_factory=list)


class Review(BaseModel):
    id: str
    document_id: str
    filename: str
    invoice: Invoice
    decision: Literal['ready', 'clarification', 'procurement', 'hold']
    summary: str
    checks: list[Check]
    matched_vendor: Vendor | None = None
    matched_po: PurchaseOrder | None = None
    po_candidates: list[str] = Field(default_factory=list)
    po_context: dict = Field(default_factory=dict)
    reviewed_at: str
    resolution: dict | None = None
    ai_analysis: dict = Field(default_factory=dict)


class Correction(BaseModel):
    invoice: Invoice
    reason: str = Field(min_length=5, max_length=1000)


class Resolution(BaseModel):
    action: Literal['acknowledge', 'request_clarification', 'send_to_procurement', 'investigate']
    note: str = Field(min_length=5, max_length=2000)


class SemanticConfirmation(BaseModel):
    analysis_key: str
    invoice_line: int = Field(ge=0)
    po_line: int = Field(ge=0)
    note: str = Field(min_length=5, max_length=1000)
