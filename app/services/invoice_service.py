import logging
from decimal import Decimal
from typing import List, Tuple, Optional
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.cache import invalidate_tenant_cache_sync
from app.core.constants import (
    ERR_INSUFFICIENT_STOCK, ERR_NO_VALID_RETURN_ITEMS, ERR_RETURN_QTY_EXCEEDS,
    ERR_CANNOT_DELETE_HAS_STOCK, ERR_CANNOT_MODIFY_RETURN,
    ERR_CANNOT_MODIFY_PURCHASE_COUNT, ERR_INVALID_INVOICE_TYPE, ERR_INVALID_ITEM,
    INVOICE_TYPE_SELL, INVOICE_TYPE_PURCHASE, INVOICE_TYPE_SELL_RETURN,
    INVOICE_TYPE_PURCHASE_RETURN, STATUS_PAID, STATUS_PARTIAL, STATUS_UNPAID,
)
from app.models.domain import Invoice, InvoiceItem, InvoiceType, Party, Payment, Product, StockBatch
from app.repositories.base import BatchRepository, InvoiceRepository, PartyRepository
from app.schemas.invoice import InvoiceCreatePurchase, InvoiceCreateSell

logger = logging.getLogger(__name__)


def _invoice_status(paid: Decimal, total: Decimal) -> str:
    balance = total - paid
    if balance <= Decimal("0"):
        return STATUS_PAID
    if paid > Decimal("0"):
        return STATUS_PARTIAL
    return STATUS_UNPAID


def _build_invoice_dict(inv: Invoice, paid: Decimal, party_name_map: dict = None, returned_qty_map: dict = None) -> dict:
    balance = inv.total_amount - paid
    profit = Decimal("0")
    if inv.invoice_type == INVOICE_TYPE_SELL:
        for item in inv.items:
            cost = item.purchase_price if item.purchase_price is not None else (
                item.batch.purchase_price if item.batch and item.batch.purchase_price is not None else Decimal("0")
            )
            sell = item.sell_price if item.sell_price is not None else item.unit_price
            profit += (sell - cost) * item.quantity

    return {
        "id": inv.id,
        "party_id": inv.party_id,
        "party_name": (party_name_map or {}).get(inv.party_id) if party_name_map is not None else (inv.party.name if inv.party else None),
        "invoice_type": inv.invoice_type.value if inv.invoice_type else None,
        "total_amount": inv.total_amount,
        "subtotal": getattr(inv, "subtotal", Decimal("0")) or Decimal("0"),
        "total_discount": getattr(inv, "total_discount", Decimal("0")) or Decimal("0"),
        "discount_amount": getattr(inv, "discount_amount", Decimal("0")) or getattr(inv, "total_discount", Decimal("0")) or Decimal("0"),
        "delivery_fee": inv.delivery_fee if inv.delivery_fee else Decimal("0"),
        "reference_number": inv.reference_number,
        "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "notes": inv.notes,
        "footer_custom_text": inv.footer_custom_text,
        "paid_amount": paid,
        "balance": balance,
        "status": _invoice_status(paid, inv.total_amount),
        "invoice_profit": profit,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "items": [
            {
                "id": item.id,
                "batch_id": item.batch_id,
                "product_id": item.batch.product_id if item.batch else None,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "purchase_price": item.purchase_price if item.purchase_price else None,
                "sell_price": item.sell_price if item.sell_price else None,
                "product_name": item.batch.product.name if item.batch and item.batch.product else None,
                "already_returned_qty": returned_qty_map.get(item.id, Decimal("0")) if returned_qty_map else Decimal("0"),
                "original_invoice_item_id": item.original_invoice_item_id,
            }
            for item in inv.items
        ],
    }


def get_invoice_totals_svc(invoice_repo: InvoiceRepository, invoice: Invoice) -> dict:
    paid = invoice_repo.get_paid_amount(invoice.id)
    balance = invoice.total_amount - paid
    return {
        "total": invoice.total_amount,
        "paid": paid,
        "balance": balance,
        "status": _invoice_status(paid, invoice.total_amount),
    }


def get_party_previous_balance_svc(
    party_repo: PartyRepository,
    party_id: int,
    invoice_id: int,
    invoice_type: InvoiceType,
    party: Optional[Party] = None,
) -> Tuple[Decimal, Optional[Party]]:
    if not party:
        party = party_repo.get_by_id(party_id)
    initial_balance = party.initial_balance if party and party.initial_balance else Decimal("0")
    summary = party_repo.get_party_financial_summary_excluding(party_id, invoice_id)
    if invoice_type in (INVOICE_TYPE_SELL, INVOICE_TYPE_SELL_RETURN):
        inv_total = summary["sale_net"]
    else:
        inv_total = summary["purchase_net"]
    paid_total = summary["paid_total"]
    return initial_balance + inv_total - paid_total, party


