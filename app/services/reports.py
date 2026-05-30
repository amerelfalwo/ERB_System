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
    RecentTransaction,
)


def profit_report(db: Session, tenant_id: int = None) -> ProfitReportOut:
    stmt = select(InvoiceItem, StockBatch, Invoice).join(
        StockBatch, StockBatch.id == InvoiceItem.batch_id
    ).join(Invoice, Invoice.id == InvoiceItem.invoice_id).where(
        Invoice.invoice_type == InvoiceType.SELL,
    )
    if tenant_id is not None:
        stmt = stmt.where(Invoice.tenant_id == tenant_id)
    rows = db.execute(stmt).all()

    items: List[ProfitItem] = []
    total_profit = Decimal("0")
    seen_invoices: set = set()
    for invoice_item, batch, invoice in rows:
        cost = invoice_item.purchase_price if invoice_item.purchase_price is not None else batch.purchase_price
        sale = invoice_item.sell_price if invoice_item.sell_price is not None else invoice_item.unit_price
        line_profit = (sale - cost) * invoice_item.quantity
        if invoice.id not in seen_invoices:
            seen_invoices.add(invoice.id)
            fee = invoice.delivery_fee or Decimal("0")
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
            Invoice.invoice_type == InvoiceType.SELL,
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
        sale = invoice_item.sell_price if invoice_item.sell_price is not None else invoice_item.unit_price
        revenue = sale * invoice_item.quantity
        profit = (sale - cost) * invoice_item.quantity
        if party_id not in party_data:
            party_data[party_id] = {"name": party_name, "profit": Decimal("0"), "revenue": Decimal("0"), "invoices": set()}
        if inv_id not in seen_invoices:
            seen_invoices.add(inv_id)
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
    from collections import defaultdict

    products = db.execute(select(Product).where(Product.tenant_id == tenant_id)).scalars().all()
    if not products:
        return InventoryReportOut(products=[], total_value=Decimal("0"))

    product_ids = [p.id for p in products]

    # Single query: fetch ALL batches for ALL products at once
    all_batches = db.execute(
        select(StockBatch).where(
            StockBatch.product_id.in_(product_ids),
            StockBatch.tenant_id == tenant_id,
        )
    ).scalars().all()

    batches_by_product = defaultdict(list)
    for b in all_batches:
        batches_by_product[b.product_id].append(b)

    items: List[InventoryProductOut] = []
    total_value = Decimal("0")
    for product in products:
        product_batches = batches_by_product[product.id]
        product_value = Decimal("0")
        batch_items = []
        for b in product_batches:
            batch_items.append(InventoryBatchOut(
                batch_id=b.id,
                purchase_price=b.purchase_price,
                selling_price=b.current_selling_price,
                remaining_quantity=b.remaining_quantity,
            ))
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
            "balance_effect": inv.total_amount if inv.invoice_type in (InvoiceType.SELL, InvoiceType.PURCHASE) else -inv.total_amount,
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
    initial_balance = Decimal(str(party.initial_balance or 0))
    running_balance = initial_balance

    # Include opening balance as the first transaction in the statement
    ledger.append(LedgerTransaction(
        date="-",
        type="INITIAL",
        reference="Opening Balance",
        amount=initial_balance,
        balance=initial_balance
    ))

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
    from sqlalchemy import extract, case, literal_column

    profit_data = profit_report(db, tenant_id)
    inventory_data = inventory_report(db, tenant_id)

    # ── Outstanding balances: 2 super fast, robust aggregate queries ──
    invoice_sums = db.execute(
        select(Invoice.invoice_type, func.coalesce(func.sum(Invoice.total_amount), 0))
        .where(Invoice.tenant_id == tenant_id, Invoice.invoice_type.in_([InvoiceType.SELL, InvoiceType.PURCHASE]))
        .group_by(Invoice.invoice_type)
    ).all()
    invoice_sums_map = {row[0]: Decimal(str(row[1])) for row in invoice_sums}

    payment_sums = db.execute(
        select(Invoice.invoice_type, func.coalesce(func.sum(Payment.amount), 0))
        .join(Payment, Payment.invoice_id == Invoice.id)
        .where(Invoice.tenant_id == tenant_id, Invoice.invoice_type.in_([InvoiceType.SELL, InvoiceType.PURCHASE]))
        .group_by(Invoice.invoice_type)
    ).all()
    payment_sums_map = {row[0]: Decimal(str(row[1])) for row in payment_sums}

    customer_receivables = invoice_sums_map.get(InvoiceType.SELL, Decimal("0")) - payment_sums_map.get(InvoiceType.SELL, Decimal("0"))
    supplier_payables = invoice_sums_map.get(InvoiceType.PURCHASE, Decimal("0")) - payment_sums_map.get(InvoiceType.PURCHASE, Decimal("0"))
    outstanding_balances = customer_receivables + supplier_payables

    # ── Monthly sales/purchases: ONE aggregation query ──
    monthly_rows = db.execute(
        select(
            extract("month", Invoice.created_at).label("month_num"),
            Invoice.invoice_type,
            func.coalesce(func.sum(Invoice.total_amount), 0).label("total"),
        )
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.invoice_type.in_([InvoiceType.SELL, InvoiceType.PURCHASE]),
        )
        .group_by(extract("month", Invoice.created_at), Invoice.invoice_type)
    ).all()

    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    monthly_sales_dict = {m: {"sales": Decimal("0"), "purchases": Decimal("0")} for m in months}
    for row in monthly_rows:
        month_idx = int(row.month_num) - 1
        if 0 <= month_idx < 12:
            m_name = months[month_idx]
            if row.invoice_type == InvoiceType.SELL:
                monthly_sales_dict[m_name]["sales"] = Decimal(str(row.total))
            else:
                monthly_sales_dict[m_name]["purchases"] = Decimal(str(row.total))

    monthly_sales = [MonthlySales(name=k, sales=v["sales"], purchases=v["purchases"]) for k, v in monthly_sales_dict.items()]

    # ── Recent transactions: ONE query + bulk payment lookup ──
    recent_invoices = db.execute(
        select(Invoice).where(Invoice.tenant_id == tenant_id).order_by(Invoice.created_at.desc()).limit(8)
    ).scalars().all()

    recent_ids = [inv.id for inv in recent_invoices]
    paid_map = {}
    if recent_ids:
        paid_rows = db.execute(
            select(Payment.invoice_id, func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.invoice_id.in_(recent_ids))
            .group_by(Payment.invoice_id)
        ).all()
        paid_map = {inv_id: amt for inv_id, amt in paid_rows}

    recent_transactions = []
    for inv in recent_invoices:
        desc = "Supplier Payables" if inv.invoice_type == InvoiceType.PURCHASE else "Customer Receivables" if inv.invoice_type == InvoiceType.SELL else str(inv.invoice_type.value)
        paid_total = paid_map.get(inv.id, Decimal("0"))
        status = "Pending" if inv.total_amount > paid_total else "Completed"
        recent_transactions.append(
            RecentTransaction(
                date=inv.created_at.strftime("%m/%d/%Y"),
                description=desc,
                value=inv.total_amount,
                status=status
            )
        )

    return DashboardAnalyticsOut(
        total_profit=profit_data.total_profit,
        stock_valuation=inventory_data.total_value,
        outstanding_balances=outstanding_balances,
        customer_receivables=customer_receivables,
        supplier_payables=supplier_payables,
        monthly_sales=monthly_sales,
        recent_transactions=recent_transactions
    )
