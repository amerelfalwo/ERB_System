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
    NetProfitReportOut,
    DashboardKpis,
    DashboardTrendPoint,
    TopProductItem,
    LowStockProductItem,
    TopPartyItem,
    UnifiedDashboardOut,
)

from app.models.domain import Expense

def net_profit_report(db: Session, tenant_id: int = None, start_date: str = None, end_date: str = None) -> NetProfitReportOut:
    from datetime import datetime

    # 1. Get gross profit using existing profit_report logic
    profit_data = profit_report(db, tenant_id, start_date, end_date)
    gross_profit = profit_data.total_profit

    # 2. Get total expenses for the same period
    dt_start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
    dt_end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59) if end_date else None

    expense_stmt = select(func.sum(Expense.amount))
    if tenant_id is not None:
        expense_stmt = expense_stmt.where(Expense.tenant_id == tenant_id)
    if dt_start:
        expense_stmt = expense_stmt.where(Expense.expense_date >= dt_start)
    if dt_end:
        expense_stmt = expense_stmt.where(Expense.expense_date <= dt_end)

    total_expenses = db.execute(expense_stmt).scalar() or Decimal("0")
    
    net_profit = gross_profit - Decimal(str(total_expenses))

    return NetProfitReportOut(
        gross_profit=gross_profit,
        total_expenses=Decimal(str(total_expenses)),
        net_profit=net_profit
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
        disc = Decimal(str(inv.discount_amount or inv.total_discount or 0))
        if inv.invoice_type == InvoiceType.SELL_RETURN:
            total_profit += disc
        else:
            total_profit -= disc

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
        cost = Decimal(str(invoice_item.purchase_price if invoice_item.purchase_price is not None else (batch.purchase_price if batch and batch.purchase_price is not None else "0")))
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
        select(Invoice.id, Invoice.invoice_type, Invoice.delivery_fee, Invoice.discount_amount, Invoice.total_discount,
               Party.id.label("party_id"), Party.name.label("party_name"))
        .join(Party, Party.id == Invoice.party_id)
        .where(
            Invoice.invoice_type.in_([InvoiceType.SELL, InvoiceType.SELL_RETURN]),
            Invoice.tenant_id == tenant_id,
            Party.tenant_id == tenant_id,
        )
    ).all()

    invoice_ids = [r.id for r in rows]
    invoice_meta = {r.id: (r.party_id, r.party_name, r.invoice_type, Decimal(str(r.delivery_fee or 0)), Decimal(str(r.discount_amount or r.total_discount or 0))) for r in rows}

    party_data: dict = {}
    
    for inv_id, (party_id, party_name, inv_type, delivery_fee, discount_amount) in invoice_meta.items():
        if party_id not in party_data:
            party_data[party_id] = {"name": party_name, "profit": Decimal("0"), "revenue": Decimal("0"), "invoices": set()}
            
        party_data[party_id]["invoices"].add(inv_id)
        if inv_type == InvoiceType.SELL_RETURN:
            party_data[party_id]["profit"] += discount_amount
            party_data[party_id]["revenue"] -= (delivery_fee - discount_amount)
        else:
            party_data[party_id]["profit"] -= discount_amount
            party_data[party_id]["revenue"] += (delivery_fee - discount_amount)

    if not invoice_ids:
        return []

    item_rows = db.execute(
        select(InvoiceItem, StockBatch, Invoice.id.label("inv_id"))
        .join(StockBatch, StockBatch.id == InvoiceItem.batch_id)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(InvoiceItem.invoice_id.in_(invoice_ids))
    ).all()

    for invoice_item, batch, inv_id in item_rows:
        party_id, party_name, inv_type, _, _ = invoice_meta[inv_id]
        cost = Decimal(str(invoice_item.purchase_price if invoice_item.purchase_price is not None else (batch.purchase_price if batch and batch.purchase_price is not None else "0")))
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


