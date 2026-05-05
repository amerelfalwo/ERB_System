from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class StockBatchOut(BaseModel):
    id: int
    product_id: int
    purchase_price: Decimal
    current_selling_price: Decimal
    initial_quantity: Decimal
    remaining_quantity: Decimal
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StockBatchUpdate(BaseModel):
    current_selling_price: Decimal
