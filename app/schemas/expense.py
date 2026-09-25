from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

class ExpenseBase(BaseModel):
    description: str = Field(..., title="Description", min_length=1)
    amount: float = Field(..., title="Amount", gt=0)
    expense_date: date = Field(..., title="Expense Date")
    category: Optional[str] = Field(None, title="Category")

class ExpenseCreate(ExpenseBase):
    pass

class ExpenseRead(ExpenseBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    created_by: Optional[int]
    created_at: datetime

class ExpenseSummaryRead(BaseModel):
    total_expenses: Decimal
    expenses_count: int
    top_category: Optional[str] = None
