from decimal import Decimal
from typing import List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.domain import Invoice, InvoiceItem, InvoiceType, Payment, Product, StockBatch
from app.schemas.report import (
    InventoryBatchOut,
    InventoryProductOut,
    InventoryReportOut,
    ProfitItem,
    ProfitReportOut,
    StatementItem,
    StatementOut,
)


def profit_report(db: Session) -> ProfitReportOut:
    stmt = select(InvoiceItem, StockBatch, Invoice).join(
        StockBatch, StockBatch.id == InvoiceItem.batch_id
    ).join(Invoice, Invoice.id == InvoiceItem.invoice_id).where(Invoice.invoice_type == InvoiceType.SALE)
    rows = db.execute(stmt).all()

    items: List[ProfitItem] = []
    total_profit = Decimal("0")
    for invoice_item, batch, invoice in rows:
        profit = (invoice_item.unit_price - batch.purchase_price) * invoice_item.quantity
        total_profit += profit
        items.append(
            ProfitItem(
                invoice_id=invoice.id,
                batch_id=batch.id,
                quantity=invoice_item.quantity,
                purchase_price=batch.purchase_price,
                selling_price=invoice_item.unit_price,
                profit=profit,
            )
        )

    return ProfitReportOut(total_profit=total_profit, items=items)


def inventory_report(db: Session) -> InventoryReportOut:
    products = db.execute(select(Product)).scalars().all()
    items: List[InventoryProductOut] = []
    total_value = Decimal("0")
    for product in products:
        batches = db.execute(select(StockBatch).where(StockBatch.product_id == product.id)).scalars().all()
        product_value = Decimal("0")
        batch_items = [
            InventoryBatchOut(
                batch_id=b.id,
                purchase_price=b.purchase_price,
                selling_price=b.current_selling_price,
                remaining_quantity=b.remaining_quantity,
            )
            for b in batches
        ]
        for b in batches:
            product_value += b.purchase_price * b.remaining_quantity
        total_value += product_value
        items.append(
            InventoryProductOut(
                product_id=product.id,
                product_name=product.name,
                batches=batch_items,
                product_value=product_value,
            )
        )
    return InventoryReportOut(products=items, total_value=total_value)


def party_statement(db: Session, party_id: int) -> StatementOut:
    invoices = db.execute(select(Invoice).where(Invoice.party_id == party_id)).scalars().all()
    items: List[StatementItem] = []
    total_balance = Decimal("0")

    for invoice in invoices:
        paid_total = db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.invoice_id == invoice.id)
        ).scalar_one()
        balance = invoice.total_amount - paid_total
        total_balance += balance
        items.append(
            StatementItem(
                invoice_id=invoice.id,
                invoice_type=invoice.invoice_type.value,
                invoice_total=invoice.total_amount,
                paid_total=paid_total,
                balance=balance,
            )
        )

    return StatementOut(party_id=party_id, items=items, total_balance=total_balance)