def list_invoices_svc(invoice_repo: InvoiceRepository, party_id=None, invoice_type: str = None, search: str = None, status: str = None, skip: int = 0, limit: int = 100) -> dict:
    total = invoice_repo.count(party_id=party_id, invoice_type=invoice_type, search=search, status=status)
    invoices = invoice_repo.list(party_id=party_id, invoice_type=invoice_type, search=search, status=status, skip=skip, limit=limit)
    ids = [i.id for i in invoices]
    payment_map = invoice_repo.bulk_payment_sums(ids)
    party_ids = {i.party_id for i in invoices if i.party_id}
    party_name_map = invoice_repo.bulk_party_names(party_ids)
    
    item_ids = [item.id for inv in invoices for item in inv.items]
    returned_qty_map = {}
    if item_ids:
        rows = invoice_repo._db.execute(
            select(InvoiceItem.original_invoice_item_id, func.sum(InvoiceItem.quantity))
            .where(InvoiceItem.original_invoice_item_id.in_(item_ids))
            .group_by(InvoiceItem.original_invoice_item_id)
        ).all()
        returned_qty_map = {orig_id: qty for orig_id, qty in rows}
        
    data = [_build_invoice_dict(inv, Decimal(str(payment_map.get(inv.id, 0))), party_name_map, returned_qty_map) for inv in invoices]
    return {"total": total, "skip": skip, "limit": limit, "data": data}


def allocate_batches_svc(
    batch_repo: BatchRepository, product_id: int, quantity: Decimal, party_id: int = None
) -> List[Tuple[StockBatch, Decimal]]:
    batches = batch_repo.get_fifo_batches(product_id, party_id=party_id)
    remaining = quantity
    allocations: List[Tuple[StockBatch, Decimal]] = []
    for batch in batches:
        if remaining <= 0:
            break
        take = batch.remaining_quantity if batch.remaining_quantity <= remaining else remaining
        allocations.append((batch, take))
        remaining -= take
    if remaining > 0:
        raise HTTPException(status_code=400, detail=ERR_INSUFFICIENT_STOCK)
    return allocations


