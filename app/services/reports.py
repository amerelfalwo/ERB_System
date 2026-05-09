from decimal import Decimal
from typing import List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.domain import Invoice, InvoiceItem, InvoiceType, Payment, Product, StockBatch, Party
from app.schemas.report import (
    InventoryBatchOut,
    InventoryProductOut,
    InventoryReportOut,
    ProfitItem,
    ProfitReportOut,
    LedgerTransaction,
    StatementOut,
    DashboardAnalyticsOut,
    MonthlySales,
)


def profit_report(db: Session, tenant_id: int) -> ProfitReportOut:
    stmt = select(InvoiceItem, StockBatch, Invoice).join(
        StockBatch, StockBatch.id == InvoiceItem.batch_id
    ).join(Invoice, Invoice.id == InvoiceItem.invoice_id).where(
        Invoice.invoice_type.in_([InvoiceType.SALE, InvoiceType.SALE_RETURN]),
        Invoice.tenant_id == tenant_id,
    )
    rows = db.execute(stmt).all()

    items: List[ProfitItem] = []
    total_profit = Decimal("0")
    seen_invoices: set = set()
    for invoice_item, batch, invoice in rows:
        cost = invoice_item.purchase_price if invoice_item.purchase_price is not None else batch.purchase_price
        sale = invoice_item.sale_price if invoice_item.sale_price is not None else invoice_item.unit_price
        line_profit = (sale - cost) * invoice_item.quantity
        if invoice.invoice_type == InvoiceType.SALE_RETURN:
            line_profit = -line_profit
        if invoice.id not in seen_invoices:
            seen_invoices.add(invoice.id)
            fee = invoice.delivery_fee or Decimal("0")
            if invoice.invoice_type == InvoiceType.SALE_RETURN:
                line_profit += fee
            else:
                line_profit -= fee
        total_profit += line_profit
        items.append(
            ProfitItem(
                invoice_id=invoice.id,
                batch_id=batch.id,
                quantity=invoice_item.quantity,
                purchase_price=cost,
                selling_price=sale,
                profit=line_profit,
            )
        )

    return ProfitReportOut(total_profit=total_profit, items=items)


def party_profit_summary(db: Session, tenant_id: int) -> list:
    rows = db.execute(
        select(Invoice.id, Invoice.invoice_type, Invoice.delivery_fee,
               Party.id.label("party_id"), Party.name.label("party_name"))
        .join(Party, Party.id == Invoice.party_id)
        .where(
            Invoice.invoice_type.in_([InvoiceType.SALE, InvoiceType.SALE_RETURN]),
            Invoice.tenant_id == tenant_id,
            Party.tenant_id == tenant_id,
        )
    ).all()

    invoice_ids = [r.id for r in rows]
    invoice_meta = {r.id: (r.party_id, r.party_name, r.invoice_type, r.delivery_fee or Decimal("0")) for r in rows}

    if not invoice_ids:
        return []

    item_rows = db.execute(
        select(InvoiceItem, StockBatch, Invoice.id.label("inv_id"))
        .join(StockBatch, StockBatch.id == InvoiceItem.batch_id)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(InvoiceItem.invoice_id.in_(invoice_ids))
    ).all()

    party_data: dict = {}
    seen_invoices: set = set()
    for invoice_item, batch, inv_id in item_rows:
        party_id, party_name, inv_type, delivery_fee = invoice_meta[inv_id]
        cost = invoice_item.purchase_price if invoice_item.purchase_price is not None else batch.purchase_price
        sale = invoice_item.sale_price if invoice_item.sale_price is not None else invoice_item.unit_price
        revenue = sale * invoice_item.quantity
        profit = (sale - cost) * invoice_item.quantity
        if inv_type == InvoiceType.SALE_RETURN:
            profit = -profit
            revenue = -revenue
        if party_id not in party_data:
            party_data[party_id] = {"name": party_name, "profit": Decimal("0"), "revenue": Decimal("0"), "invoices": set()}
        if inv_id not in seen_invoices:
            seen_invoices.add(inv_id)
            if inv_type == InvoiceType.SALE_RETURN:
                profit += delivery_fee
            else:
                profit -= delivery_fee
        party_data[party_id]["profit"] += profit
        party_data[party_id]["revenue"] += revenue
        party_data[party_id]["invoices"].add(inv_id)

    return [
        {
            "party_id": pid,
            "party_name": v["name"],
            "total_profit": float(v["profit"]),
            "total_revenue": float(v["revenue"]),
            "invoice_count": len(v["invoices"]),
        }
        for pid, v in party_data.items()
    ]



