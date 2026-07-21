from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.domain import InvoiceType


class InvoiceItemCreatePurchase(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    purchase_price: Optional[Decimal] = Field(None, ge=0)
    sell_price: Optional[Decimal] = Field(None, ge=0)
    discount: Optional[Decimal] = Field(Decimal('0'), ge=0)
    tax: Optional[Decimal] = Field(Decimal('0'), ge=0)
    original_invoice_item_id: Optional[int] = None


class InvoiceItemCreateSell(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    sell_price: Optional[Decimal] = Field(None, ge=0)
    purchase_price: Optional[Decimal] = Field(None, ge=0)
    discount: Optional[Decimal] = Field(Decimal('0'), ge=0)
    tax: Optional[Decimal] = Field(Decimal('0'), ge=0)
    original_invoice_item_id: Optional[int] = None

# Backwards-compatible aliases used by tests and older code
InvoiceItemCreateSale = InvoiceItemCreateSell


class InvoiceCreatePurchase(BaseModel):
    party_id: int
    items: List[InvoiceItemCreatePurchase] = Field(..., min_length=1)
    amount_paid: Decimal = Field(Decimal('0'), ge=0)
    delivery_fee: Decimal = Field(Decimal('0'), ge=0)
    total_discount: Optional[Decimal] = Field(Decimal('0'), ge=0)
    total_tax: Optional[Decimal] = Field(Decimal('0'), ge=0)
    reference_number: Optional[str] = None
    issue_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    footer_custom_text: Optional[str] = None


class InvoiceCreateSell(BaseModel):
    party_id: int
    items: List[InvoiceItemCreateSell] = Field(..., min_length=1)
    amount_paid: Decimal = Field(Decimal('0'), ge=0)
    delivery_fee: Decimal = Field(Decimal('0'), ge=0)
    total_discount: Optional[Decimal] = Field(Decimal('0'), ge=0)
    total_tax: Optional[Decimal] = Field(Decimal('0'), ge=0)
    reference_number: Optional[str] = None
    issue_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    footer_custom_text: Optional[str] = None

# Backwards-compatible alias
InvoiceCreateSale = InvoiceCreateSell


class InvoiceItemOut(BaseModel):
    id: int
    batch_id: int
    quantity: Decimal
    unit_price: Decimal
    purchase_price: Optional[Decimal] = None
    sell_price: Optional[Decimal] = None
    product_name: Optional[str] = None
    already_returned_qty: Optional[Decimal] = Decimal('0')
    discount: Optional[Decimal] = Decimal('0')
    tax: Optional[Decimal] = Decimal('0')
    original_invoice_item_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class InvoiceOut(BaseModel):
    id: int
    party_id: int
    party_name: Optional[str] = None
    invoice_type: InvoiceType
    total_amount: Decimal
    subtotal: Decimal = Decimal('0')
    total_discount: Decimal = Decimal('0')
    total_tax: Decimal = Decimal('0')
    delivery_fee: Decimal = Decimal('0')
    reference_number: Optional[str] = None
    issue_date: datetime
    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    footer_custom_text: Optional[str] = None
    created_at: datetime
    items: List[InvoiceItemOut]
    paid_amount: Decimal
    balance: Decimal
    status: str
    previous_balance: Optional[Decimal] = None
    total_balance_after: Optional[Decimal] = None
    invoice_profit: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)


class InvoiceListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    data: List[InvoiceOut]


class PaymentOut(BaseModel):
    id: int
    amount: Decimal
    payment_date: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