def create_purchase_invoice_svc(
    db: Session, invoice_repo: InvoiceRepository, batch_repo: BatchRepository,
    data: InvoiceCreatePurchase, tenant_id: int
) -> Invoice:
    try:
        logger.info("Creating purchase invoice for party_id=%s, tenant_id=%s, items=%d",
                    data.party_id, tenant_id, len(data.items))

        invoice = Invoice(
            party_id=data.party_id,
            invoice_type=INVOICE_TYPE_PURCHASE,
            total_amount=Decimal("0"),
            delivery_fee=data.delivery_fee,
            reference_number=data.reference_number,
            issue_date=data.issue_date or datetime.now(timezone.utc),
            due_date=data.due_date,
            notes=data.notes,
            footer_custom_text=data.footer_custom_text,
            tenant_id=tenant_id,
        )
        invoice_repo.add(invoice)
        invoice_repo.flush()

        product_ids = list({item.product_id for item in data.items})
        products = db.execute(
            select(Product).where(Product.id.in_(product_ids), Product.tenant_id == tenant_id)
        ).scalars().all()
        product_map = {p.id: p for p in products}
        latest_batches = batch_repo.get_latest_batches_for_products(product_ids)

        subtotal = Decimal("0")
        total_item_discount = Decimal("0")
        total_item_tax = Decimal("0")
        batches_created = []
        for item in data.items:
            selling_price = item.sell_price
            purchase_price = item.purchase_price
            
            product = product_map.get(item.product_id)
            if not product:
                raise HTTPException(status_code=404, detail=f"المنتج ID {item.product_id} غير موجود")
            
            if not selling_price or selling_price <= 0:
                if product.sell_price and product.sell_price > 0:
                    selling_price = product.sell_price
                else:
                    prev_batch = latest_batches.get(item.product_id)
                    if prev_batch and prev_batch.current_selling_price and prev_batch.current_selling_price > 0:
                        selling_price = prev_batch.current_selling_price
                        
            if not selling_price or selling_price <= 0:
                selling_price = Decimal("0")

            if not purchase_price or purchase_price <= 0:
                if product.purchase_price and product.purchase_price > 0:
                    purchase_price = product.purchase_price
                else:
                    prev_batch = latest_batches.get(item.product_id)
                    if prev_batch and prev_batch.purchase_price and prev_batch.purchase_price > 0:
                        purchase_price = prev_batch.purchase_price
                        
            if not purchase_price or purchase_price <= 0:
                raise HTTPException(status_code=400, detail=f"سعر الشراء غير محدد أو صفر للمنتج ID {item.product_id}. يرجى إدخال سعر شراء صحيح.")

            total_stock = batch_repo.get_total_stock(item.product_id)
            new_stock = Decimal(str(item.quantity))
            current_avg = product.average_cost if product.average_cost else Decimal("0")
            new_cost = purchase_price
            
            if total_stock + new_stock > 0:
                updated_average_cost = ((total_stock * current_avg) + (new_stock * new_cost)) / (total_stock + new_stock)
            else:
                updated_average_cost = new_cost

            batch = StockBatch(
                product_id=item.product_id,
                purchase_price=purchase_price,
                current_selling_price=selling_price,
                initial_quantity=item.quantity,
                remaining_quantity=item.quantity,
                tenant_id=tenant_id,
                party_id=data.party_id,
            )
            batch_repo.add(batch)
            batch_repo.flush()
            batches_created.append(batch.id)
            logger.info("  Created batch id=%s for product_id=%s, qty=%s, purchase=%s, sell=%s",
                        batch.id, item.product_id, item.quantity, purchase_price, selling_price)

            discount = item.discount or Decimal("0")
            tax = item.tax or Decimal("0")

            invoice_item = InvoiceItem(
                invoice_id=invoice.id,
                batch_id=batch.id,
                quantity=item.quantity,
                unit_price=purchase_price,
                purchase_price=purchase_price,
                sell_price=selling_price,
                discount=discount,
                tax=tax,
            )
            invoice_repo.add(invoice_item)
            subtotal += purchase_price * item.quantity
            total_item_discount += discount
            total_item_tax += tax

            product.last_purchase_price = purchase_price
            product.purchase_price = purchase_price
            product.average_cost = updated_average_cost
            invoice_repo.add(product)

        invoice.discount_amount = Decimal("0")
        invoice.total_discount = total_item_discount
        invoice.total_tax = (data.total_tax or Decimal("0")) + total_item_tax
        invoice.subtotal = subtotal
        invoice.total_amount = invoice.subtotal - invoice.total_discount + invoice.total_tax + data.delivery_fee
        if invoice.total_amount < 0:
            raise HTTPException(status_code=400, detail="إجمالي الفاتورة لا يمكن أن يكون أقل من الصفر")
        # ── Rule: cannot pay more than the invoice total ──
        max_payable = invoice.total_amount
        capped_payment = min(Decimal(str(data.amount_paid)), max_payable)
        if capped_payment > 0:
            payment = Payment(party_id=data.party_id, invoice_id=invoice.id, amount=capped_payment)
            invoice_repo.add(payment)

        invoice_repo.commit()
        invoice_repo.refresh(invoice)
        invalidate_tenant_cache_sync(tenant_id, ["dashboard", "reports:profit", "reports:net-profit", "reports:inventory", "reports:party-profits", "parties"])
        logger.info("Purchase invoice #%s created successfully. Batches: %s. Total: %s",
                    invoice.id, batches_created, invoice.total_amount)
        return invoice
    except HTTPException:
        invoice_repo.rollback()
        raise
    except Exception as exc:
        logger.error("PURCHASE INVOICE CREATION FAILED: %s", exc, exc_info=True)
        invoice_repo.rollback()
        raise


