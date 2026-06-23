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


class LedgerTransaction(BaseModel):
    date: str
    type: str
    reference: str
    amount: Decimal
    balance: Decimal

class StatementOut(BaseModel):
    party_id: int
    transactions: List[LedgerTransaction]
    total_balance: Decimal

class MonthlySales(BaseModel):
    name: str
    sales: Decimal
    purchases: Decimal

class RecentTransaction(BaseModel):
    date: str
    description: str
    value: Decimal
    status: str

class DashboardAnalyticsOut(BaseModel):
    total_profit: Decimal
    stock_valuation: Decimal
    outstanding_balances: Decimal
    customer_receivables: Decimal
    supplier_payables: Decimal
    monthly_sales: List[MonthlySales]
    recent_transactions: List[RecentTransaction]

class PartyProfitSummaryOut(BaseModel):
    party_id: int
    party_name: str
    total_profit: Decimal
    total_revenue: Decimal
    invoice_count: int

