from typing import Optional
from pydantic import BaseModel, ConfigDict


class ProductBase(BaseModel):
    name: str


class ProductCreate(ProductBase):
    purchase_price: Optional[float] = 0.0
    sell_price: Optional[float] = 0.0


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    purchase_price: Optional[float] = None
    sell_price: Optional[float] = None


class ProductOut(ProductBase):
    id: int
    last_purchase_price: float | None = 0.0
    purchase_price: float | None = 0.0
    average_cost: float | None = 0.0
    sell_price: float | None = 0.0

    model_config = ConfigDict(from_attributes=True)
