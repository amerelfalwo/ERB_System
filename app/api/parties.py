from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.domain import Invoice, InvoiceItem, InvoiceType, Party, PartyType, Payment, Product, StockBatch, User
from app.repositories.base import PartyRepository
from app.schemas.party import PartyCreate, PartyOut, PartyUpdate
from app.services.payments import get_party_balance, get_parties_balances

from app.core.cache import get_cache, set_cache, invalidate_tenant_cache

router = APIRouter(prefix="/parties", tags=["parties"])


@router.post("", response_model=PartyOut)
async def create_party(
    data: PartyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = Party(
        name=data.name,
        party_type=data.party_type,
        phone=data.phone,
        address=data.address,
        initial_balance=data.initial_balance or Decimal("0"),
        tenant_id=current_user.tenant_id,
    )
    db.add(party)
    db.commit()
    db.refresh(party)
    party.calculated_balance = party.initial_balance

    await invalidate_tenant_cache(current_user.tenant_id, ["parties", "reports:party-profits", "dashboard"])
    return party


@router.get("", response_model=list[PartyOut])
async def list_parties(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"parties:list:all:{skip}:{limit}"
    cached = await get_cache(current_user.tenant_id, cache_key)
    if cached is not None:
        return cached

    party_repo = PartyRepository(db, current_user.tenant_id)
    parties = party_repo.list(skip=skip, limit=limit)
    if parties:
        party_ids = [p.id for p in parties]
        balances = get_parties_balances(db, party_ids, current_user.tenant_id)
        for p in parties:
            p.calculated_balance = balances.get(p.id, Decimal("0"))

    res_dict = [PartyOut.model_validate(p).model_dump(mode="json") for p in parties] if parties else []
    await set_cache(current_user.tenant_id, cache_key, res_dict, ttl=300)
    return parties



@router.get("/select")
def list_parties_select(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party_repo = PartyRepository(db, current_user.tenant_id)
    return party_repo.get_all_for_select()


@router.get("/suppliers", response_model=list[PartyOut])
async def list_suppliers(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"parties:list:suppliers:{skip}:{limit}"
    cached = await get_cache(current_user.tenant_id, cache_key)
    if cached is not None:
        return cached

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
            
    res_dict = [PartyOut.model_validate(p).model_dump(mode="json") for p in parties] if parties else []
    await set_cache(current_user.tenant_id, cache_key, res_dict, ttl=300)
    return parties


@router.post("/suppliers", response_model=PartyOut)
async def create_supplier(
    data: PartyCreate,
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
    await invalidate_tenant_cache(current_user.tenant_id, ["parties", "reports:party-profits", "dashboard"])
    return party


@router.get("/suppliers/select")
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


@router.get("/customers", response_model=list[PartyOut])
async def list_customers(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"parties:list:customers:{skip}:{limit}"
    cached = await get_cache(current_user.tenant_id, cache_key)
    if cached is not None:
        return cached

    parties = db.execute(
        select(Party).where(
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.CLIENT,
        ).offset(skip).limit(limit)
    ).scalars().all()
    if parties:
        party_ids = [p.id for p in parties]
        balances = get_parties_balances(db, party_ids, current_user.tenant_id)
        for p in parties:
            p.calculated_balance = balances.get(p.id, Decimal("0"))

    res_dict = [PartyOut.model_validate(p).model_dump(mode="json") for p in parties] if parties else []
    await set_cache(current_user.tenant_id, cache_key, res_dict, ttl=300)
    return parties


@router.post("/customers", response_model=PartyOut)
async def create_customer(
    data: PartyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = Party(
        name=data.name,
        party_type=PartyType.CLIENT,
        phone=data.phone,
        address=data.address,
        initial_balance=data.initial_balance or Decimal("0"),
        tenant_id=current_user.tenant_id,
    )
    db.add(party)
    db.commit()
    db.refresh(party)
    party.calculated_balance = party.initial_balance
    await invalidate_tenant_cache(current_user.tenant_id, ["parties", "reports:party-profits", "dashboard"])
    return party


@router.get("/customers/select")
def list_customers_select(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.execute(
        select(Party.id, Party.name).where(
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.CLIENT,
        )
    ).all()
    return [{"id": r.id, "name": r.name} for r in rows]


@router.put("/{party_id}", response_model=PartyOut)
async def update_party(
    party_id: int,
    data: PartyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(Party.id == party_id, Party.tenant_id == current_user.tenant_id)
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")

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
    party.calculated_balance = get_party_balance(db, party_id, current_user.tenant_id)
    await invalidate_tenant_cache(current_user.tenant_id, ["parties", "reports:party-profits", "dashboard"])
    return party



@router.get("/{party_id}/balance")
def party_balance(
    party_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(Party.id == party_id, Party.tenant_id == current_user.tenant_id)
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")
    balance = get_party_balance(db, party_id, current_user.tenant_id)
    return {"party_id": party_id, "balance": balance}


@router.post("/{party_id}/payments")
async def create_party_payment(
    party_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(Party.id == party_id, Party.tenant_id == current_user.tenant_id)
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")

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

    await invalidate_tenant_cache(current_user.tenant_id, ["parties", "reports:party-profits", "dashboard"])
    return party_summary(party_id, db, current_user)


@router.get("/{party_id}/summary")
def party_summary(
    party_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(Party.id == party_id, Party.tenant_id == current_user.tenant_id)
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")

    if party.party_type == PartyType.CLIENT:
        purchase_type = InvoiceType.SELL
        return_type = InvoiceType.SELL_RETURN
    else:
        purchase_type = InvoiceType.PURCHASE
        return_type = InvoiceType.PURCHASE_RETURN

    initial = Decimal(str(party.initial_balance or 0))

    invoices = db.execute(
        select(Invoice).options(
            selectinload(Invoice.items).joinedload(InvoiceItem.batch).joinedload(StockBatch.product)
        ).where(
            Invoice.party_id == party_id,
            Invoice.tenant_id == current_user.tenant_id,
        ).order_by(Invoice.created_at.desc())
    ).unique().scalars().all()

    total_purchases = Decimal("0")
    total_returns = Decimal("0")
    for inv in invoices:
        if inv.invoice_type == purchase_type:
            total_purchases += inv.total_amount
        elif inv.invoice_type == return_type:
            total_returns += inv.total_amount

    payments = db.execute(
        select(Payment).where(Payment.party_id == party_id).order_by(Payment.payment_date.desc())
    ).scalars().all()

    total_paid = Decimal("0")
    payments_by_invoice = {}
    payment_list = []
    for p in payments:
        total_paid += p.amount
        if p.invoice_id:
            payments_by_invoice[p.invoice_id] = payments_by_invoice.get(p.invoice_id, Decimal("0")) + p.amount
        payment_list.append({
            "id": p.id,
            "invoice_id": p.invoice_id,
            "amount": float(p.amount),
            "payment_date": p.payment_date.isoformat() if p.payment_date else None,
        })

    balance = initial + total_purchases - total_returns - total_paid

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
        inv_balance = inv.total_amount - inv_paid
        if inv_balance <= 0:
            status = "paid"
        elif inv_paid > 0:
            status = "partial"
        else:
            status = "unpaid"

        inv_profit = Decimal("0")
        if inv.invoice_type == InvoiceType.SELL:
            for item in inv.items:
                cost = item.batch.purchase_price if item.batch and item.batch.purchase_price is not None else (
                    item.purchase_price if item.purchase_price is not None else Decimal("0")
                )
                sale = item.sell_price if item.sell_price is not None else item.unit_price
                qty = item.quantity if item.quantity is not None else Decimal("0")
                returned_qty = returned_qty_map.get(item.id, Decimal("0"))
                effective_qty = max(Decimal("0"), qty - returned_qty)
                inv_profit += (sale - cost) * effective_qty

        invoice_list.append({
            "id": inv.id,
            "invoice_type": inv.invoice_type.value if inv.invoice_type else None,
            "total_amount": float(inv.total_amount),
            "paid_amount": float(inv_paid),
            "balance": float(inv_balance),
            "status": status,
            "invoice_profit": float(inv_profit),
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "items": [
                {
                    "id": item.id,
                    "batch_id": item.batch_id,
                    "product_id": item.batch.product_id if item.batch else None,
                    "quantity": float(item.quantity),
                    "unit_price": float(item.unit_price),
                    "purchase_price": float(item.purchase_price) if item.purchase_price else None,
                    "sell_price": float(item.sell_price) if item.sell_price else None,
                    "product_name": item.batch.product.name if item.batch and item.batch.product else None,
                }
                for item in inv.items
            ],
        })

    product_ids = set()
    last_purchase_prices = {}
    for inv in invoices:
        for item in inv.items:
            if item.batch and item.batch.product_id:
                pid = item.batch.product_id
                product_ids.add(pid)
                if inv.invoice_type == InvoiceType.PURCHASE and pid not in last_purchase_prices:
                    last_purchase_prices[pid] = item.unit_price

    product_summary = []
    if product_ids:
        from sqlalchemy import case
        products = db.execute(
            select(Product).where(
                Product.id.in_(product_ids), 
                Product.tenant_id == current_user.tenant_id
            )
        ).scalars().all()
        
        stock_stats = db.execute(
            select(
                StockBatch.product_id,
                func.coalesce(func.sum(StockBatch.remaining_quantity), 0),
                func.coalesce(func.sum(case((StockBatch.party_id == party_id, StockBatch.remaining_quantity), else_=0)), 0)
            )
            .where(
                StockBatch.product_id.in_(product_ids), 
                StockBatch.tenant_id == current_user.tenant_id
            )
            .group_by(StockBatch.product_id)
        ).all()
        
        stock_map = {pid: qty for pid, qty, _ in stock_stats}
        supplier_stock_map = {pid: sqty for pid, _, sqty in stock_stats}
        
        for p in products:
            product_summary.append({
                "id": p.id,
                "name": p.name,
                "remaining_stock": float(stock_map.get(p.id, 0)),
                "supplier_stock": float(supplier_stock_map.get(p.id, 0)),
                "last_purchase_price": float(last_purchase_prices.get(p.id, 0)),
            })

    total_profit = sum(inv.get("invoice_profit", 0) for inv in invoice_list)

    return {
        "party": {
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
            "total_profit": total_profit,
        },
        "invoices": invoice_list,
        "products": product_summary,
        "payments": payment_list,
    }


@router.post("/{party_id}/stock-return")
async def stock_return(
    party_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(Party.id == party_id, Party.tenant_id == current_user.tenant_id)
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")

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

            current_stock = db.execute(
                select(func.coalesce(func.sum(StockBatch.remaining_quantity), 0)).where(
                    StockBatch.product_id == product_id,
                    StockBatch.tenant_id == current_user.tenant_id,
                    StockBatch.party_id == party_id
                )
            ).scalar_one()

            if Decimal(str(current_stock)) < ret_qty:
                product_name = db.execute(
                    select(Product.name).where(Product.id == product_id, Product.tenant_id == current_user.tenant_id)
                ).scalar_one_or_none() or f"Product #{product_id}"
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient stock from this supplier for '{product_name}'. Available: {current_stock}, Requested: {ret_qty}",
                )

            batches = db.execute(
                select(StockBatch).where(
                    StockBatch.product_id == product_id,
                    StockBatch.tenant_id == current_user.tenant_id,
                    StockBatch.party_id == party_id,
                    StockBatch.remaining_quantity > 0,
                ).order_by(StockBatch.created_at.desc())
            ).scalars().all()

            remaining_to_deduct = ret_qty
            used_batch_id = None
            for batch in batches:
                if remaining_to_deduct <= 0:
                    break
                deduct = min(batch.remaining_quantity, remaining_to_deduct)
                batch.remaining_quantity -= deduct
                remaining_to_deduct -= deduct
                if used_batch_id is None:
                    used_batch_id = batch.id

            if used_batch_id is None:
                raise HTTPException(status_code=400, detail="No stock batch found")

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
            party_id=party_id,
            invoice_type=InvoiceType.PURCHASE_RETURN if party.party_type == PartyType.SUPPLIER else InvoiceType.SELL_RETURN,
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

        db.commit()
        await invalidate_tenant_cache(current_user.tenant_id, ["dashboard", "reports:profit", "reports:inventory", "reports:party-profits", "parties"])
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return party_summary(party_id, db, current_user)


@router.delete("/{party_id}")
async def delete_party(
    party_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(Party.id == party_id, Party.tenant_id == current_user.tenant_id)
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")
    invoices_count = db.execute(
        select(func.count(Invoice.id)).where(
            Invoice.party_id == party_id,
            Invoice.tenant_id == current_user.tenant_id,
        )
    ).scalar_one()
    payments_count = db.execute(
        select(func.count(Payment.id)).where(Payment.party_id == party_id)
    ).scalar_one()
    if invoices_count > 0 or payments_count > 0:
        raise HTTPException(status_code=400, detail="لا يمكن حذف الطرف لوجود فواتير او دفعات")
    db.delete(party)
    db.commit()
    await invalidate_tenant_cache(current_user.tenant_id, ["parties", "reports:party-profits", "dashboard"])
    return {"status": "deleted"}


@router.patch("/{party_id}/payments/{payment_id}")
async def update_party_payment(
    party_id: int,
    payment_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(Party.id == party_id, Party.tenant_id == current_user.tenant_id)
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")

    payment = db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.party_id == party_id)
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
    await invalidate_tenant_cache(current_user.tenant_id, ["parties", "reports:party-profits", "dashboard"])
    return party_summary(party_id, db, current_user)


@router.delete("/{party_id}/payments/{payment_id}")
async def delete_party_payment(
    party_id: int,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(Party.id == party_id, Party.tenant_id == current_user.tenant_id)
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")

    payment = db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.party_id == party_id)
    ).scalar_one_or_none()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    db.delete(payment)
    db.commit()
    db.refresh(party)
    await invalidate_tenant_cache(current_user.tenant_id, ["parties", "reports:party-profits", "dashboard"])
    return party_summary(party_id, db, current_user)