def create_sell_invoice_svc(
    invoice_repo: InvoiceRepository, batch_repo: BatchRepository,
    data: InvoiceCreateSell, tenant_id: int
) -> Invoice:
    try:
        invoice = Invoice(
            party_id=data.party_id,
            invoice_type=INVOICE_TYPE_SELL,
            total_amount=Decimal("0"),
            delivery_fee=data.delivery_fee,
            reference_number=data.reference_number,
            issue_date=data.issue_date or datetime.now(timezone.utc),
            due_date=data.due_date,
            notes=data.notes,
            footer_custom_text=data.footer_custom_text,
            tenant_id=tenant_id,
        )
        invoice_repo.add(invoice)
        invoice_repo.flush()

        product_ids = list({item.product_id for item in data.items})
        highest_prices = {}
        if product_ids:
            rows = batch_repo._db.execute(
                select(StockBatch.product_id, func.max(StockBatch.current_selling_price))
                .where(
                    StockBatch.product_id.in_(product_ids),
                    StockBatch.tenant_id == tenant_id,
                    StockBatch.remaining_quantity > 0,
                )
                .group_by(StockBatch.product_id)
            ).all()
            highest_prices = {row[0]: row[1] for row in rows}
            
            missing_pids = [pid for pid in product_ids if pid not in highest_prices]
            if missing_pids:
                fallback_rows = batch_repo._db.execute(
                    select(StockBatch.product_id, func.max(StockBatch.current_selling_price))
                    .where(
                        StockBatch.product_id.in_(missing_pids),
                        StockBatch.tenant_id == tenant_id,
                    )
                    .group_by(StockBatch.product_id)
                ).all()
                for pid, pr in fallback_rows:
                    highest_prices[pid] = pr

        subtotal = Decimal("0")
        total_item_discount = Decimal("0")
        total_item_tax = Decimal("0")
        
        for item in data.items:
            latest_price = highest_prices.get(item.product_id)
            if latest_price is None:
                raise HTTPException(status_code=400, detail="No batches available")
            effective_price = Decimal(str(item.sell_price)) if item.sell_price is not None else latest_price
            if effective_price <= Decimal("0"):
                raise HTTPException(status_code=400, detail=f"سعر البيع غير محدد أو صفر للمنتج ID {item.product_id}. يرجى إدخال سعر بيع صحيح.")
            allocations = allocate_batches_svc(batch_repo, item.product_id, item.quantity)
            for batch, qty in allocations:
                batch.remaining_quantity = batch.remaining_quantity - qty
                locked_cost = batch.purchase_price
                
                # Pro-rate discount and tax based on the quantity allocated
                fraction = qty / item.quantity if item.quantity > 0 else Decimal("0")
                discount = (item.discount or Decimal("0")) * fraction
                tax = (item.tax or Decimal("0")) * fraction
                
                invoice_item = InvoiceItem(
                    invoice_id=invoice.id,
                    batch_id=batch.id,
                    quantity=qty,
                    unit_price=effective_price,
                    purchase_price=locked_cost,
                    sell_price=effective_price,
                    discount=discount,
                    tax=tax,
                )
                invoice_repo.add(invoice_item)
                subtotal += effective_price * qty
                total_item_discount += discount
                total_item_tax += tax

        disc_amount = (data.discount_amount if data.discount_amount is not None and data.discount_amount > 0 else (data.total_discount or Decimal("0")))
        invoice.discount_amount = disc_amount
        invoice.total_discount = disc_amount + total_item_discount
        invoice.total_tax = (data.total_tax or Decimal("0")) + total_item_tax
        invoice.subtotal = subtotal
        invoice.total_amount = invoice.subtotal - invoice.total_discount + invoice.total_tax + data.delivery_fee
        if invoice.total_amount < 0:
            raise HTTPException(status_code=400, detail="إجمالي الفاتورة لا يمكن أن يكون أقل من الصفر")
        # ── Rule: cannot pay more than the invoice total ──
        max_payable = invoice.total_amount
        capped_payment = min(Decimal(str(data.amount_paid)), max_payable)
        if capped_payment > 0:
            payment = Payment(party_id=data.party_id, invoice_id=invoice.id, amount=capped_payment)
            invoice_repo.add(payment)

        invoice_repo.commit()
        invoice_repo.refresh(invoice)
        return invoice
    except Exception:
        invoice_repo.rollback()
        raise