def inventory_report(db: Session, tenant_id: int) -> InventoryReportOut:
    products = db.execute(select(Product).where(Product.tenant_id == tenant_id)).scalars().all()
    items: List[InventoryProductOut] = []
    total_value = Decimal("0")
    for product in products:
        batches = db.execute(
            select(StockBatch).where(
                StockBatch.product_id == product.id,
                StockBatch.tenant_id == tenant_id,
            )
        ).scalars().all()
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


def party_statement(db: Session, party_id: int, tenant_id: int) -> StatementOut:
    party = db.execute(
        select(Party).where(Party.id == party_id, Party.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not party:
        return StatementOut(party_id=party_id, transactions=[], total_balance=Decimal("0"))

    invoices = db.execute(
        select(Invoice).where(Invoice.party_id == party_id, Invoice.tenant_id == tenant_id)
    ).scalars().all()

    payments = db.execute(
        select(Payment).where(Payment.party_id == party_id)
    ).scalars().all()

    transactions = []

    for inv in invoices:
        transactions.append({
            "date": inv.created_at,
            "type": "INVOICE",
            "reference": f"Invoice #{inv.id}",
            "amount": inv.total_amount,
            "balance_effect": inv.total_amount if inv.invoice_type in (InvoiceType.SALE, InvoiceType.PURCHASE) else -inv.total_amount,
        })

    for pay in payments:
        transactions.append({
            "date": pay.payment_date,
            "type": "PAYMENT",
            "reference": "Payment" + (f" for Invoice #{pay.invoice_id}" if pay.invoice_id else ""),
            "amount": pay.amount,
            "balance_effect": -pay.amount,
        })

    transactions.sort(key=lambda x: x["date"])

    ledger = []
    running_balance = Decimal("0")
    for t in transactions:
        running_balance += t["balance_effect"]
        ledger.append(LedgerTransaction(
            date=t["date"].strftime("%Y-%m-%d %H:%M"),
            type=t["type"],
            reference=t["reference"],
            amount=t["amount"],
            balance=running_balance
        ))

    return StatementOut(party_id=party_id, transactions=ledger, total_balance=running_balance)


def dashboard_analytics(db: Session, tenant_id: int) -> DashboardAnalyticsOut:
    profit_data = profit_report(db, tenant_id)
    inventory_data = inventory_report(db, tenant_id)
    
    invoices = db.execute(select(Invoice).where(Invoice.tenant_id == tenant_id)).scalars().all()
    outstanding_balances = Decimal("0")
    for invoice in invoices:
        paid_total = db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.invoice_id == invoice.id)
        ).scalar_one()
        outstanding_balances += (invoice.total_amount - paid_total)
        
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    monthly_sales_dict = {m: {"sales": Decimal("0"), "purchases": Decimal("0")} for m in months}
    
    sales_invoices = db.execute(
        select(Invoice).where(Invoice.invoice_type == InvoiceType.SALE, Invoice.tenant_id == tenant_id)
    ).scalars().all()
    for inv in sales_invoices:
        m_name = inv.created_at.strftime("%b")
        if m_name in monthly_sales_dict:
            monthly_sales_dict[m_name]["sales"] += inv.total_amount
            
    purchase_invoices = db.execute(
        select(Invoice).where(Invoice.invoice_type == InvoiceType.PURCHASE, Invoice.tenant_id == tenant_id)
    ).scalars().all()
    for inv in purchase_invoices:
        m_name = inv.created_at.strftime("%b")
        if m_name in monthly_sales_dict:
            monthly_sales_dict[m_name]["purchases"] += inv.total_amount
            
    monthly_sales = [MonthlySales(name=k, sales=v["sales"], purchases=v["purchases"]) for k, v in monthly_sales_dict.items()]
    
    return DashboardAnalyticsOut(
        total_profit=profit_data.total_profit,
        stock_valuation=inventory_data.total_value,
        outstanding_balances=outstanding_balances,
        monthly_sales=monthly_sales
    )
