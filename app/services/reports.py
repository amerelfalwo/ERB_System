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


def profit_report(db: Session, tenant_id: int = None, start_date: str = None, end_date: str = None) -> ProfitReportOut:
    from datetime import datetime
    
    dt_start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
    dt_end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59) if end_date else None

    # 1. Fetch all invoices to account for delivery fees correctly
    inv_stmt = select(Invoice).where(Invoice.invoice_type.in_([InvoiceType.SELL, InvoiceType.SELL_RETURN]))
    if tenant_id is not None:
        inv_stmt = inv_stmt.where(Invoice.tenant_id == tenant_id)
    if dt_start:
        inv_stmt = inv_stmt.where(Invoice.created_at >= dt_start)
    if dt_end:
        inv_stmt = inv_stmt.where(Invoice.created_at <= dt_end)

    invoices = db.execute(inv_stmt).scalars().all()
    
    total_profit = Decimal("0")
    for inv in invoices:
        fee = Decimal(str(inv.delivery_fee or 0))
        if inv.invoice_type == InvoiceType.SELL_RETURN:
            total_profit -= fee
        else:
            total_profit += fee

    # 2. Fetch items for COGS and revenue logic
    stmt = select(InvoiceItem, StockBatch, Invoice).join(
        StockBatch, StockBatch.id == InvoiceItem.batch_id
    ).join(Invoice, Invoice.id == InvoiceItem.invoice_id).where(
        Invoice.invoice_type.in_([InvoiceType.SELL, InvoiceType.SELL_RETURN]),
    )
    if tenant_id is not None:
        stmt = stmt.where(Invoice.tenant_id == tenant_id)
    if dt_start:
        stmt = stmt.where(Invoice.created_at >= dt_start)
    if dt_end:
        stmt = stmt.where(Invoice.created_at <= dt_end)
    rows = db.execute(stmt).all()

    items: List[ProfitItem] = []
    for invoice_item, batch, invoice in rows:
        cost = Decimal(str(invoice_item.purchase_price if invoice_item.purchase_price is not None else batch.purchase_price))
        sale = Decimal(str(invoice_item.sell_price if invoice_item.sell_price is not None else invoice_item.unit_price))
        qty_val = Decimal(str(invoice_item.quantity))
        
        if invoice.invoice_type == InvoiceType.SELL_RETURN:
            line_profit = -(sale - cost) * qty_val
            qty = -qty_val
        else:
            line_profit = (sale - cost) * qty_val
            qty = qty_val
                
        total_profit += line_profit
        items.append(
            ProfitItem(
                invoice_id=invoice.id,
                batch_id=batch.id,
                quantity=qty,
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
            Invoice.invoice_type.in_([InvoiceType.SELL, InvoiceType.SELL_RETURN]),
            Invoice.tenant_id == tenant_id,
            Party.tenant_id == tenant_id,
        )
    ).all()

    invoice_ids = [r.id for r in rows]
    invoice_meta = {r.id: (r.party_id, r.party_name, r.invoice_type, Decimal(str(r.delivery_fee or 0))) for r in rows}

    party_data: dict = {}
    
    for inv_id, (party_id, party_name, inv_type, delivery_fee) in invoice_meta.items():
        if party_id not in party_data:
            party_data[party_id] = {"name": party_name, "profit": Decimal("0"), "revenue": Decimal("0"), "invoices": set()}
            
        party_data[party_id]["invoices"].add(inv_id)
        if inv_type == InvoiceType.SELL_RETURN:
            party_data[party_id]["profit"] -= delivery_fee
            party_data[party_id]["revenue"] -= delivery_fee
        else:
            party_data[party_id]["profit"] += delivery_fee
            party_data[party_id]["revenue"] += delivery_fee

    if not invoice_ids:
        return []

    item_rows = db.execute(
        select(InvoiceItem, StockBatch, Invoice.id.label("inv_id"))
        .join(StockBatch, StockBatch.id == InvoiceItem.batch_id)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(InvoiceItem.invoice_id.in_(invoice_ids))
    ).all()

    for invoice_item, batch, inv_id in item_rows:
        party_id, party_name, inv_type, _ = invoice_meta[inv_id]
        cost = Decimal(str(invoice_item.purchase_price if invoice_item.purchase_price is not None else batch.purchase_price))
        sale = Decimal(str(invoice_item.sell_price if invoice_item.sell_price is not None else invoice_item.unit_price))
        qty = Decimal(str(invoice_item.quantity))
        
        if inv_type == InvoiceType.SELL_RETURN:
            revenue = -(sale * qty)
            profit = -((sale - cost) * qty)
        else:
            revenue = sale * qty
            profit = (sale - cost) * qty
            
        party_data[party_id]["profit"] += profit
        party_data[party_id]["revenue"] += revenue

    return [
        {
            "party_id": pid,
            "party_name": v["name"],
            "total_profit": v["profit"],
            "total_revenue": v["revenue"],
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
            purchase_price = Decimal(str(b.purchase_price or 0))
            rem_qty = Decimal(str(b.remaining_quantity or 0))
            selling_price = Decimal(str(b.current_selling_price or 0))
            
            batch_items.append(InventoryBatchOut(
                batch_id=b.id,
                purchase_price=purchase_price,
                selling_price=selling_price,
                remaining_quantity=rem_qty,
            ))
            product_value += purchase_price * rem_qty
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
        is_return = inv.invoice_type in (InvoiceType.SELL_RETURN, InvoiceType.PURCHASE_RETURN)
        total_amt = Decimal(str(inv.total_amount))
        balance_effect = total_amt if inv.invoice_type in (InvoiceType.SELL, InvoiceType.PURCHASE) else -total_amt
        
        transactions.append({
            "date": inv.created_at,
            "type": "RETURN" if is_return else "INVOICE",
            "reference": f"Return #{inv.id}" if is_return else f"Invoice #{inv.id}",
            "amount": total_amt,
            "balance_effect": balance_effect,
        })

    for pay in payments:
        pay_amt = Decimal(str(pay.amount))
        transactions.append({
            "date": pay.payment_date,
            "type": "PAYMENT",
            "reference": "Payment" + (f" for Invoice #{pay.invoice_id}" if pay.invoice_id else ""),
            "amount": pay_amt,
            "balance_effect": -pay_amt,
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



def dashboard_analytics(db: Session, tenant_id: int, start_date: str = None, end_date: str = None) -> DashboardAnalyticsOut:
    from sqlalchemy import extract, case, literal_column
    from app.models.domain import Party, PartyType
    from datetime import datetime

    dt_start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
    dt_end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59) if end_date else None

    profit_data = profit_report(db, tenant_id, start_date, end_date)
    inventory_data = inventory_report(db, tenant_id)

    # ── Outstanding balances: calculate via PartyType and Invoice totals + Payments ──
    inv_sum_stmt = select(Party.party_type, Invoice.invoice_type, func.coalesce(func.sum(Invoice.total_amount), 0)).join(Party, Party.id == Invoice.party_id).where(Invoice.tenant_id == tenant_id)
    pay_sum_stmt = select(Party.party_type, func.coalesce(func.sum(Payment.amount), 0)).join(Party, Party.id == Payment.party_id).where(Party.tenant_id == tenant_id)
    
    if dt_start:
        inv_sum_stmt = inv_sum_stmt.where(Invoice.created_at >= dt_start)
        pay_sum_stmt = pay_sum_stmt.where(Payment.payment_date >= dt_start.date())
    if dt_end:
        inv_sum_stmt = inv_sum_stmt.where(Invoice.created_at <= dt_end)
        pay_sum_stmt = pay_sum_stmt.where(Payment.payment_date <= dt_end.date())
        
    invoice_sums = db.execute(inv_sum_stmt.group_by(Party.party_type, Invoice.invoice_type)).all()
    payment_sums = db.execute(pay_sum_stmt.group_by(Party.party_type)).all()
    
    initial_balances = db.execute(
        select(Party.party_type, func.coalesce(func.sum(Party.initial_balance), 0))
        .where(Party.tenant_id == tenant_id)
        .group_by(Party.party_type)
    ).all()
    
    init_bal_map = {row[0]: Decimal(str(row[1])) for row in initial_balances}
    inv_map = {(pt, it): Decimal(str(amt)) for pt, it, amt in invoice_sums}
    pay_map = {row[0]: Decimal(str(row[1])) for row in payment_sums}
    
    # Receivables (Clients): initial_balance + SELL - SELL_RETURN - PAYMENTS
    customer_receivables = (
        init_bal_map.get(PartyType.CLIENT, Decimal("0"))
        + inv_map.get((PartyType.CLIENT, InvoiceType.SELL), Decimal("0"))
        - inv_map.get((PartyType.CLIENT, InvoiceType.SELL_RETURN), Decimal("0"))
        - pay_map.get(PartyType.CLIENT, Decimal("0"))
    )
    
    # Payables (Suppliers): initial_balance + PURCHASE - PURCHASE_RETURN - PAYMENTS
    supplier_payables = (
        init_bal_map.get(PartyType.SUPPLIER, Decimal("0"))
        + inv_map.get((PartyType.SUPPLIER, InvoiceType.PURCHASE), Decimal("0"))
        - inv_map.get((PartyType.SUPPLIER, InvoiceType.PURCHASE_RETURN), Decimal("0"))
        - pay_map.get(PartyType.SUPPLIER, Decimal("0"))
    )
    
    outstanding_balances = customer_receivables + supplier_payables

    # ── Monthly sales/purchases: ONE aggregation query ──
    monthly_stmt = select(
        extract("month", Invoice.created_at).label("month_num"),
        Invoice.invoice_type,
        func.coalesce(func.sum(Invoice.total_amount), 0).label("total"),
    ).where(Invoice.tenant_id == tenant_id)
    
    if dt_start:
        monthly_stmt = monthly_stmt.where(Invoice.created_at >= dt_start)
    if dt_end:
        monthly_stmt = monthly_stmt.where(Invoice.created_at <= dt_end)
        
    monthly_rows = db.execute(monthly_stmt.group_by(extract("month", Invoice.created_at), Invoice.invoice_type)).all()

    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    monthly_sales_dict = {m: {"sales": Decimal("0"), "purchases": Decimal("0")} for m in months}
    for row in monthly_rows:
        month_idx = int(row.month_num) - 1
        if 0 <= month_idx < 12:
            m_name = months[month_idx]
            val = Decimal(str(row.total))
            if row.invoice_type == InvoiceType.SELL:
                monthly_sales_dict[m_name]["sales"] += val
            elif row.invoice_type == InvoiceType.SELL_RETURN:
                monthly_sales_dict[m_name]["sales"] -= val
            elif row.invoice_type == InvoiceType.PURCHASE:
                monthly_sales_dict[m_name]["purchases"] += val
            elif row.invoice_type == InvoiceType.PURCHASE_RETURN:
                monthly_sales_dict[m_name]["purchases"] -= val

    monthly_sales = [MonthlySales(name=k, sales=v["sales"], purchases=v["purchases"]) for k, v in monthly_sales_dict.items()]

    # ── Recent transactions: ONE query + bulk payment lookup ──
    recent_stmt = select(Invoice).where(Invoice.tenant_id == tenant_id)
    if dt_start:
        recent_stmt = recent_stmt.where(Invoice.created_at >= dt_start)
    if dt_end:
        recent_stmt = recent_stmt.where(Invoice.created_at <= dt_end)
        
    recent_invoices = db.execute(recent_stmt.order_by(Invoice.created_at.desc()).limit(8)).scalars().all()

    recent_ids = [inv.id for inv in recent_invoices]
    paid_map = {}
    if recent_ids:
        paid_rows = db.execute(
            select(Payment.invoice_id, func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.invoice_id.in_(recent_ids))
            .group_by(Payment.invoice_id)
        ).all()
        paid_map = {inv_id: Decimal(str(amt)) for inv_id, amt in paid_rows}

    recent_transactions = []
    for inv in recent_invoices:
        desc = str(inv.invoice_type.value)
        if inv.invoice_type == InvoiceType.PURCHASE:
            desc = "Supplier Payables"
        elif inv.invoice_type == InvoiceType.SELL:
            desc = "Customer Receivables"
        elif inv.invoice_type == InvoiceType.SELL_RETURN:
            desc = "Customer Return"
        elif inv.invoice_type == InvoiceType.PURCHASE_RETURN:
            desc = "Supplier Return"
            
        inv_total = Decimal(str(inv.total_amount))
        paid_total = paid_map.get(inv.id, Decimal("0"))
        status = "Pending" if inv_total > paid_total else "Completed"
        recent_transactions.append(
            RecentTransaction(
                date=inv.created_at.strftime("%m/%d/%Y"),
                description=desc,
                value=inv_total,
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

