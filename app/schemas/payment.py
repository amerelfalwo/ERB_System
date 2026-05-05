from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PaymentCreate(BaseModel):
    party_id: int
    amount: Decimal
    invoice_id: Optional[int] = None


class PaymentOut(BaseModel):
    id: int
    party_id: int
    invoice_id: Optional[int]
    amount: Decimal
    payment_date: datetime

    model_config = ConfigDict(from_attributes=True)
