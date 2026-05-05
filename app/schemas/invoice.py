from datetime import datetime
from decimal import Decimal
from typing import List

from pydantic import BaseModel, ConfigDict

from app.models.domain import InvoiceType


class InvoiceItemCreatePurchase(BaseModel):
    product_id: int
    quantity: Decimal
    purchase_price: Decimal
    selling_price: Decimal


class InvoiceItemCreateSale(BaseModel):
    product_id: int
    quantity: Decimal


class InvoiceCreatePurchase(BaseModel):
    party_id: int
    items: List[InvoiceItemCreatePurchase]


class InvoiceCreateSale(BaseModel):
    party_id: int
    items: List[InvoiceItemCreateSale]


class InvoiceItemOut(BaseModel):
    id: int
    batch_id: int
    quantity: Decimal
    unit_price: Decimal

    model_config = ConfigDict(from_attributes=True)


class InvoiceOut(BaseModel):
    id: int
    party_id: int
    invoice_type: InvoiceType
    total_amount: Decimal
    created_at: datetime
    items: List[InvoiceItemOut]
    paid_amount: Decimal
    balance: Decimal
    status: str

    model_config = ConfigDict(from_attributes=True)
