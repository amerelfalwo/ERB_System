from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

class StockBatchOut(BaseModel):
    id: int
    product_id: int
    purchase_price: Decimal
    selling_price: Decimal = Field(validation_alias="current_selling_price")
    initial_quantity: Decimal
    remaining_quantity: Decimal
    created_at: datetime
    party_id: int | None = None
    supplier_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class StockBatchUpdate(BaseModel):
    selling_price: Decimal
