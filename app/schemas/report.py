from decimal import Decimal
from typing import List

from pydantic import BaseModel


class ProfitItem(BaseModel):
    invoice_id: int
    batch_id: int
    quantity: Decimal
    purchase_price: Decimal
    selling_price: Decimal
    profit: Decimal


class ProfitReportOut(BaseModel):
    total_profit: Decimal
    items: List[ProfitItem]


class InventoryBatchOut(BaseModel):
    batch_id: int
    purchase_price: Decimal
    selling_price: Decimal
    remaining_quantity: Decimal


class InventoryProductOut(BaseModel):
    product_id: int
    product_name: str
    batches: List[InventoryBatchOut]
    product_value: Decimal


class InventoryReportOut(BaseModel):
    products: List[InventoryProductOut]
    total_value: Decimal


class StatementItem(BaseModel):
    invoice_id: int
    invoice_type: str
    invoice_total: Decimal
    paid_total: Decimal
    balance: Decimal


class StatementOut(BaseModel):
    party_id: int
    items: List[StatementItem]
    total_balance: Decimal

class MonthlySales(BaseModel):
    name: str
    sales: Decimal
    purchases: Decimal

class DashboardAnalyticsOut(BaseModel):
    total_profit: Decimal
    stock_valuation: Decimal
    outstanding_balances: Decimal
    monthly_sales: List[MonthlySales]
