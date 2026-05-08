from decimal import Decimal
from typing import Dict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.domain import Invoice, InvoiceType, Party, PartyType, Payment
from app.schemas.payment import PaymentCreate


def create_payment(db: Session, data: PaymentCreate, tenant_id: int) -> Payment:
    party_id = data.party_id
    if data.invoice_id is not None:
        invoice = db.execute(
            select(Invoice).where(Invoice.id == data.invoice_id, Invoice.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if not invoice:
            raise ValueError("Invoice not found")
        if party_id is None:
            party_id = invoice.party_id
    if party_id is None:
        raise ValueError("Party not found")
    party = db.execute(
        select(Party).where(Party.id == party_id, Party.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not party:
        raise ValueError("Party not found")
    payment = Payment(party_id=party_id, invoice_id=data.invoice_id, amount=data.amount)
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def get_invoice_totals(db: Session, invoice_id: int, tenant_id: int) -> Dict[str, Decimal]:
    invoice = db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not invoice:
        return {"total": Decimal("0"), "paid": Decimal("0"), "balance": Decimal("0"), "status": "missing"}

    paid = db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.invoice_id == invoice_id)
    ).scalar_one()
    balance = invoice.total_amount - paid
    if balance <= 0:
        status = "paid"
    elif paid > 0:
        status = "partial"
    else:
        status = "unpaid"

    return {"total": invoice.total_amount, "paid": paid, "balance": balance, "status": status}


def get_party_balance(db: Session, party_id: int, tenant_id: int) -> Decimal:
    party = db.execute(
        select(Party).where(Party.id == party_id, Party.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not party:
        return Decimal("0")

    if party.party_type == PartyType.CLIENT:
        invoice_type = InvoiceType.SALE
    else:
        invoice_type = InvoiceType.PURCHASE

    invoice_total = db.execute(
        select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.party_id == party_id,
            Invoice.invoice_type == invoice_type,
            Invoice.tenant_id == tenant_id,
        )
    ).scalar_one()
    paid_total = db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.party_id == party_id)
    ).scalar_one()
    return invoice_total - paid_total


def get_party_previous_balance(db: Session, party_id: int, invoice_id: int, tenant_id: int) -> Decimal:
    party = db.execute(
        select(Party).where(Party.id == party_id, Party.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not party:
        return Decimal("0")

    if party.party_type == PartyType.CLIENT:
        invoice_type = InvoiceType.SALE
    else:
        invoice_type = InvoiceType.PURCHASE

    other_invoice_total = db.execute(
        select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.party_id == party_id,
            Invoice.invoice_type == invoice_type,
            Invoice.tenant_id == tenant_id,
            Invoice.id != invoice_id,
        )
    ).scalar_one()

    other_paid_total = db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.party_id == party_id,
            Payment.invoice_id != invoice_id,
        )
    ).scalar_one()

    result = Decimal(str(other_invoice_total)) - Decimal(str(other_paid_total))
    return max(Decimal("0"), result)
