from decimal import Decimal
from typing import List, Tuple

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import (
    ERR_INSUFFICIENT_STOCK, ERR_NO_VALID_RETURN_ITEMS, ERR_RETURN_QTY_EXCEEDS,
    ERR_CANNOT_DELETE_HAS_STOCK, ERR_CANNOT_MODIFY_RETURN,
    ERR_CANNOT_MODIFY_PURCHASE_COUNT, ERR_INVALID_INVOICE_TYPE, ERR_INVALID_ITEM,
    INVOICE_TYPE_SALE, INVOICE_TYPE_PURCHASE, INVOICE_TYPE_SALE_RETURN,
    INVOICE_TYPE_PURCHASE_RETURN, STATUS_PAID, STATUS_PARTIAL, STATUS_UNPAID,
)
from app.models.domain import Invoice, InvoiceItem, InvoiceType, Payment, Product, StockBatch
from app.repositories.base import BatchRepository, InvoiceRepository, PartyRepository
from app.schemas.invoice import InvoiceCreatePurchase, InvoiceCreateSale


def _invoice_status(paid: Decimal, total: Decimal) -> str:
    balance = total - paid
    if balance <= Decimal("0"):
        return STATUS_PAID
    if paid > Decimal("0"):
        return STATUS_PARTIAL
    return STATUS_UNPAID


