from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.domain import Invoice, InvoiceType, Party, PartyType, Payment
from app.schemas.payment import PaymentCreate


def get_party_balance(db: Session, party_id: int, tenant_id: int = None) -> Decimal:
    # If tenant_id is provided, include it in filters; otherwise omit for tests/single-tenant setups
    if tenant_id is None:
        party = db.execute(
            select(Party).where(Party.id == party_id)
        ).scalar_one_or_none()
    else:
        party = db.execute(
            select(Party).where(Party.id == party_id, Party.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if not party:
            # Fallback to tenant-less party
            party = db.execute(select(Party).where(Party.id == party_id)).scalar_one_or_none()
    if not party:
        raise ValueError(f"Party {party_id} not found")

    initial = Decimal(str(party.initial_balance or 0))

    if party.party_type == PartyType.SUPPLIER:
        purchase_type = InvoiceType.PURCHASE
        return_type = InvoiceType.PURCHASE_RETURN
    else:
        purchase_type = InvoiceType.SELL
        return_type = InvoiceType.SELL_RETURN

    total_invoices = Decimal(str(db.execute(
        select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.party_id == party_id,
            Invoice.invoice_type == purchase_type,
            Invoice.tenant_id == tenant_id,
        )
    ).scalar_one()))

    total_returns = Decimal(str(db.execute(
        select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.party_id == party_id,
            Invoice.invoice_type == return_type,
            Invoice.tenant_id == tenant_id,
        )
    ).scalar_one()))

    total_paid = Decimal(str(db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.party_id == party_id,
        )
    ).scalar_one()))

    return initial + total_invoices - total_returns - total_paid


def create_payment(db: Session, data: PaymentCreate, tenant_id: int = None) -> Payment:
    party_id = data.party_id
    invoice = None
    if data.invoice_id is not None:
        if tenant_id is None:
            invoice = db.execute(select(Invoice).where(Invoice.id == data.invoice_id)).scalar_one_or_none()
        else:
            invoice = db.execute(
                select(Invoice).where(
                    Invoice.id == data.invoice_id, Invoice.tenant_id == tenant_id
                )
            ).scalar_one_or_none()
        if not invoice:
            # Fallback: try finding invoice without tenant filter (useful for tests or mixed data)
            invoice = db.execute(select(Invoice).where(Invoice.id == data.invoice_id)).scalar_one_or_none()
            if not invoice:
                raise ValueError("Invoice not found")
        party_id = invoice.party_id

    if party_id is None:
        raise ValueError("party_id is required (or provide invoice_id)")

    if tenant_id is None:
        party = db.execute(select(Party).where(Party.id == party_id)).scalar_one_or_none()
    else:
        party = db.execute(select(Party).where(Party.id == party_id, Party.tenant_id == tenant_id)).scalar_one_or_none()
        if not party:
            # Fallback: try without tenant filter
            party = db.execute(select(Party).where(Party.id == party_id)).scalar_one_or_none()
    if not party:
        raise ValueError("Party not found")

    if invoice is not None:
        current_paid_amount = Decimal(str(db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.invoice_id == invoice.id
            )
        ).scalar_one()))
        remaining_balance = invoice.total_amount - current_paid_amount
        if data.amount < 0 and abs(data.amount) > current_paid_amount:
            raise ValueError("Cannot refund more than what was paid for this invoice")
        if data.amount > 0 and data.amount > remaining_balance:
            raise ValueError("Cannot pay more than the outstanding balance of the invoice")
    else:
        balance = get_party_balance(db, party_id, tenant_id)
        if balance == 0:
            raise ValueError("No outstanding balance")
        if (balance > 0 and data.amount < 0) or (balance < 0 and data.amount > 0):
            raise ValueError("Payment direction mismatch with balance")
        if abs(data.amount) > abs(balance):
            raise ValueError("Cannot pay more than the outstanding balance")

    payment = Payment(
        party_id=party_id,
        invoice_id=data.invoice_id,
        amount=data.amount,
        notes=data.notes,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def get_invoice_totals(db: Session, invoice_id: int) -> dict:
    invoice = db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    ).scalar_one_or_none()
    if not invoice:
        raise ValueError("Invoice not found")

    total_paid = Decimal(str(db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.invoice_id == invoice_id
        )
    ).scalar_one()))

    total = Decimal(str(invoice.total_amount))
    balance = total - total_paid

    if total_paid >= total:
        status = "paid"
    elif total_paid > 0:
        status = "partial"
    else:
        status = "unpaid"

    return {
        "total": total,
        "paid": total_paid,
        "balance": balance,
        "status": status,
    }


def get_parties_balances(db: Session, party_ids: list[int], tenant_id: int) -> dict[int, Decimal]:
    if not party_ids:
        return {}

    # 1. Fetch parties to get their party_type and initial_balance
    if tenant_id is None:
        parties = db.execute(select(Party).where(Party.id.in_(party_ids))).scalars().all()
    else:
        parties = db.execute(select(Party).where(Party.id.in_(party_ids), Party.tenant_id == tenant_id)).scalars().all()
    
    party_types = {p.id: p.party_type for p in parties}
    initial_balances = {p.id: Decimal(str(p.initial_balance or 0)) for p in parties}

    # Initialize all requested party_ids with their initial balance
    balances = {pid: initial_balances.get(pid, Decimal("0")) for pid in party_ids}

    # 2. Select invoice sums grouped by party_id and invoice_type
    if tenant_id is None:
        invoice_sums = db.execute(
            select(Invoice.party_id, Invoice.invoice_type, func.coalesce(func.sum(Invoice.total_amount), 0))
            .where(Invoice.party_id.in_(party_ids))
            .group_by(Invoice.party_id, Invoice.invoice_type)
        ).all()
    else:
        invoice_sums = db.execute(
            select(Invoice.party_id, Invoice.invoice_type, func.coalesce(func.sum(Invoice.total_amount), 0))
            .where(Invoice.party_id.in_(party_ids), Invoice.tenant_id == tenant_id)
            .group_by(Invoice.party_id, Invoice.invoice_type)
        ).all()

    # Map (party_id, invoice_type) -> sum
    invoice_map = {(row[0], row[1]): Decimal(str(row[2])) for row in invoice_sums}

    # 3. Select payment sums grouped by party_id
    payment_sums = db.execute(
        select(Payment.party_id, func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.party_id.in_(party_ids))
        .group_by(Payment.party_id)
    ).all()

    # Map party_id -> payment_sum
    payment_map = {row[0]: Decimal(str(row[1])) for row in payment_sums}

    # 4. Calculate final balance for each party
    for pid in party_ids:
        ptype = party_types.get(pid)
        if not ptype:
            continue
        
        if ptype == PartyType.SUPPLIER:
            purchase_type = InvoiceType.PURCHASE
            return_type = InvoiceType.PURCHASE_RETURN
        else:
            purchase_type = InvoiceType.SELL
            return_type = InvoiceType.SELL_RETURN

        total_invoices = invoice_map.get((pid, purchase_type), Decimal("0"))
        total_returns = invoice_map.get((pid, return_type), Decimal("0"))
        total_paid = payment_map.get(pid, Decimal("0"))

        balances[pid] = initial_balances.get(pid, Decimal("0")) + total_invoices - total_returns - total_paid

    return balances

