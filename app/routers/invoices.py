from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.constants import (
    ERR_INVOICE_NOT_FOUND, ERR_PARTY_NOT_FOUND, ERR_PRODUCT_NOT_FOUND,
    INVOICE_TYPE_SALE, INVOICE_TYPE_PURCHASE,
)
from app.models.domain import User
from app.repositories.base import (
    BatchRepository, InvoiceRepository, PartyRepository, ProductRepository, PaymentRepository
)
from app.schemas.invoice import InvoiceCreatePurchase, InvoiceCreateSale, InvoiceItemOut, InvoiceOut
from app.services.invoice_service import (
    list_invoices_svc, create_purchase_invoice_svc, create_sale_invoice_svc,
    update_invoice_svc, delete_invoice_svc, process_return_svc,
    get_invoice_totals_svc, get_party_previous_balance_svc,
)

router = APIRouter(prefix="/invoices", tags=["invoices"])


def _invoice_out(invoice, invoice_repo: InvoiceRepository, party_repo: PartyRepository) -> InvoiceOut:
    totals = get_invoice_totals_svc(invoice_repo, invoice)
    inv_type = INVOICE_TYPE_SALE if invoice.invoice_type == INVOICE_TYPE_SALE else INVOICE_TYPE_PURCHASE
    prev_balance = get_party_previous_balance_svc(party_repo, invoice.party_id, invoice.id, inv_type)

    # Resolve product_name for each item via batch → product relationship
    items_out = []
    for item in invoice.items:
        product_name = None
        if item.batch and item.batch.product:
            product_name = item.batch.product.name
        items_out.append(InvoiceItemOut(
            id=item.id,
            batch_id=item.batch_id,
            quantity=item.quantity,
            unit_price=item.unit_price,
            purchase_price=item.purchase_price,
            sale_price=item.sale_price,
            product_name=product_name,
        ))

    return InvoiceOut(
        id=invoice.id,
        party_id=invoice.party_id,
        invoice_type=invoice.invoice_type,
        total_amount=invoice.total_amount,
        delivery_fee=invoice.delivery_fee or Decimal("0"),
        footer_custom_text=invoice.footer_custom_text,
        created_at=invoice.created_at,
        items=items_out,
        paid_amount=totals["paid"],
        balance=totals["balance"],
        status=totals["status"],
        previous_balance=prev_balance,
        total_balance_after=prev_balance + totals["balance"],
    )