def unified_dashboard_report(db: Session, tenant_id: int, date_from: str = None, date_to: str = None) -> UnifiedDashboardOut:
    from datetime import datetime, timedelta
    from collections import defaultdict

    dt_start = datetime.strptime(date_from, "%Y-%m-%d") if date_from else None
    dt_end = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59) if date_to else None

    # 1. KPIs
    # Invoices in date range
    inv_query = select(Invoice).where(Invoice.tenant_id == tenant_id)
    if dt_start:
        inv_query = inv_query.where(Invoice.created_at >= dt_start)
    if dt_end:
        inv_query = inv_query.where(Invoice.created_at <= dt_end)

    invoices = db.execute(inv_query).scalars().all()

    total_sales = Decimal("0")
    total_purchases = Decimal("0")
    total_invoices_count = len(invoices)

    for inv in invoices:
        amt = Decimal(str(inv.total_amount or 0))
        if inv.invoice_type == InvoiceType.SELL:
            total_sales += amt
        elif inv.invoice_type == InvoiceType.SELL_RETURN:
            total_sales -= amt
        elif inv.invoice_type == InvoiceType.PURCHASE:
            total_purchases += amt
        elif inv.invoice_type == InvoiceType.PURCHASE_RETURN:
            total_purchases -= amt

    net_report = net_profit_report(db, tenant_id, date_from, date_to)
    gross_profit = net_report.gross_profit
    total_expenses = net_report.total_expenses
    net_profit = net_report.net_profit

    dash_analytics = dashboard_analytics(db, tenant_id, date_from, date_to)
    outstanding_balance = dash_analytics.customer_receivables

    kpis = DashboardKpis(
        total_sales=total_sales,
        total_purchases=total_purchases,
        gross_profit=gross_profit,
        total_expenses=total_expenses,
        net_profit=net_profit,
        total_invoices_count=total_invoices_count,
        outstanding_balance=outstanding_balance
    )

    # 2. Trend (Period grouping)
    # Determine period format: daily if <= 31 days or default, else monthly
    days_diff = (dt_end - dt_start).days if (dt_start and dt_end) else 30
    group_fmt = "%Y-%m-%d" if days_diff <= 60 else "%Y-%m"

    trend_map = defaultdict(lambda: {"sales": Decimal("0"), "purchases": Decimal("0"), "profit": Decimal("0")})
    for inv in invoices:
        period_key = inv.created_at.strftime(group_fmt)
        amt = Decimal(str(inv.total_amount or 0))
        if inv.invoice_type == InvoiceType.SELL:
            trend_map[period_key]["sales"] += amt
        elif inv.invoice_type == InvoiceType.SELL_RETURN:
            trend_map[period_key]["sales"] -= amt
        elif inv.invoice_type == InvoiceType.PURCHASE:
            trend_map[period_key]["purchases"] += amt
        elif inv.invoice_type == InvoiceType.PURCHASE_RETURN:
            trend_map[period_key]["purchases"] -= amt

    # Incorporate profit into trend map
    p_report = profit_report(db, tenant_id, date_from, date_to)
    inv_ids = {p_item.invoice_id for p_item in p_report.items if p_item.invoice_id}
    if inv_ids:
        inv_rows = db.execute(
            select(Invoice.id, Invoice.created_at).where(Invoice.id.in_(inv_ids))
        ).all()
        inv_created_at_map = {row.id: row.created_at for row in inv_rows}
        for p_item in p_report.items:
            created_at = inv_created_at_map.get(p_item.invoice_id)
            if created_at:
                period_key = created_at.strftime(group_fmt)
                trend_map[period_key]["profit"] += p_item.profit

    sorted_periods = sorted(trend_map.keys())
    trend = [
        DashboardTrendPoint(
            period=pk,
            sales=trend_map[pk]["sales"],
            purchases=trend_map[pk]["purchases"],
            profit=trend_map[pk]["profit"]
        ) for pk in sorted_periods
    ]

    # 3. Top Products
    top_prod_query = (
        select(
            Product.name.label("product_name"),
            func.coalesce(func.sum(InvoiceItem.quantity), 0).label("qty_sold"),
            func.coalesce(func.sum(InvoiceItem.quantity * func.coalesce(InvoiceItem.sell_price, InvoiceItem.unit_price)), 0).label("revenue")
        )
        .join(StockBatch, StockBatch.id == InvoiceItem.batch_id)
        .join(Product, Product.id == StockBatch.product_id)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(Invoice.tenant_id == tenant_id, Invoice.invoice_type == InvoiceType.SELL)
    )
    if dt_start:
        top_prod_query = top_prod_query.where(Invoice.created_at >= dt_start)
    if dt_end:
        top_prod_query = top_prod_query.where(Invoice.created_at <= dt_end)

    top_prod_rows = db.execute(
        top_prod_query.group_by(Product.id, Product.name)
        .order_by(func.sum(InvoiceItem.quantity * func.coalesce(InvoiceItem.sell_price, InvoiceItem.unit_price)).desc())
        .limit(5)
    ).all()

    top_products = [
        TopProductItem(
            product_name=row.product_name,
            qty_sold=Decimal(str(row.qty_sold)),
            revenue=Decimal(str(row.revenue))
        ) for row in top_prod_rows
    ]

    # 4. Low Stock Products
    batch_subq = (
        select(
            StockBatch.product_id,
            func.coalesce(func.sum(StockBatch.remaining_quantity), 0).label("remaining_qty")
        )
        .where(StockBatch.tenant_id == tenant_id)
        .group_by(StockBatch.product_id)
        .subquery()
    )

    low_stock_query = (
        select(
            Product.name.label("product_name"),
            func.coalesce(batch_subq.c.remaining_qty, 0).label("remaining_qty"),
            func.coalesce(Product.min_stock, 5).label("min_stock")
        )
        .outerjoin(batch_subq, batch_subq.c.product_id == Product.id)
        .where(Product.tenant_id == tenant_id)
        .where(func.coalesce(batch_subq.c.remaining_qty, 0) <= func.coalesce(Product.min_stock, 5))
        .limit(5)
    )

    low_stock_rows = db.execute(low_stock_query).all()
    low_stock_products = [
        LowStockProductItem(
            product_name=row.product_name,
            remaining_qty=Decimal(str(row.remaining_qty)),
            min_stock=Decimal(str(row.min_stock))
        ) for row in low_stock_rows
    ]

    # 5. Top Parties
    top_party_query = (
        select(
            Party.name.label("party_name"),
            Party.party_type.label("party_type"),
            func.coalesce(func.sum(Invoice.total_amount), 0).label("total_amount")
        )
        .join(Party, Party.id == Invoice.party_id)
        .where(Invoice.tenant_id == tenant_id)
    )
    if dt_start:
        top_party_query = top_party_query.where(Invoice.created_at >= dt_start)
    if dt_end:
        top_party_query = top_party_query.where(Invoice.created_at <= dt_end)

    top_party_rows = db.execute(
        top_party_query.group_by(Party.id, Party.name, Party.party_type)
        .order_by(func.sum(Invoice.total_amount).desc())
        .limit(5)
    ).all()

    top_parties = [
        TopPartyItem(
            party_name=row.party_name,
            type=str(row.party_type.value if hasattr(row.party_type, "value") else row.party_type).upper(),
            total_amount=Decimal(str(row.total_amount))
        ) for row in top_party_rows
    ]

    return UnifiedDashboardOut(
        kpis=kpis,
        trend=trend,
        top_products=top_products,
        low_stock_products=low_stock_products,
        top_parties=top_parties
    )

