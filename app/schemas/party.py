from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.domain import PartyType


class PartyBase(BaseModel):
    name: str
    party_type: PartyType
    phone: Optional[str] = None
    address: Optional[str] = None


class PartyCreate(PartyBase):
    initial_balance: Optional[Decimal] = Decimal("0")


class PartyOut(PartyBase):
    id: int
    initial_balance: Optional[Decimal] = Decimal("0")

    model_config = ConfigDict(from_attributes=True)
