from pydantic import BaseModel, ConfigDict


class ProductBase(BaseModel):
    name: str


class ProductCreate(ProductBase):
    pass


class ProductOut(ProductBase):
    id: int
    last_purchase_price: float | None = 0.0

    model_config = ConfigDict(from_attributes=True)