def update_invoice_svc(
    db: Session, invoice_repo: InvoiceRepository, batch_repo: BatchRepository,
    invoice: Invoice, data: dict, tenant_id: int
) -> dict:
    try:
        items_updated = False
        new_items_total = Decimal("0")

        # Prevent modification of items if there are associated returns
        if data.get("items") is not None and invoice.items:
            item_ids = [item.id for item in invoice.items]
            has_returns = invoice_repo._db.execute(
                select(InvoiceItem.original_invoice_item_id)
                .where(InvoiceItem.original_invoice_item_id.in_(item_ids))
                .limit(1)
            ).scalar_one_or_none()
            if has_returns:
                raise HTTPException(status_code=400, detail="لا يمكن تعديل الفاتورة لوجود مرتجعات مرتبطة بها")

        new_items = data.get("items")
        if new_items is not None:
            if len(new_items) == 0:
                raise HTTPException(status_code=400, detail="لا يمكن ترك الفاتورة بدون أي بنود")
            items_updated = True
            
            old_global_discount = (invoice.total_discount or Decimal("0")) - sum(i.discount or Decimal("0") for i in invoice.items)
            old_global_tax = (invoice.total_tax or Decimal("0")) - sum(i.tax or Decimal("0") for i in invoice.items)
            
            if invoice.invoice_type == INVOICE_TYPE_SELL:
                for old_item in invoice.items:
                    b = batch_repo.get_by_id(old_item.batch_id)
                    if b:
                        b.remaining_quantity += old_item.quantity
                    invoice_repo.delete(old_item)
                invoice_repo.flush()

                subtotal = Decimal("0")
                total_item_discount = Decimal("0")
                total_item_tax = Decimal("0")
                for item in new_items:
                    product_id = item.get("product_id")
                    if not product_id:
                        if "batch_id" in item:
                            b = batch_repo.get_by_id(item["batch_id"])
                            if b:
                                product_id = b.product_id
                        if not product_id:
                            raise HTTPException(status_code=400, detail="يجب توفير product_id لكل صنف في الفاتورة")
                            
                    quantity = Decimal(str(item.get("quantity", 0)))
                    sell_price = item.get("sell_price") or item.get("unit_price")
                    
                    latest_price = batch_repo.get_highest_selling_price(product_id)
                    if latest_price is None:
                        raise HTTPException(status_code=400, detail=f"No batches available for product {product_id}")
                    effective_price = Decimal(str(sell_price)) if sell_price is not None else latest_price
                    if effective_price <= Decimal("0"):
                        raise HTTPException(status_code=400, detail=f"سعر البيع غير محدد أو صفر للمنتج ID {product_id}. يرجى إدخال سعر بيع صحيح.")
                        
                    if quantity <= Decimal("0"):
                        raise HTTPException(status_code=400, detail="الكمية يجب أن تكون أكبر من الصفر")
                        
                    allocations = allocate_batches_svc(batch_repo, product_id, quantity)
                    for batch, qty in allocations:
                        batch.remaining_quantity = batch.remaining_quantity - qty
                        locked_cost = batch.purchase_price
                        
                        fraction = qty / quantity if quantity > 0 else Decimal("0")
                        discount = Decimal(str(item.get("discount", "0"))) * fraction
                        tax = Decimal(str(item.get("tax", "0"))) * fraction
                        
                        invoice_item = InvoiceItem(
                            invoice_id=invoice.id,
                            batch_id=batch.id,
                            quantity=qty,
                            unit_price=effective_price,
                            purchase_price=locked_cost,
                            sell_price=effective_price,
                            discount=discount,
                            tax=tax,
                        )
                        invoice_repo.add(invoice_item)
                        subtotal += effective_price * qty
                        total_item_discount += discount
                        total_item_tax += tax
                
                invoice.subtotal = subtotal
                new_global_discount = Decimal(str(data["total_discount"])) if "total_discount" in data else old_global_discount
                new_global_tax = Decimal(str(data["total_tax"])) if "total_tax" in data else old_global_tax
                invoice.total_discount = new_global_discount + total_item_discount
                invoice.total_tax = new_global_tax + total_item_tax

            elif invoice.invoice_type == INVOICE_TYPE_PURCHASE:
                old_map = {str(item.batch_id): item for item in invoice.items}
                if len(new_items) != len(invoice.items):
                    raise HTTPException(status_code=400, detail=ERR_CANNOT_MODIFY_PURCHASE_COUNT)

                subtotal = Decimal("0")
                total_item_discount = Decimal("0")
                total_item_tax = Decimal("0")
                for item_data in new_items:
                    batch_id = str(item_data.get("batch_id"))
                    new_qty = Decimal(str(item_data.get("quantity", 0)))
                    new_price = Decimal(str(item_data.get("unit_price", 0)))
                    new_sell_price = Decimal(str(item_data.get("sell_price", 0)))
                    discount = Decimal(str(item_data.get("discount", 0)))
                    tax = Decimal(str(item_data.get("tax", 0)))
                    
                    old_item = old_map.get(batch_id)
                    if not old_item:
                        raise HTTPException(status_code=400, detail=f"البند (دفعة #{batch_id}) غير موجود في الفاتورة")
                    batch = db.execute(select(StockBatch).where(StockBatch.id == int(batch_id), StockBatch.tenant_id == tenant_id)).scalar_one_or_none()
                    if not batch:
                        raise HTTPException(status_code=404, detail=f"الدفعة #{batch_id} غير موجودة")
                    sold_qty = batch.initial_quantity - batch.remaining_quantity
                    
                    if new_qty <= 0:
                        raise HTTPException(status_code=400, detail="الكمية يجب أن تكون أكبر من الصفر")
                    if new_price <= 0:
                        raise HTTPException(status_code=400, detail="سعر الشراء يجب أن يكون أكبر من الصفر")
                        
                    if new_qty < sold_qty:
                        raise HTTPException(status_code=400, detail=f"الكمية الجديدة ({new_qty}) أقل من الكمية المباعة فعلاً ({sold_qty})")
                    batch.initial_quantity = new_qty
                    batch.remaining_quantity = new_qty - sold_qty
                    batch.purchase_price = new_price
                    old_item.quantity = new_qty
                    old_item.unit_price = new_price
                    old_item.purchase_price = new_price
                    old_item.discount = discount
                    old_item.tax = tax
                    
                    if new_sell_price > 0:
                        batch.current_selling_price = new_sell_price
                        old_item.sell_price = new_sell_price
                    
                    # Update product's last purchase price and sell price
                    if batch.product:
                        batch.product.last_purchase_price = new_price
                        batch.product.purchase_price = new_price
                        if new_sell_price > 0:
                            batch.product.sell_price = new_sell_price
                        
                    subtotal += new_qty * new_price
                    total_item_discount += discount
                    total_item_tax += tax
                
                invoice.subtotal = subtotal
                new_global_discount = Decimal(str(data["total_discount"])) if "total_discount" in data else old_global_discount
                new_global_tax = Decimal(str(data["total_tax"])) if "total_tax" in data else old_global_tax
                invoice.total_discount = new_global_discount + total_item_discount
                invoice.total_tax = new_global_tax + total_item_tax
            else:
                raise HTTPException(status_code=400, detail=ERR_CANNOT_MODIFY_RETURN)

        delivery_fee = data.get("delivery_fee")
        if delivery_fee is not None:
            new_fee = Decimal(str(delivery_fee))
            if new_fee < 0:
                raise HTTPException(status_code=400, detail="رسوم التوصيل لا يمكن أن تكون سالبة")
            invoice.delivery_fee = new_fee

        if items_updated or delivery_fee is not None or "total_discount" in data or "total_tax" in data:
            if "total_discount" in data and not items_updated:
                invoice.total_discount = Decimal(str(data["total_discount"])) + sum(i.discount or Decimal("0") for i in invoice.items)
            if "total_tax" in data and not items_updated:
                invoice.total_tax = Decimal(str(data["total_tax"])) + sum(i.tax or Decimal("0") for i in invoice.items)
            
            invoice.total_amount = (invoice.subtotal or Decimal("0")) - (invoice.total_discount or Decimal("0")) + (invoice.total_tax or Decimal("0")) + (invoice.delivery_fee or Decimal("0"))
            if invoice.total_amount < 0:
                raise HTTPException(status_code=400, detail="إجمالي الفاتورة لا يمكن أن يكون أقل من الصفر")

        footer = data.get("footer_custom_text")
        if footer is not None:
            invoice.footer_custom_text = footer
            
        if "reference_number" in data:
            invoice.reference_number = data.get("reference_number")
        if "issue_date" in data:
            invoice.issue_date = data.get("issue_date")
        if "due_date" in data:
            invoice.due_date = data.get("due_date")
        if "notes" in data:
            invoice.notes = data.get("notes")

        invoice_repo.commit()
        invalidate_tenant_cache_sync(tenant_id, ["dashboard", "reports:profit", "reports:net-profit", "reports:inventory", "reports:party-profits", "parties"])
    except Exception:
        invoice_repo.rollback()
        raise

    # Re-fetch with joinedload so item.batch.product is always available
    invoice = invoice_repo.get_by_id(invoice.id)

    paid = invoice_repo.get_paid_amount(invoice.id)
    balance = invoice.total_amount - paid
    item_ids = [i.id for i in invoice.items]
    returned_qty_map = invoice_repo.get_returned_quantities_for_items(item_ids)
    items_out = []
    for i in invoice.items:
        product_name = i.batch.product.name if i.batch and i.batch.product else None
        already_returned_qty = returned_qty_map.get(i.id, Decimal("0"))
        items_out.append({
            "id": i.id, "batch_id": i.batch_id,
            "product_id": i.batch.product_id if i.batch else None,
            "product_name": product_name,
            "quantity": i.quantity, "unit_price": i.unit_price,
            "purchase_price": i.purchase_price if i.purchase_price else None,
            "sell_price": i.sell_price if i.sell_price else None,
            "already_returned_qty": already_returned_qty,
        })

    return {
        "id": invoice.id,
        "party_id": invoice.party_id,
        "invoice_type": invoice.invoice_type.value if invoice.invoice_type else None,
        "total_amount": invoice.total_amount,
        "delivery_fee": invoice.delivery_fee if invoice.delivery_fee else Decimal("0"),
        "reference_number": invoice.reference_number,
        "issue_date": invoice.issue_date.isoformat() if invoice.issue_date else None,
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "notes": invoice.notes,
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
        "paid_amount": paid,
        "balance": balance,
        "status": _invoice_status(paid, invoice.total_amount),
        "items": items_out,
    }


