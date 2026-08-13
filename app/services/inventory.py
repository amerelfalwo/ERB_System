from decimal import Decimal
from typing import List, Tuple

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.domain import Invoice, InvoiceItem, InvoiceType, Product, StockBatch, Payment
from app.schemas.invoice import InvoiceCreatePurchase, InvoiceCreateSell
from app.core.cache import invalidate_tenant_cache_sync


def create_purchase_invoice(db: Session, data: InvoiceCreatePurchase, tenant_id: int = None) -> Invoice:
    try:
        invoice = Invoice(
            party_id=data.party_id,
            invoice_type=InvoiceType.PURCHASE,
            total_amount=Decimal("0"),
            delivery_fee=data.delivery_fee,
            footer_custom_text=data.footer_custom_text,
            tenant_id=tenant_id,
        )
        db.add(invoice)
        db.flush()

        product_ids = list({item.product_id for item in data.items})
        products = db.execute(select(Product).where(Product.id.in_(product_ids))).scalars().all()
        product_map = {p.id: p for p in products}

        # Pre-fetch latest batch prices
        latest_batch_subq = (
            select(StockBatch.product_id, func.max(StockBatch.id).label("max_batch_id"))
            .where(StockBatch.product_id.in_(product_ids))
            .group_by(StockBatch.product_id)
            .subquery()
        )
        latest_batches = db.execute(
            select(StockBatch).join(latest_batch_subq, StockBatch.id == latest_batch_subq.c.max_batch_id)
        ).scalars().all()
        latest_batch_map = {b.product_id: b for b in latest_batches}

        total = Decimal("0")
        for item in data.items:
            selling_price = item.sell_price or Decimal("0")
            purchase_price = item.purchase_price or Decimal("0")
            
            product = product_map.get(item.product_id)
            if not product:
                raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
            
            if selling_price == 0:
                if product.sell_price and product.sell_price > 0:
                    selling_price = product.sell_price
                else:
                    prev_batch = latest_batch_map.get(item.product_id)
                    if prev_batch and prev_batch.current_selling_price and prev_batch.current_selling_price > 0:
                        selling_price = prev_batch.current_selling_price

            if purchase_price == 0:
                if product.purchase_price and product.purchase_price > 0:
                    purchase_price = product.purchase_price
                else:
                    prev_batch = latest_batch_map.get(item.product_id)
                    if prev_batch and prev_batch.purchase_price and prev_batch.purchase_price > 0:
                        purchase_price = prev_batch.purchase_price

            batch = StockBatch(
                product_id=item.product_id,
                purchase_price=purchase_price,
                current_selling_price=selling_price,
                initial_quantity=item.quantity,
                remaining_quantity=item.quantity,
                tenant_id=tenant_id,
                party_id=data.party_id,
            )
            db.add(batch)
            db.flush()

            invoice_item = InvoiceItem(
                invoice_id=invoice.id,
                batch_id=batch.id,
                quantity=item.quantity,
                unit_price=purchase_price,
                purchase_price=purchase_price,
                sell_price=selling_price,
            )
            db.add(invoice_item)
            total += purchase_price * item.quantity

            product.last_purchase_price = purchase_price
            db.add(product)

        invoice.total_amount = total + data.delivery_fee
        if data.amount_paid > 0:
            payment = Payment(party_id=data.party_id, invoice_id=invoice.id, amount=data.amount_paid)
            db.add(payment)
        db.commit()
        db.refresh(invoice)
        if tenant_id:
            invalidate_tenant_cache_sync(tenant_id, ["dashboard", "reports:profit", "reports:net-profit", "reports:inventory", "reports:party-profits", "parties"])
        return invoice
    except Exception:
        db.rollback()
        raise