def _build_invoice_dict(inv: Invoice, paid: Decimal) -> dict:
    balance = inv.total_amount - paid
    profit = Decimal("0")
    if inv.invoice_type == INVOICE_TYPE_SALE:
        for item in inv.items:
            cost = item.purchase_price if item.purchase_price is not None else (
                item.batch.purchase_price if item.batch else Decimal("0")
            )
            sale = item.sale_price if item.sale_price is not None else item.unit_price
            profit += (sale - cost) * item.quantity
        profit -= inv.delivery_fee or Decimal("0")

    return {
        "id": inv.id,
        "party_id": inv.party_id,
        "invoice_type": inv.invoice_type.value if inv.invoice_type else None,
        "total_amount": float(inv.total_amount),
        "delivery_fee": float(inv.delivery_fee) if inv.delivery_fee else 0,
        "footer_custom_text": inv.footer_custom_text,
        "paid_amount": float(paid),
        "balance": float(balance),
        "status": _invoice_status(paid, inv.total_amount),
        "invoice_profit": float(profit),
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "items": [
            {
                "id": item.id,
                "batch_id": item.batch_id,
                "product_id": item.batch.product_id if item.batch else None,
                "quantity": float(item.quantity),
                "unit_price": float(item.unit_price),
                "purchase_price": float(item.purchase_price) if item.purchase_price else None,
                "sale_price": float(item.sale_price) if item.sale_price else None,
                "product_name": item.batch.product.name if item.batch and item.batch.product else None,
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
) -> Decimal:
    if invoice_type == INVOICE_TYPE_SALE:
        inv_total = party_repo.total_invoiced_net_excluding(party_id, invoice_id)
    else:
        inv_total = party_repo.total_invoiced_excluding(party_id, invoice_type, invoice_id)
    paid_total = party_repo.total_paid_excluding(party_id, invoice_id)
    return max(Decimal("0"), inv_total - paid_total)


def list_invoices_svc(invoice_repo: InvoiceRepository, party_id=None) -> list:
    invoices = invoice_repo.list(party_id=party_id)
    ids = [i.id for i in invoices]
    payment_map = invoice_repo.bulk_payment_sums(ids)
    return [_build_invoice_dict(inv, Decimal(str(payment_map.get(inv.id, 0)))) for inv in invoices]


def allocate_batches_svc(
    batch_repo: BatchRepository, product_id: int, quantity: Decimal
) -> List[Tuple[StockBatch, Decimal]]:
    batches = batch_repo.get_fifo_batches(product_id)
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
        invoice = Invoice(
            party_id=data.party_id,
            invoice_type=INVOICE_TYPE_PURCHASE,
            total_amount=Decimal("0"),
            delivery_fee=data.delivery_fee,
            footer_custom_text=data.footer_custom_text,
            tenant_id=tenant_id,
        )
        invoice_repo.add(invoice)
        invoice_repo.flush()

        total = Decimal("0")
        for item in data.items:
            batch = StockBatch(
                product_id=item.product_id,
                purchase_price=item.purchase_price,
                current_selling_price=item.selling_price,
                initial_quantity=item.quantity,
                remaining_quantity=item.quantity,
                tenant_id=tenant_id,
            )
            batch_repo.add(batch)
            batch_repo.flush()

            invoice_item = InvoiceItem(
                invoice_id=invoice.id,
                batch_id=batch.id,
                quantity=item.quantity,
                unit_price=item.purchase_price,
                purchase_price=item.purchase_price,
                sale_price=item.selling_price,
            )
            invoice_repo.add(invoice_item)
            total += item.purchase_price * item.quantity

            product = db.execute(select(Product).where(Product.id == item.product_id)).scalar_one()
            product.last_purchase_price = item.purchase_price
            invoice_repo.add(product)

        invoice.total_amount = total + data.delivery_fee
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


def create_sale_invoice_svc(
    invoice_repo: InvoiceRepository, batch_repo: BatchRepository,
    data: InvoiceCreateSale, tenant_id: int
) -> Invoice:
    try:
        invoice = Invoice(
            party_id=data.party_id,
            invoice_type=INVOICE_TYPE_SALE,
            total_amount=Decimal("0"),
            delivery_fee=data.delivery_fee,
            footer_custom_text=data.footer_custom_text,
            tenant_id=tenant_id,
        )
        invoice_repo.add(invoice)
        invoice_repo.flush()

        total = Decimal("0")
        for item in data.items:
            latest_price = batch_repo.get_highest_selling_price(item.product_id)
            if latest_price is None:
                raise HTTPException(status_code=400, detail="No batches available")
            effective_price = Decimal(str(item.sale_price)) if item.sale_price is not None else latest_price
            allocations = allocate_batches_svc(batch_repo, item.product_id, item.quantity)
            for batch, qty in allocations:
                batch.remaining_quantity = batch.remaining_quantity - qty
                override_cost = Decimal(str(item.purchase_price)) if item.purchase_price is not None else None
                locked_cost = override_cost if override_cost is not None else batch.purchase_price
                invoice_item = InvoiceItem(
                    invoice_id=invoice.id,
                    batch_id=batch.id,
                    quantity=qty,
                    unit_price=effective_price,
                    purchase_price=locked_cost,
                    sale_price=effective_price,
                )
                invoice_repo.add(invoice_item)
                total += effective_price * qty

        invoice.total_amount = total + data.delivery_fee
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
    new_items = data.get("items")
    if new_items is not None:
        if invoice.invoice_type == INVOICE_TYPE_SALE:
            for old_item in invoice.items:
                b = batch_repo.get_by_id(old_item.batch_id)
                if b:
                    b.remaining_quantity += old_item.quantity
                invoice_repo.delete(old_item)
            invoice_repo.flush()

            total = Decimal("0")
            for item in new_items:
                batch = batch_repo.get_by_id(item["batch_id"])
                if not batch:
                    raise HTTPException(status_code=404, detail=f"Batch {item['batch_id']} not found")
                unit_price = Decimal(str(item["unit_price"]))
                qty = Decimal(str(item["quantity"]))
                if batch.remaining_quantity < qty:
                    raise HTTPException(status_code=400, detail=f"الكمية المطلوبة غير متوفرة في الدفعة #{batch.id}")
                batch.remaining_quantity -= qty
                new_item = InvoiceItem(
                    invoice_id=invoice.id, batch_id=batch.id,
                    quantity=qty, unit_price=unit_price,
                    purchase_price=batch.purchase_price, sale_price=unit_price,
                )
                invoice_repo.add(new_item)
                total += unit_price * qty
            invoice.total_amount = total

        elif invoice.invoice_type == INVOICE_TYPE_PURCHASE:
            old_map = {str(item.batch_id): item for item in invoice.items}
            if len(new_items) != len(invoice.items):
                raise HTTPException(status_code=400, detail=ERR_CANNOT_MODIFY_PURCHASE_COUNT)

            total = Decimal("0")
            for item_data in new_items:
                batch_id = str(item_data.get("batch_id"))
                new_qty = Decimal(str(item_data.get("quantity", 0)))
                new_price = Decimal(str(item_data.get("unit_price", 0)))
                old_item = old_map.get(batch_id)
                if not old_item:
                    raise HTTPException(status_code=400, detail=f"البند (دفعة #{batch_id}) غير موجود في الفاتورة")
                batch = db.execute(select(StockBatch).where(StockBatch.id == int(batch_id))).scalar_one_or_none()
                if not batch:
                    raise HTTPException(status_code=404, detail=f"الدفعة #{batch_id} غير موجودة")
                sold_qty = batch.initial_quantity - batch.remaining_quantity
                if new_qty < sold_qty:
                    raise HTTPException(status_code=400, detail=f"الكمية الجديدة ({new_qty}) أقل من الكمية المباعة فعلاً ({sold_qty})")
                batch.initial_quantity = new_qty
                batch.remaining_quantity = new_qty - sold_qty
                batch.purchase_price = new_price
                old_item.quantity = new_qty
                old_item.unit_price = new_price
                old_item.purchase_price = new_price
                total += new_qty * new_price
            invoice.total_amount = total
        else:
            raise HTTPException(status_code=400, detail=ERR_CANNOT_MODIFY_RETURN)

    delivery_fee = data.get("delivery_fee")
    if delivery_fee is not None:
        new_fee = Decimal(str(delivery_fee))
        old_fee = invoice.delivery_fee or Decimal("0")
        invoice.delivery_fee = new_fee
        invoice.total_amount = (invoice.total_amount or Decimal("0")) - old_fee + new_fee

    footer = data.get("footer_custom_text")
    if footer is not None:
        invoice.footer_custom_text = footer

    invoice_repo.commit()
    # Re-fetch with joinedload so item.batch.product is always available
    invoice = invoice_repo.get_by_id(invoice.id)

    paid = invoice_repo.get_paid_amount(invoice.id)
    balance = invoice.total_amount - paid
    return {
        "id": invoice.id,
        "party_id": invoice.party_id,
        "invoice_type": invoice.invoice_type.value if invoice.invoice_type else None,
        "total_amount": float(invoice.total_amount),
        "delivery_fee": float(invoice.delivery_fee) if invoice.delivery_fee else 0,
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
        "paid_amount": float(paid),
        "balance": float(balance),
        "status": _invoice_status(paid, invoice.total_amount),
        "items": [
            {
                "id": i.id, "batch_id": i.batch_id,
                "product_id": i.batch.product_id if i.batch else None,
                "product_name": i.batch.product.name if i.batch and i.batch.product else None,
                "quantity": float(i.quantity), "unit_price": float(i.unit_price),
                "purchase_price": float(i.purchase_price) if i.purchase_price else None,
                "sale_price": float(i.sale_price) if i.sale_price else None,
            }
            for i in invoice.items
        ],
    }


def delete_invoice_svc(
    invoice_repo: InvoiceRepository, batch_repo: BatchRepository, invoice: Invoice
) -> None:
    batches_to_delete = []
    if invoice.invoice_type in (INVOICE_TYPE_SALE, INVOICE_TYPE_PURCHASE_RETURN):
        for item in invoice.items:
            b = batch_repo.get_by_id(item.batch_id)
            if b:
                b.remaining_quantity += item.quantity
    elif invoice.invoice_type in (INVOICE_TYPE_PURCHASE, INVOICE_TYPE_SALE_RETURN):
        for item in invoice.items:
            b = batch_repo.get_by_id(item.batch_id)
            if b:
                if b.remaining_quantity < b.initial_quantity:
                    raise HTTPException(status_code=400, detail=ERR_CANNOT_DELETE_HAS_STOCK)
                batches_to_delete.append(b)

    for item in invoice.items:
        invoice_repo.delete(item)
    for b in batches_to_delete:
        batch_repo.delete(b)
    for payment in invoice.payments:
        invoice_repo.delete(payment)
    invoice_repo.delete(invoice)
    invoice_repo.commit()


def process_return_svc(
    invoice_repo: InvoiceRepository, batch_repo: BatchRepository,
    orig_invoice: Invoice, data: dict, tenant_id: int
) -> Invoice:
    if orig_invoice.invoice_type not in (INVOICE_TYPE_SALE, INVOICE_TYPE_PURCHASE):
        raise HTTPException(status_code=400, detail=ERR_INVALID_INVOICE_TYPE)

    return_type = (
        INVOICE_TYPE_SALE_RETURN
        if orig_invoice.invoice_type == INVOICE_TYPE_SALE
        else INVOICE_TYPE_PURCHASE_RETURN
    )

    try:
        return_invoice = Invoice(
            tenant_id=tenant_id,
            party_id=orig_invoice.party_id,
            invoice_type=return_type,
            total_amount=Decimal("0"),
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
            if ret_qty > orig_item.quantity:
                raise HTTPException(status_code=400, detail=ERR_RETURN_QTY_EXCEEDS)

            orig_batch = batch_repo.get_by_id(orig_item.batch_id)

            if return_type == INVOICE_TYPE_SALE_RETURN:
                new_batch = StockBatch(
                    tenant_id=tenant_id,
                    product_id=orig_batch.product_id,
                    purchase_price=orig_batch.purchase_price,
                    current_selling_price=orig_batch.current_selling_price,
                    initial_quantity=ret_qty,
                    remaining_quantity=ret_qty,
                )
                batch_repo.add(new_batch)
                batch_repo.flush()
                used_batch_id = new_batch.id
            else:
                if orig_batch.remaining_quantity < ret_qty:
                    raise HTTPException(status_code=400, detail=ERR_INSUFFICIENT_STOCK)
                orig_batch.remaining_quantity -= ret_qty
                used_batch_id = orig_batch.id

            # ── For Purchase Return: use last purchase price from product ──
            if return_type == INVOICE_TYPE_PURCHASE_RETURN:
                product_last_price = (
                    orig_batch.product.last_purchase_price
                    if orig_batch and orig_batch.product and orig_batch.product.last_purchase_price
                    else orig_item.unit_price
                )
                return_unit_price = product_last_price
            else:
                return_unit_price = orig_item.unit_price

            new_ii = InvoiceItem(
                invoice_id=return_invoice.id, batch_id=used_batch_id,
                quantity=ret_qty, unit_price=return_unit_price,
                purchase_price=orig_item.purchase_price, sale_price=orig_item.sale_price,
            )
            invoice_repo.add(new_ii)
            total_return += ret_qty * return_unit_price

        if total_return == Decimal("0"):
            raise HTTPException(status_code=400, detail=ERR_NO_VALID_RETURN_ITEMS)

        return_invoice.total_amount = total_return

        # ── Cap the auto-credit to what was actually paid on the original invoice ──
        # This prevents over-crediting when the original invoice was partially paid or unpaid.
        orig_paid = invoice_repo.get_paid_amount(orig_invoice.id)
        credit_amount = min(total_return, orig_paid)
        if credit_amount > 0:
            credit = Payment(
                party_id=orig_invoice.party_id,
                invoice_id=return_invoice.id,
                amount=credit_amount,
            )
            invoice_repo.add(credit)
        invoice_repo.commit()
    except Exception:
        invoice_repo.rollback()
        raise

    invoice_repo.refresh(return_invoice)
    return return_invoice