def delete_invoice_svc(
    invoice_repo: InvoiceRepository, batch_repo: BatchRepository, invoice: Invoice
) -> None:
    try:
        tenant_id = invoice.tenant_id
        if invoice.items:
            item_ids = [item.id for item in invoice.items]
            has_returns = invoice_repo._db.execute(
                select(InvoiceItem.original_invoice_item_id)
                .where(InvoiceItem.original_invoice_item_id.in_(item_ids))
                .limit(1)
            ).scalar_one_or_none()
            if has_returns:
                raise HTTPException(status_code=400, detail="لا يمكن حذف الفاتورة لوجود مرتجعات مرتبطة بها")

        batches_to_delete = []
        if invoice.invoice_type in (INVOICE_TYPE_SELL, INVOICE_TYPE_PURCHASE_RETURN):
            batch_ids = [item.batch_id for item in invoice.items if item.batch_id]
            if batch_ids:
                batches = batch_repo._db.execute(
                    select(StockBatch).where(StockBatch.id.in_(batch_ids))
                ).scalars().all()
                batch_map = {b.id: b for b in batches}
                for item in invoice.items:
                    b = batch_map.get(item.batch_id)
                    if b:
                        b.remaining_quantity += item.quantity
        elif invoice.invoice_type in (INVOICE_TYPE_PURCHASE, INVOICE_TYPE_SELL_RETURN):
            batch_ids = [item.batch_id for item in invoice.items if item.batch_id]
            if batch_ids:
                other_items_count = invoice_repo._db.execute(
                    select(InvoiceItem.batch_id)
                    .where(InvoiceItem.batch_id.in_(batch_ids), InvoiceItem.invoice_id != invoice.id)
                    .limit(1)
                ).scalar_one_or_none()
                if other_items_count:
                    raise HTTPException(
                        status_code=400, 
                        detail=ERR_CANNOT_DELETE_HAS_STOCK
                    )
                batches_to_delete = batch_repo._db.execute(
                    select(StockBatch).where(StockBatch.id.in_(batch_ids))
                ).scalars().all()

        for item in invoice.items:
            invoice_repo.delete(item)
        invoice_repo.flush()

        for b in batches_to_delete:
            batch_repo.delete(b)

        for payment in invoice.payments:
            invoice_repo.delete(payment)
        invoice_repo.flush()

        invoice_repo.delete(invoice)
        invoice_repo.commit()
        invalidate_tenant_cache_sync(tenant_id, ["dashboard", "reports:profit", "reports:net-profit", "reports:inventory", "reports:party-profits", "parties"])
    except Exception:
        invoice_repo.rollback()
        raise


