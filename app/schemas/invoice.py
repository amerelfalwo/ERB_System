from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.domain import InvoiceType


class InvoiceItemCreatePurchase(BaseModel):
    product_id: int
    quantity: Decimal
    purchase_price: Decimal
    selling_price: Decimal
    original_invoice_item_id: Optional[int] = None


class InvoiceItemCreateSell(BaseModel):
    product_id: int
    quantity: Decimal
    sell_price: Optional[Decimal] = None
    purchase_price: Optional[Decimal] = None
    original_invoice_item_id: Optional[int] = None

# Backwards-compatible aliases used by tests and older code
InvoiceItemCreateSale = InvoiceItemCreateSell


class InvoiceCreatePurchase(BaseModel):
    party_id: int
    items: List[InvoiceItemCreatePurchase]
    amount_paid: Decimal = Decimal('0')
    delivery_fee: Decimal = Decimal('0')
    footer_custom_text: Optional[str] = None


class InvoiceCreateSell(BaseModel):
    party_id: int
    items: List[InvoiceItemCreateSell]
    amount_paid: Decimal = Decimal('0')
    delivery_fee: Decimal = Decimal('0')
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
    original_invoice_item_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class InvoiceOut(BaseModel):
    id: int
    party_id: int
    party_name: Optional[str] = None
    invoice_type: InvoiceType
    total_amount: Decimal
    delivery_fee: Decimal = Decimal('0')
    footer_custom_text: Optional[str] = None
    created_at: datetime
    items: List[InvoiceItemOut]
    paid_amount: Decimal
    balance: Decimal
    status: str
    previous_balance: Optional[Decimal] = None
    total_balance_after: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)
