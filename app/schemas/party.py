from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.domain import PartyType


class PartyBase(BaseModel):
    name: str
    phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    credit_limit: Optional[Decimal] = Decimal("0")


class CustomerCreate(PartyBase):
    initial_balance: Optional[Decimal] = Decimal("0")


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    initial_balance: Optional[Decimal] = None
    notes: Optional[str] = None
    credit_limit: Optional[Decimal] = None


class SupplierCreate(PartyBase):
    initial_balance: Optional[Decimal] = Decimal("0")


class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    initial_balance: Optional[Decimal] = None
    notes: Optional[str] = None
    credit_limit: Optional[Decimal] = None


class PartyCreate(PartyBase):
    """Generic create schema used by the legacy /parties endpoint."""
    party_type: PartyType
    initial_balance: Optional[Decimal] = Decimal("0")


class PartyUpdate(BaseModel):
    """Generic update schema used by the legacy /parties endpoint."""
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    initial_balance: Optional[Decimal] = None
    notes: Optional[str] = None
    credit_limit: Optional[Decimal] = None


class PartyOut(PartyBase):
    id: int
    party_type: PartyType
    initial_balance: Optional[Decimal] = Decimal("0")
    calculated_balance: Optional[Decimal] = Decimal("0")
    total_profit: Optional[Decimal] = Decimal("0")
    payment_status: Optional[str] = None
    notes: Optional[str] = None
    credit_limit: Optional[Decimal] = Decimal("0")

    model_config = ConfigDict(from_attributes=True)