def process_return_svc(
    invoice_repo: InvoiceRepository, batch_repo: BatchRepository,
    orig_invoice: Invoice, data: dict, tenant_id: int
) -> Invoice:
    if orig_invoice.invoice_type not in (INVOICE_TYPE_SELL, INVOICE_TYPE_PURCHASE):
        raise HTTPException(status_code=400, detail=ERR_INVALID_INVOICE_TYPE)

    return_type = (
        INVOICE_TYPE_SELL_RETURN
        if orig_invoice.invoice_type == INVOICE_TYPE_SELL
        else INVOICE_TYPE_PURCHASE_RETURN
    )

    try:
        # ── Pre-flight stock check for Purchase Returns ──────────────────────
        if return_type == INVOICE_TYPE_PURCHASE_RETURN:
            # Aggregate requested return quantities per product
            product_qty_map: dict = {}
            for ret_item in data.get("items", []):
                ret_qty = Decimal(str(ret_item.get("quantity", 0)))
                if ret_qty <= 0:
                    continue
                orig_item_id = ret_item.get("invoice_item_id")
                orig_item = invoice_repo._db.execute(
                    select(InvoiceItem).where(InvoiceItem.id == orig_item_id)
                ).scalar_one_or_none()
                if orig_item and orig_item.batch:
                    pid = orig_item.batch.product_id
                    product_qty_map[pid] = product_qty_map.get(pid, Decimal("0")) + ret_qty

            for product_id, needed_qty in product_qty_map.items():
                current_stock = invoice_repo._db.execute(
                    select(func.coalesce(func.sum(StockBatch.remaining_quantity), 0)).where(
                        StockBatch.product_id == product_id,
                        StockBatch.tenant_id == tenant_id,
                        (StockBatch.party_id == orig_invoice.party_id) | (StockBatch.party_id.is_(None))
                    )
                ).scalar_one()
                if Decimal(str(current_stock)) < needed_qty:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Insufficient stock for this return. Available: {current_stock}, Requested: {needed_qty}",
                    )
        # ─────────────────────────────────────────────────────────────────────

        return_invoice = Invoice(
            tenant_id=tenant_id,
            party_id=orig_invoice.party_id,
            invoice_type=return_type,
            total_amount=Decimal("0"),
            reference_number=data.get("reference_number"),
            issue_date=data.get("issue_date"),
            due_date=data.get("due_date"),
            notes=data.get("notes"),
            footer_custom_text=data.get("footer_custom_text"),
        )
        invoice_repo.add(return_invoice)
        invoice_repo.flush()

        total_return = Decimal("0")
        for ret_item in data.get("items", []):
            ret_qty = Decimal(str(ret_item.get("quantity", 0)))
            if ret_qty <= 0:
                continue

            orig_item_id = ret_item.get("invoice_item_id")
            orig_item = invoice_repo._db.execute(
                select(InvoiceItem).where(InvoiceItem.id == orig_item_id)
            ).scalar_one_or_none()

            if not orig_item or orig_item.invoice_id != orig_invoice.id:
                raise HTTPException(status_code=400, detail=ERR_INVALID_ITEM)
                
            already_returned_qty = invoice_repo._db.execute(
                select(func.sum(InvoiceItem.quantity))
                .where(InvoiceItem.original_invoice_item_id == orig_item_id)
            ).scalar() or Decimal("0")

            if ret_qty + already_returned_qty > orig_item.quantity:
                raise HTTPException(status_code=400, detail=ERR_RETURN_QTY_EXCEEDS)

            orig_batch = batch_repo.get_by_id(orig_item.batch_id)

            if return_type == INVOICE_TYPE_SELL_RETURN:
                new_batch = StockBatch(
                    tenant_id=tenant_id,
                    product_id=orig_batch.product_id,
                    party_id=orig_batch.party_id,
                    purchase_price=orig_batch.purchase_price,
                    current_selling_price=orig_batch.current_selling_price,
                    initial_quantity=ret_qty,
                    remaining_quantity=ret_qty,
                )
                batch_repo.add(new_batch)
                batch_repo.flush()
                
                return_unit_price = orig_item.unit_price
                new_ii = InvoiceItem(
                    invoice_id=return_invoice.id, batch_id=new_batch.id,
                    original_invoice_item_id=orig_item_id,
                    quantity=ret_qty, unit_price=return_unit_price,
                    purchase_price=orig_item.purchase_price, sell_price=orig_item.sell_price,
                )
                invoice_repo.add(new_ii)
                total_return += ret_qty * return_unit_price
            else:
                # Purchase return: use allocate_batches_svc to subtract from any available stock
                allocations = allocate_batches_svc(
                    batch_repo,
                    orig_batch.product_id,
                    ret_qty,
                    party_id=orig_invoice.party_id,
                )
                
                return_unit_price = orig_item.unit_price
                
                for batch, alloc_qty in allocations:
                    batch.remaining_quantity -= alloc_qty
                    new_ii = InvoiceItem(
                        invoice_id=return_invoice.id, batch_id=batch.id,
                        original_invoice_item_id=orig_item_id,
                        quantity=alloc_qty, unit_price=return_unit_price,
                        purchase_price=orig_item.purchase_price, sell_price=orig_item.sell_price,
                    )
                    invoice_repo.add(new_ii)
                    total_return += alloc_qty * return_unit_price

        if total_return == Decimal("0"):
            raise HTTPException(status_code=400, detail=ERR_NO_VALID_RETURN_ITEMS)

        return_invoice.total_amount = total_return

        # ── Auto-create a negative payment to offset the return value ────────
        # This ensures the party balance is correctly reduced when a return is
        # processed: if the customer/supplier already paid, the return cancels
        # the corresponding portion of that payment so the net balance stays accurate.
        total_paid_on_party = invoice_repo._db.execute(
            select(func.coalesce(func.sum(Payment.amount), Decimal("0"))).where(
                Payment.party_id == orig_invoice.party_id
            )
        ).scalar_one()
        total_paid_on_party = Decimal(str(total_paid_on_party))

        if total_paid_on_party > Decimal("0"):
            # Negative payment capped at what was actually paid
            offset_amount = min(total_return, total_paid_on_party)
            negative_payment = Payment(
                party_id=orig_invoice.party_id,
                invoice_id=return_invoice.id,
                amount=-offset_amount,
            )
            invoice_repo.add(negative_payment)
        # ─────────────────────────────────────────────────────────────────────

        invoice_repo.commit()
        invalidate_tenant_cache_sync(tenant_id, ["dashboard", "reports:profit", "reports:net-profit", "reports:inventory", "reports:party-profits", "parties"])
    except Exception:
        invoice_repo.rollback()
        raise

    invoice_repo.refresh(return_invoice)
    return return_invoice