@router.get("")
def list_invoices(
    party_id: int = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv_repo = InvoiceRepository(db, current_user.tenant_id)
    return list_invoices_svc(inv_repo, party_id=party_id, skip=skip, limit=limit)


@router.post("/purchase", response_model=InvoiceOut)
def purchase_invoice(
    data: InvoiceCreatePurchase,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv_repo = InvoiceRepository(db, current_user.tenant_id)
    batch_repo = BatchRepository(db, current_user.tenant_id)
    party_repo = PartyRepository(db, current_user.tenant_id)
    prod_repo = ProductRepository(db, current_user.tenant_id)

    if not party_repo.get_by_id(data.party_id):
        raise HTTPException(status_code=404, detail=ERR_PARTY_NOT_FOUND)

    product_ids = [i.product_id for i in data.items]
    if product_ids and prod_repo.count_by_ids(product_ids) != len(set(product_ids)):
        raise HTTPException(status_code=404, detail=ERR_PRODUCT_NOT_FOUND)

    invoice = create_purchase_invoice_svc(db, inv_repo, batch_repo, data, current_user.tenant_id)
    return _invoice_out(invoice, inv_repo, party_repo)


@router.post("/sale", response_model=InvoiceOut)
def sale_invoice(
    data: InvoiceCreateSale,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv_repo = InvoiceRepository(db, current_user.tenant_id)
    batch_repo = BatchRepository(db, current_user.tenant_id)
    party_repo = PartyRepository(db, current_user.tenant_id)
    prod_repo = ProductRepository(db, current_user.tenant_id)

    if not party_repo.get_by_id(data.party_id):
        raise HTTPException(status_code=404, detail=ERR_PARTY_NOT_FOUND)

    product_ids = [i.product_id for i in data.items]
    if product_ids and prod_repo.count_by_ids(product_ids) != len(set(product_ids)):
        raise HTTPException(status_code=404, detail=ERR_PRODUCT_NOT_FOUND)

    invoice = create_sale_invoice_svc(inv_repo, batch_repo, data, current_user.tenant_id)
    return _invoice_out(invoice, inv_repo, party_repo)


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv_repo = InvoiceRepository(db, current_user.tenant_id)
    party_repo = PartyRepository(db, current_user.tenant_id)
    invoice = inv_repo.get_by_id(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail=ERR_INVOICE_NOT_FOUND)
    return _invoice_out(invoice, inv_repo, party_repo)


@router.patch("/{invoice_id}")
def update_invoice(
    invoice_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv_repo = InvoiceRepository(db, current_user.tenant_id)
    batch_repo = BatchRepository(db, current_user.tenant_id)
    invoice = inv_repo.get_by_id(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail=ERR_INVOICE_NOT_FOUND)
    return update_invoice_svc(db, inv_repo, batch_repo, invoice, data, current_user.tenant_id)


@router.delete("/{invoice_id}", status_code=204)
def delete_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv_repo = InvoiceRepository(db, current_user.tenant_id)
    batch_repo = BatchRepository(db, current_user.tenant_id)
    invoice = inv_repo.get_by_id(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail=ERR_INVOICE_NOT_FOUND)
    delete_invoice_svc(inv_repo, batch_repo, invoice)


@router.get("/{invoice_id}/payments")
def list_invoice_payments(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv_repo = InvoiceRepository(db, current_user.tenant_id)
    invoice = inv_repo.get_by_id(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail=ERR_INVOICE_NOT_FOUND)
    return [
        {
            "id": p.id,
            "amount": float(p.amount),
            "payment_date": p.payment_date.isoformat() if p.payment_date else None,
        }
        for p in invoice.payments
    ]


@router.patch("/{invoice_id}/payments/{payment_id}")
def update_payment(
    invoice_id: int,
    payment_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv_repo = InvoiceRepository(db, current_user.tenant_id)
    pay_repo = PaymentRepository(db, current_user.tenant_id)
    invoice = inv_repo.get_by_id(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail=ERR_INVOICE_NOT_FOUND)
    payment = pay_repo.get_for_invoice(invoice_id, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if "amount" in data:
        new_amount = Decimal(str(data["amount"]))
        # Sum of all OTHER payments on this invoice
        other_paid = inv_repo.get_paid_amount(invoice_id) - payment.amount
        max_allowed = invoice.total_amount - other_paid
        if new_amount > max_allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot set payment to {new_amount}. Max allowed is {max_allowed} (invoice total {invoice.total_amount})."
            )
        payment.amount = new_amount
    pay_repo.commit()
    pay_repo.refresh(payment)
    return {
        "id": payment.id,
        "amount": float(payment.amount),
        "payment_date": payment.payment_date.isoformat() if payment.payment_date else None,
    }


@router.delete("/{invoice_id}/payments/{payment_id}", status_code=204)
def delete_payment(
    invoice_id: int,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv_repo = InvoiceRepository(db, current_user.tenant_id)
    pay_repo = PaymentRepository(db, current_user.tenant_id)
    if not inv_repo.get_by_id(invoice_id):
        raise HTTPException(status_code=404, detail=ERR_INVOICE_NOT_FOUND)
    payment = pay_repo.get_for_invoice(invoice_id, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    pay_repo.delete(payment)
    pay_repo.commit()


@router.post("/{invoice_id}/return", response_model=InvoiceOut)
def process_return(
    invoice_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv_repo = InvoiceRepository(db, current_user.tenant_id)
    batch_repo = BatchRepository(db, current_user.tenant_id)
    party_repo = PartyRepository(db, current_user.tenant_id)

    orig_invoice = inv_repo.get_by_id(invoice_id)
    if not orig_invoice:
        raise HTTPException(status_code=404, detail=ERR_INVOICE_NOT_FOUND)

    return_invoice = process_return_svc(inv_repo, batch_repo, orig_invoice, data, current_user.tenant_id)
    return _invoice_out(return_invoice, inv_repo, party_repo)
