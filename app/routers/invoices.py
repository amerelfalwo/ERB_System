from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.domain import Invoice
from app.schemas.invoice import InvoiceCreatePurchase, InvoiceCreateSale, InvoiceOut
from app.services.inventory import create_purchase_invoice, create_sale_invoice
from app.services.payments import get_invoice_totals

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.post("/purchase", response_model=InvoiceOut)
def purchase_invoice(data: InvoiceCreatePurchase, db: Session = Depends(get_db)):
    invoice = create_purchase_invoice(db, data)
    totals = get_invoice_totals(db, invoice.id)
    return InvoiceOut(
        id=invoice.id,
        party_id=invoice.party_id,
        invoice_type=invoice.invoice_type,
        total_amount=invoice.total_amount,
        created_at=invoice.created_at,
        items=invoice.items,
        paid_amount=totals["paid"],
        balance=totals["balance"],
        status=totals["status"],
    )


@router.post("/sale", response_model=InvoiceOut)
def sale_invoice(data: InvoiceCreateSale, db: Session = Depends(get_db)):
    invoice = create_sale_invoice(db, data)
    totals = get_invoice_totals(db, invoice.id)
    return InvoiceOut(
        id=invoice.id,
        party_id=invoice.party_id,
        invoice_type=invoice.invoice_type,
        total_amount=invoice.total_amount,
        created_at=invoice.created_at,
        items=invoice.items,
        paid_amount=totals["paid"],
        balance=totals["balance"],
        status=totals["status"],
    )


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    totals = get_invoice_totals(db, invoice.id)
    return InvoiceOut(
        id=invoice.id,
        party_id=invoice.party_id,
        invoice_type=invoice.invoice_type,
        total_amount=invoice.total_amount,
        created_at=invoice.created_at,
        items=invoice.items,
        paid_amount=totals["paid"],
        balance=totals["balance"],
        status=totals["status"],
    )
