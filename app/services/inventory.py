from decimal import Decimal
from typing import List, Tuple

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Invoice, InvoiceItem, InvoiceType, Product, StockBatch
from app.schemas.invoice import InvoiceCreatePurchase, InvoiceCreateSale


def create_purchase_invoice(db: Session, data: InvoiceCreatePurchase) -> Invoice:
    try:
        invoice = Invoice(party_id=data.party_id, invoice_type=InvoiceType.PURCHASE, total_amount=Decimal("0"))
        db.add(invoice)
        db.flush()

        total = Decimal("0")
        for item in data.items:
            batch = StockBatch(
                product_id=item.product_id,
                purchase_price=item.purchase_price,
                current_selling_price=item.selling_price,
                initial_quantity=item.quantity,
                remaining_quantity=item.quantity,
            )
            db.add(batch)
            db.flush()

            invoice_item = InvoiceItem(
                invoice_id=invoice.id,
                batch_id=batch.id,
                quantity=item.quantity,
                unit_price=item.purchase_price,
            )
            db.add(invoice_item)
            total += item.purchase_price * item.quantity

        invoice.total_amount = total
        db.commit()
        db.refresh(invoice)
        return invoice
    except Exception:
        db.rollback()
        raise


def allocate_batches(db: Session, product_id: int, quantity: Decimal) -> List[Tuple[StockBatch, Decimal]]:
    stmt = select(StockBatch).where(
        StockBatch.product_id == product_id,
        StockBatch.remaining_quantity > 0,
    ).order_by(StockBatch.created_at.asc(), StockBatch.id.asc())
    batches = db.execute(stmt).scalars().all()

    remaining = quantity
    allocations: List[Tuple[StockBatch, Decimal]] = []
    for batch in batches:
        if remaining <= 0:
            break
        take = batch.remaining_quantity if batch.remaining_quantity <= remaining else remaining
        allocations.append((batch, take))
        remaining -= take

    if remaining > 0:
        raise HTTPException(status_code=400, detail="Insufficient stock")

    return allocations


def create_sale_invoice(db: Session, data: InvoiceCreateSale) -> Invoice:
    try:
        invoice = Invoice(party_id=data.party_id, invoice_type=InvoiceType.SALE, total_amount=Decimal("0"))
        db.add(invoice)
        db.flush()

        total = Decimal("0")
        for item in data.items:
            allocations = allocate_batches(db, item.product_id, item.quantity)
            for batch, qty in allocations:
                batch.remaining_quantity = batch.remaining_quantity - qty
                invoice_item = InvoiceItem(
                    invoice_id=invoice.id,
                    batch_id=batch.id,
                    quantity=qty,
                    unit_price=batch.current_selling_price,
                )
                db.add(invoice_item)
                total += batch.current_selling_price * qty

        invoice.total_amount = total
        db.commit()
        db.refresh(invoice)
        return invoice
    except Exception:
        db.rollback()
        raise


def ensure_product_exists(db: Session, product_id: int) -> None:
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