def allocate_batches(db: Session, tenant_id: int, product_id: int, quantity: Decimal) -> List[Tuple[StockBatch, Decimal]]:
    stmt = select(StockBatch).where(
        StockBatch.product_id == product_id,
        StockBatch.tenant_id == tenant_id,
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


def get_latest_selling_price(db: Session, tenant_id: int, product_id: int) -> Decimal:
    price = db.execute(
        select(StockBatch.current_selling_price).where(
            StockBatch.product_id == product_id,
            StockBatch.tenant_id == tenant_id,
            StockBatch.remaining_quantity > 0,
        ).order_by(StockBatch.current_selling_price.desc()).limit(1)
    ).scalar_one_or_none()

    if price is None:
        price = db.execute(
            select(StockBatch.current_selling_price).where(
                StockBatch.product_id == product_id,
                StockBatch.tenant_id == tenant_id,
            ).order_by(StockBatch.current_selling_price.desc()).limit(1)
        ).scalar_one_or_none()

    if price is None:
        raise HTTPException(status_code=400, detail="No batches available")
    return price


def create_sell_invoice(db: Session, data: InvoiceCreateSell, tenant_id: int = None) -> Invoice:
    try:
        invoice = Invoice(
            party_id=data.party_id,
            invoice_type=InvoiceType.SELL,
            total_amount=Decimal("0"),
            delivery_fee=data.delivery_fee,
            footer_custom_text=data.footer_custom_text,
            tenant_id=tenant_id,
        )
        invoice_repo_db = db
        db.add(invoice)
        db.flush()

        product_ids = list({item.product_id for item in data.items})
        highest_price_map = {}
        if product_ids:
            hp_stmt = select(StockBatch.product_id, func.max(StockBatch.current_selling_price)).where(
                StockBatch.product_id.in_(product_ids),
                StockBatch.remaining_quantity > 0,
            ).group_by(StockBatch.product_id)
            if tenant_id is not None:
                hp_stmt = hp_stmt.where(StockBatch.tenant_id == tenant_id)
            hp_rows = db.execute(hp_stmt).all()
            highest_price_map = {r[0]: r[1] for r in hp_rows}

            missing_pids = [pid for pid in product_ids if pid not in highest_price_map]
            if missing_pids:
                fb_stmt = select(StockBatch.product_id, func.max(StockBatch.current_selling_price)).where(
                    StockBatch.product_id.in_(missing_pids)
                ).group_by(StockBatch.product_id)
                if tenant_id is not None:
                    fb_stmt = fb_stmt.where(StockBatch.tenant_id == tenant_id)
                fb_rows = db.execute(fb_stmt).all()
                for pid, pr in fb_rows:
                    highest_price_map[pid] = pr

        total = Decimal("0")
        for item in data.items:
            latest_price = highest_price_map.get(item.product_id)
            if latest_price is None:
                latest_price = get_latest_selling_price(db, tenant_id, item.product_id)
            effective_price = Decimal(str(item.sell_price)) if item.sell_price is not None else latest_price
            allocations = allocate_batches(db, tenant_id, item.product_id, item.quantity)
            for batch, qty in allocations:
                batch.remaining_quantity = batch.remaining_quantity - qty
                invoice_item = InvoiceItem(
                    invoice_id=invoice.id,
                    batch_id=batch.id,
                    quantity=qty,
                    unit_price=effective_price,
                    purchase_price=batch.purchase_price,
                    sell_price=effective_price,
                )
                db.add(invoice_item)
                total += effective_price * qty

        invoice.total_amount = total + data.delivery_fee
        if data.amount_paid > 0:
            payment = Payment(party_id=data.party_id, invoice_id=invoice.id, amount=data.amount_paid)
            db.add(payment)
        db.commit()
        db.refresh(invoice)
        if tenant_id:
            invalidate_tenant_cache_sync(tenant_id, ["dashboard", "reports:profit", "reports:net-profit", "reports:inventory", "reports:party-profits", "parties"])
        return invoice
    except Exception:
        db.rollback()
        raise


# Backwards-compatible alias
create_sale_invoice = create_sell_invoice


def ensure_product_exists(db: Session, product_id: int, tenant_id: int) -> None:
    product = db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
