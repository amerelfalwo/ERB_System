from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.domain import Invoice, InvoiceItem, InvoiceType, Party, PartyType, Payment, Product, StockBatch, User
from app.schemas.party import SupplierCreate, SupplierUpdate, PartyOut
from app.services.payments import get_party_balance, get_parties_balances
from app.core.cache import invalidate_tenant_cache_sync

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.post("", response_model=PartyOut)
def create_supplier(
    data: SupplierCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = Party(
        name=data.name,
        party_type=PartyType.SUPPLIER,
        phone=data.phone,
        address=data.address,
        initial_balance=data.initial_balance or Decimal("0"),
        tenant_id=current_user.tenant_id,
    )
    db.add(party)
    db.commit()
    db.refresh(party)
    party.calculated_balance = party.initial_balance
    return party


@router.get("", response_model=list[PartyOut])
def list_suppliers(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    parties = db.execute(
        select(Party).where(
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.SUPPLIER,
        ).offset(skip).limit(limit)
    ).scalars().all()
    if parties:
        party_ids = [p.id for p in parties]
        balances = get_parties_balances(db, party_ids, current_user.tenant_id)
        for p in parties:
            p.calculated_balance = balances.get(p.id, Decimal("0"))
    return parties


@router.get("/select")
def list_suppliers_select(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.execute(
        select(Party.id, Party.name).where(
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.SUPPLIER,
        )
    ).all()
    return [{"id": r.id, "name": r.name} for r in rows]


@router.put("/{supplier_id}", response_model=PartyOut)
def update_supplier(
    supplier_id: int,
    data: SupplierUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == supplier_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.SUPPLIER
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Supplier not found")

    if data.name is not None:
        party.name = data.name
    if data.phone is not None:
        party.phone = data.phone
    if data.address is not None:
        party.address = data.address
    if data.initial_balance is not None:
        party.initial_balance = data.initial_balance

    db.commit()
    db.refresh(party)
    party.calculated_balance = get_party_balance(db, supplier_id, current_user.tenant_id)
    return party


@router.get("/{supplier_id}/balance")
def supplier_balance(
    supplier_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == supplier_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.SUPPLIER
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Supplier not found")
    balance = get_party_balance(db, supplier_id, current_user.tenant_id)
    return {"supplier_id": supplier_id, "balance": balance}


@router.post("/{supplier_id}/payments")
def create_supplier_payment(
    supplier_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == supplier_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.SUPPLIER
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Supplier not found")

    amount_paid = Decimal(str(data.get("amount_paid", 0)))
    if amount_paid == 0:
        raise HTTPException(status_code=400, detail="Invalid payment amount")

    from app.services.payments import create_payment
    from app.schemas.payment import PaymentCreate
    
    try:
        create_payment(
            db=db,
            data=PaymentCreate(party_id=party.id, amount=amount_paid),
            tenant_id=current_user.tenant_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return supplier_summary(supplier_id, db, current_user)


@router.get("/{supplier_id}/summary")
def supplier_summary(
    supplier_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == supplier_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.SUPPLIER
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Supplier not found")

    purchase_type = InvoiceType.PURCHASE
    return_type = InvoiceType.PURCHASE_RETURN

    initial = Decimal(str(party.initial_balance or 0))

    total_purchases = Decimal(str(db.execute(
        select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.party_id == supplier_id,
            Invoice.invoice_type == purchase_type,
            Invoice.tenant_id == current_user.tenant_id,
        )
    ).scalar_one()))

    total_returns = Decimal(str(db.execute(
        select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.party_id == supplier_id,
            Invoice.invoice_type == return_type,
            Invoice.tenant_id == current_user.tenant_id,
        )
    ).scalar_one()))

    total_paid = Decimal(str(db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.party_id == supplier_id,
        )
    ).scalar_one()))

    balance = initial + total_purchases - total_returns - total_paid

    invoices = db.execute(
        select(Invoice).options(
            selectinload(Invoice.items).joinedload(InvoiceItem.batch).joinedload(StockBatch.product)
        ).where(
            Invoice.party_id == supplier_id,
            Invoice.tenant_id == current_user.tenant_id,
        ).order_by(Invoice.created_at.desc())
    ).unique().scalars().all()

    invoice_ids = [inv.id for inv in invoices]
    
    payments_by_invoice = {}
    if invoice_ids:
        payment_sums = db.execute(
            select(Payment.invoice_id, func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.invoice_id.in_(invoice_ids))
            .group_by(Payment.invoice_id)
        ).all()
        for inv_id, amt in payment_sums:
            payments_by_invoice[inv_id] = amt

    item_ids = []
    for inv in invoices:
        for item in inv.items:
            item_ids.append(item.id)
            
    returned_qty_map = {}
    if item_ids:
        rows = db.execute(
            select(InvoiceItem.original_invoice_item_id, func.sum(InvoiceItem.quantity))
            .where(InvoiceItem.original_invoice_item_id.in_(item_ids))
            .group_by(InvoiceItem.original_invoice_item_id)
        ).all()
        returned_qty_map = {orig_id: qty for orig_id, qty in rows if orig_id}

    invoice_list = []
    for inv in invoices:
        inv_paid = payments_by_invoice.get(inv.id, Decimal("0"))
        total_amt = inv.total_amount if inv.total_amount is not None else Decimal("0")
        inv_balance = total_amt - inv_paid
        if inv_balance <= 0:
            status = "paid"
        elif inv_paid > 0:
            status = "partial"
        else:
            status = "unpaid"

        inv_profit = Decimal("0")

        invoice_list.append({
            "id": inv.id,
            "invoice_type": inv.invoice_type.value if inv.invoice_type else None,
            "total_amount": float(total_amt),
            "paid_amount": float(inv_paid),
            "balance": float(inv_balance),
            "delivery_fee": float(inv.delivery_fee or 0),
            "status": status,
            "invoice_profit": float(inv_profit),
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "items": [
                {
                    "id": item.id,
                    "batch_id": item.batch_id,
                    "product_id": item.batch.product_id if item.batch else None,
                    "quantity": float(item.quantity or 0),
                    "unit_price": float(item.unit_price or 0),
                    "purchase_price": float(item.purchase_price) if item.purchase_price is not None else None,
                    "sell_price": float(item.sell_price) if item.sell_price is not None else None,
                    "product_name": item.batch.product.name if item.batch and item.batch.product else None,
                    "already_returned_qty": float(returned_qty_map.get(item.id, Decimal("0"))),
                }
                for item in inv.items
            ],
        })

    product_map = {}
    for inv in invoices:
        if inv.invoice_type == InvoiceType.PURCHASE:
            for item in inv.items:
                if item.batch and item.batch.product_id:
                    pid = item.batch.product_id
                    if pid not in product_map:
                        product_map[pid] = {
                            "id": pid,
                            "name": item.batch.product.name if item.batch.product else f"Product {pid}",
                            "remaining_stock": Decimal("0"),
                            "last_purchase_price": item.batch.product.last_purchase_price if item.batch.product else item.purchase_price
                        }
                    product_map[pid]["remaining_stock"] += (item.batch.remaining_quantity if item.batch.remaining_quantity is not None else Decimal("0"))

    product_ids = list(product_map.keys())
    stock_map = {}
    if product_ids:
        stock_sums = db.execute(
            select(StockBatch.product_id, func.coalesce(func.sum(StockBatch.remaining_quantity), 0))
            .where(
                StockBatch.product_id.in_(product_ids), 
                StockBatch.tenant_id == current_user.tenant_id
            )
            .group_by(StockBatch.product_id)
        ).all()
        stock_map = {pid: qty for pid, qty in stock_sums}

    product_summary = []
    for pid, data in product_map.items():
        if data["remaining_stock"] > 0:
            product_summary.append({
                "id": data["id"],
                "name": data["name"],
                "supplier_stock": float(data["remaining_stock"]),
                "remaining_stock": float(stock_map.get(pid, 0)),
                "last_purchase_price": float(data["last_purchase_price"] or 0),
            })

    total_profit = Decimal("0")

    payments = db.execute(
        select(Payment).where(Payment.party_id == supplier_id).order_by(Payment.payment_date.desc())
    ).scalars().all()

    payment_list = [
        {
            "id": p.id,
            "invoice_id": p.invoice_id,
            "amount": float(p.amount),
            "payment_date": p.payment_date.isoformat() if p.payment_date else None,
        }
        for p in payments
    ]

    return {
        "supplier": {
            "id": party.id,
            "name": party.name,
            "party_type": party.party_type.value if party.party_type else None,
            "phone": party.phone,
            "address": party.address,
            "initial_balance": float(initial),
        },
        "financials": {
            "initial_balance": float(initial),
            "total_purchases": float(total_purchases),
            "total_returns": float(total_returns),
            "total_paid": float(total_paid),
            "balance": float(balance),
            "total_profit": float(total_profit),
        },
        "invoices": invoice_list,
        "products": product_summary,
        "payments": payment_list,
    }


@router.post("/{supplier_id}/stock-return")
def supplier_stock_return(
    supplier_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == supplier_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.SUPPLIER
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Supplier not found")

    items = data.get("items", [])
    if not items:
        raise HTTPException(status_code=400, detail="No items provided for return")

    try:
        total_return = Decimal("0")
        invoice_items_to_add = []

        for ret in items:
            product_id = ret.get("product_id")
            ret_qty = Decimal(str(ret.get("quantity", 0)))
            unit_price = Decimal(str(ret.get("unit_price", 0)))

            if ret_qty <= 0 or unit_price <= 0:
                continue

            supplier_batches = db.execute(
                select(StockBatch)
                .where(
                    StockBatch.party_id == supplier_id,
                    StockBatch.product_id == product_id,
                    StockBatch.tenant_id == current_user.tenant_id,
                    StockBatch.remaining_quantity > 0,
                ).order_by(StockBatch.created_at.asc())
            ).scalars().all()

            # Backward compatibility: fallback to legacy join if older batches lack party_id
            if not supplier_batches:
                supplier_batches = db.execute(
                    select(StockBatch)
                    .join(InvoiceItem, StockBatch.id == InvoiceItem.batch_id)
                    .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                    .where(
                        Invoice.party_id == supplier_id,
                        Invoice.invoice_type == InvoiceType.PURCHASE,
                        StockBatch.product_id == product_id,
                        StockBatch.tenant_id == current_user.tenant_id,
                        StockBatch.remaining_quantity > 0,
                    ).order_by(StockBatch.created_at.asc())
                ).scalars().all()

            current_stock = sum(b.remaining_quantity for b in supplier_batches)

            if Decimal(str(current_stock)) < ret_qty:
                product_name = db.execute(
                    select(Product.name).where(Product.id == product_id, Product.tenant_id == current_user.tenant_id)
                ).scalar_one_or_none() or f"Product #{product_id}"
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient stock from this supplier for '{product_name}'. Available: {current_stock}, Requested: {ret_qty}",
                )

            remaining_to_deduct = ret_qty
            used_batch_id = None
            for batch in supplier_batches:
                if remaining_to_deduct <= 0:
                    break
                deduct = min(batch.remaining_quantity, remaining_to_deduct)
                batch.remaining_quantity -= deduct
                remaining_to_deduct -= deduct
                if used_batch_id is None:
                    used_batch_id = batch.id

            if used_batch_id is None:
                raise HTTPException(status_code=400, detail="No stock batch found from this supplier")

            line_total = ret_qty * unit_price
            total_return += line_total
            invoice_items_to_add.append({
                "batch_id": used_batch_id,
                "quantity": ret_qty,
                "unit_price": unit_price,
            })

        if total_return == 0:
            raise HTTPException(status_code=400, detail="No valid return items")

        return_invoice = Invoice(
            tenant_id=current_user.tenant_id,
            party_id=supplier_id,
            invoice_type=InvoiceType.PURCHASE_RETURN,
            total_amount=total_return,
        )
        db.add(return_invoice)
        db.flush()

        for ii_data in invoice_items_to_add:
            ii = InvoiceItem(
                invoice_id=return_invoice.id,
                batch_id=ii_data["batch_id"],
                quantity=ii_data["quantity"],
                unit_price=ii_data["unit_price"],
            )
            db.add(ii)

        # Auto-create a negative payment to offset the return amount
        total_paid_on_party = db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.party_id == supplier_id,
            )
        ).scalar_one()
        total_paid_on_party = Decimal(str(total_paid_on_party))
        if total_paid_on_party > Decimal("0"):
            offset_amount = min(total_return, total_paid_on_party)
            db.add(Payment(
                party_id=supplier_id,
                invoice_id=return_invoice.id,
                amount=-offset_amount,
            ))

        db.commit()
        invalidate_tenant_cache_sync(current_user.tenant_id, ["dashboard", "reports:profit", "reports:net-profit", "reports:inventory", "reports:party-profits", "parties"])
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return supplier_summary(supplier_id, db, current_user)


@router.delete("/{supplier_id}")
def delete_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == supplier_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.SUPPLIER
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Supplier not found")
    invoices_count = db.execute(
        select(func.count(Invoice.id)).where(
            Invoice.party_id == supplier_id,
            Invoice.tenant_id == current_user.tenant_id,
        )
    ).scalar_one()
    payments_count = db.execute(
        select(func.count(Payment.id)).where(Payment.party_id == supplier_id)
    ).scalar_one()
    if invoices_count > 0 or payments_count > 0:
        raise HTTPException(status_code=400, detail="لا يمكن حذف المورد لوجود فواتير او دفعات")
    db.delete(party)
    db.commit()
    return {"status": "deleted"}


@router.patch("/{supplier_id}/payments/{payment_id}")
def update_supplier_payment(
    supplier_id: int,
    payment_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == supplier_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.SUPPLIER
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Supplier not found")

    payment = db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.party_id == supplier_id)
    ).scalar_one_or_none()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    new_amount = Decimal(str(data.get("amount", payment.amount)))
    if new_amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid payment amount")

    payment.amount = new_amount
    if "payment_date" in data:
        payment.payment_date = data["payment_date"]

    db.commit()
    db.refresh(party)
    return supplier_summary(supplier_id, db, current_user)


@router.delete("/{supplier_id}/payments/{payment_id}")
def delete_supplier_payment(
    supplier_id: int,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == supplier_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.SUPPLIER
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Supplier not found")

    payment = db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.party_id == supplier_id)
    ).scalar_one_or_none()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    db.delete(payment)
    db.commit()
    db.refresh(party)
    return supplier_summary(supplier_id, db, current_user)
