import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.constants import (
    ERR_INVOICE_NOT_FOUND, ERR_PARTY_NOT_FOUND, ERR_PRODUCT_NOT_FOUND,
    INVOICE_TYPE_SELL, INVOICE_TYPE_PURCHASE,
)
from app.models.domain import Invoice, User, InvoiceItem, StockBatch, Product
from sqlalchemy import select, func, and_
from app.repositories.base import (
    BatchRepository, InvoiceRepository, PartyRepository, ProductRepository, PaymentRepository
)
from app.schemas.invoice import InvoiceCreatePurchase, InvoiceCreateSell, InvoiceItemOut, InvoiceOut, PaymentOut, InvoiceListResponse
from app.services.invoice_service import (
    list_invoices_svc, create_purchase_invoice_svc, create_sell_invoice_svc,
    update_invoice_svc, delete_invoice_svc, process_return_svc,
    get_invoice_totals_svc, get_party_previous_balance_svc,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invoices", tags=["invoices"])


def _invoice_out(invoice, invoice_repo: InvoiceRepository, party_repo: PartyRepository) -> InvoiceOut:
    totals = get_invoice_totals_svc(invoice_repo, invoice)
    inv_type = INVOICE_TYPE_SELL if invoice.invoice_type == INVOICE_TYPE_SELL else INVOICE_TYPE_PURCHASE
    prev_balance = get_party_previous_balance_svc(party_repo, invoice.party_id, invoice.id, inv_type)

    # Bulk fetch already returned quantities for all invoice items in one query
    item_ids = [item.id for item in invoice.items]
    returned_qty_map = invoice_repo.get_returned_quantities_for_items(item_ids)

    # Resolve product_name for each item via batch → product relationship
    items_out = []
    for item in invoice.items:
        product_name = None
        if item.batch and item.batch.product:
            product_name = item.batch.product.name
            
        already_returned_qty = returned_qty_map.get(item.id, Decimal("0"))
        
        items_out.append(InvoiceItemOut(
            id=item.id,
            batch_id=item.batch_id,
            quantity=item.quantity,
            unit_price=item.unit_price,
            purchase_price=item.purchase_price,
            sell_price=item.sell_price,
            product_name=product_name,
            already_returned_qty=already_returned_qty,
            original_invoice_item_id=item.original_invoice_item_id,
        ))

    party = party_repo.get_by_id(invoice.party_id)
    party_name = party.name if party else None

    return InvoiceOut(
        id=invoice.id,
        party_id=invoice.party_id,
        party_name=party_name,
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


@router.get("", response_model=InvoiceListResponse)
def list_invoices(
    party_id: int = None,
    invoice_type: str = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv_repo = InvoiceRepository(db, current_user.tenant_id)
    return list_invoices_svc(inv_repo, party_id=party_id, invoice_type=invoice_type, skip=skip, limit=limit)


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


@router.post("/sell", response_model=InvoiceOut)
def sell_invoice(
    data: InvoiceCreateSell,
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

    invoice = create_sell_invoice_svc(inv_repo, batch_repo, data, current_user.tenant_id)
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


@router.patch("/{invoice_id}", response_model=InvoiceOut)
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


@router.get("/{invoice_id}/payments", response_model=list[PaymentOut])
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
            "amount": p.amount,
            "payment_date": p.payment_date.isoformat() if p.payment_date else None,
        }
        for p in invoice.payments
    ]


@router.patch("/{invoice_id}/payments/{payment_id}", response_model=PaymentOut)
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
        "amount": payment.amount,
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


@router.get("/admin/diagnose-stock")
def diagnose_stock(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Find purchase invoices that might have failed to create stock batches.
    Returns the list of invoice IDs and item details.
    """
    logger.info("Running stock diagnostic for tenant_id=%s", current_user.tenant_id)
    
    # Get all purchase invoices
    invoices = db.execute(
        select(Invoice)
        .where(Invoice.tenant_id == current_user.tenant_id)
        .where(Invoice.invoice_type == INVOICE_TYPE_PURCHASE)
    ).scalars().all()
    
    problematic = []
    for inv in invoices:
        items = db.execute(
            select(InvoiceItem)
            .where(InvoiceItem.invoice_id == inv.id)
        ).scalars().all()
        
        bad_items = []
        for item in items:
            if not item.batch_id:
                bad_items.append({"item_id": item.id, "product_id": item.product_id, "reason": "No batch_id"})
                continue
                
            batch = db.execute(
                select(StockBatch)
                .where(StockBatch.id == item.batch_id)
            ).scalar_one_or_none()
            
            if not batch:
                bad_items.append({"item_id": item.id, "product_id": item.product_id, "batch_id": item.batch_id, "reason": "Batch not found"})
                
        if bad_items:
            problematic.append({
                "invoice_id": inv.id,
                "party_id": inv.party_id,
                "date": inv.created_at.isoformat(),
                "bad_items": bad_items
            })
            
    return {"status": "ok", "problematic_invoices_count": len(problematic), "problematic_invoices": problematic}


@router.post("/admin/reconcile-stock")
def reconcile_stock(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Reconcile stock for purchase invoices that don't have associated stock batches.
    This creates the missing batches.
    """
    logger.info("Running stock reconciliation for tenant_id=%s", current_user.tenant_id)
    
    # 1. Find all InvoiceItems for purchase invoices that don't have a valid StockBatch
    # First, get all purchase invoices
    purchase_invoices = db.execute(
        select(Invoice.id)
        .where(Invoice.tenant_id == current_user.tenant_id)
        .where(Invoice.invoice_type == INVOICE_TYPE_PURCHASE)
    ).scalars().all()
    
    if not purchase_invoices:
        return {"status": "ok", "fixed_count": 0, "message": "No purchase invoices found"}
        
    # Get all items for these invoices
    items = db.execute(
        select(InvoiceItem)
        .where(InvoiceItem.invoice_id.in_(purchase_invoices))
    ).scalars().all()
    
    fixed_count = 0
    errors = []
    
    for item in items:
        # Check if batch exists
        batch_exists = False
        if item.batch_id:
            batch = db.execute(select(StockBatch).where(StockBatch.id == item.batch_id)).scalar_one_or_none()
            batch_exists = batch is not None
            
        if not batch_exists:
            try:
                # We need to recreate the batch
                invoice = db.execute(select(Invoice).where(Invoice.id == item.invoice_id)).scalar_one()
                product = db.execute(select(Product).where(Product.id == item.product_id)).scalar_one()
                
                # Use existing prices from item if available, otherwise from product
                purchase_price = item.purchase_price or item.unit_price or product.purchase_price or Decimal("0")
                sell_price = item.sell_price or product.sell_price or Decimal("0")
                
                batch = StockBatch(
                    product_id=item.product_id,
                    purchase_price=purchase_price,
                    current_selling_price=sell_price,
                    initial_quantity=item.quantity,
                    remaining_quantity=item.quantity,
                    tenant_id=current_user.tenant_id,
                    party_id=invoice.party_id,
                )
                db.add(batch)
                db.flush() # flush to get ID
                
                # Update item to point to the new batch
                item.batch_id = batch.id
                db.add(item)
                
                fixed_count += 1
                logger.info(f"Reconciled missing batch for item_id={item.id}, product_id={item.product_id}, new_batch_id={batch.id}")
            except Exception as e:
                logger.error(f"Failed to reconcile item {item.id}: {e}")
                errors.append(f"Failed to fix item {item.id}: {str(e)}")
                
    if fixed_count > 0:
        db.commit()
        
    return {
        "status": "success", 
        "fixed_items_count": fixed_count,
        "errors": errors
    }
