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

class NetProfitReportOut(BaseModel):
    gross_profit: Decimal
    total_expenses: Decimal
    net_profit: Decimal

class DashboardKpis(BaseModel):
    total_sales: Decimal
    total_purchases: Decimal
    gross_profit: Decimal
    total_expenses: Decimal
    net_profit: Decimal
    total_invoices_count: int
    outstanding_balance: Decimal

class DashboardTrendPoint(BaseModel):
    period: str
    sales: Decimal
    purchases: Decimal
    profit: Decimal

class TopProductItem(BaseModel):
    product_name: str
    qty_sold: Decimal
    revenue: Decimal

class LowStockProductItem(BaseModel):
    product_name: str
    remaining_qty: Decimal
    min_stock: Decimal

class TopPartyItem(BaseModel):
    party_name: str
    type: str
    total_amount: Decimal

class UnifiedDashboardOut(BaseModel):
    kpis: DashboardKpis
    trend: List[DashboardTrendPoint]
    top_products: List[TopProductItem]
    low_stock_products: List[LowStockProductItem]
    top_parties: List[TopPartyItem]
