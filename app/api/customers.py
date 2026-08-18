from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.domain import Invoice, InvoiceItem, InvoiceType, Party, PartyType, Payment, Product, StockBatch, User
from app.schemas.party import CustomerCreate, CustomerUpdate, PartyOut
from app.services.payments import get_party_balance, get_parties_balances
from app.core.cache import invalidate_tenant_cache_sync

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post("", response_model=PartyOut)
def create_customer(
    data: CustomerCreate,
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
    return party


@router.get("", response_model=list[PartyOut])
def list_customers(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    parties = db.execute(
        select(Party).where(
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.CLIENT,
        ).offset(skip).limit(limit)
    ).scalars().all()
    if parties:
        party_ids = [p.id for p in parties]
        balances = get_parties_balances(db, party_ids, current_user.tenant_id)

        sell_invoices = db.execute(
            select(Invoice).options(
                selectinload(Invoice.items).joinedload(InvoiceItem.batch)
            ).where(
                Invoice.party_id.in_(party_ids),
                Invoice.invoice_type == InvoiceType.SELL,
                Invoice.tenant_id == current_user.tenant_id
            )
        ).scalars().unique().all()
        
        item_ids = [item.id for inv in sell_invoices for item in inv.items]
        returned_qty_map = {}
        if item_ids:
            rows = db.execute(
                select(InvoiceItem.original_invoice_item_id, func.sum(InvoiceItem.quantity))
                .where(InvoiceItem.original_invoice_item_id.in_(item_ids))
                .group_by(InvoiceItem.original_invoice_item_id)
            ).all()
            returned_qty_map = {orig_id: qty for orig_id, qty in rows if orig_id}

        profits_map = {p.id: Decimal("0") for p in parties}
        for inv in sell_invoices:
            inv_profit = Decimal("0")
            for item in inv.items:
                cost = item.batch.purchase_price if item.batch and item.batch.purchase_price is not None else (
                    item.purchase_price if item.purchase_price is not None else Decimal("0")
                )
                sale = item.sell_price if item.sell_price is not None else (item.unit_price if item.unit_price is not None else Decimal("0"))
                qty = item.quantity if item.quantity is not None else Decimal("0")
                returned_qty = returned_qty_map.get(item.id, Decimal("0"))
                effective_qty = max(Decimal("0"), qty - returned_qty)
                inv_profit += (sale - cost) * effective_qty
            profits_map[inv.party_id] += inv_profit

        for p in parties:
            p.calculated_balance = balances.get(p.id, Decimal("0"))
            p.total_profit = profits_map.get(p.id, Decimal("0"))
            if p.calculated_balance <= 0:
                p.payment_status = "paid"
            else:
                p.payment_status = "unpaid"
    return parties


@router.get("/select")
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


@router.put("/{customer_id}", response_model=PartyOut)
def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == customer_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.CLIENT
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Customer not found")

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
    party.calculated_balance = get_party_balance(db, customer_id, current_user.tenant_id)
    return party


@router.get("/{customer_id}/balance")
def customer_balance(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == customer_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.CLIENT
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Customer not found")
    balance = get_party_balance(db, customer_id, current_user.tenant_id)
    return {"customer_id": customer_id, "balance": balance}


@router.post("/{customer_id}/payments")
def create_customer_payment(
    customer_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == customer_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.CLIENT
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Customer not found")

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

    return customer_summary(customer_id, db, current_user)


@router.get("/{customer_id}/summary")
def customer_summary(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == customer_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.CLIENT
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Customer not found")

    purchase_type = InvoiceType.SELL
    return_type = InvoiceType.SELL_RETURN

    initial = Decimal(str(party.initial_balance or 0))

    total_purchases = Decimal(str(db.execute(
        select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.party_id == customer_id,
            Invoice.invoice_type == purchase_type,
            Invoice.tenant_id == current_user.tenant_id,
        )
    ).scalar_one()))

    total_returns = Decimal(str(db.execute(
        select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.party_id == customer_id,
            Invoice.invoice_type == return_type,
            Invoice.tenant_id == current_user.tenant_id,
        )
    ).scalar_one()))

    total_paid = Decimal(str(db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.party_id == customer_id,
        )
    ).scalar_one()))

    balance = initial + total_purchases - total_returns - total_paid

    invoices = db.execute(
        select(Invoice).options(
            selectinload(Invoice.items).joinedload(InvoiceItem.batch).joinedload(StockBatch.product)
        ).where(
            Invoice.party_id == customer_id,
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
        if inv.invoice_type == InvoiceType.SELL:
            for item in inv.items:
                cost = item.batch.purchase_price if item.batch and item.batch.purchase_price is not None else (
                    item.purchase_price if item.purchase_price is not None else Decimal("0")
                )
                sale = item.sell_price if item.sell_price is not None else (item.unit_price if item.unit_price is not None else Decimal("0"))
                qty = item.quantity if item.quantity is not None else Decimal("0")
                returned_qty = returned_qty_map.get(item.id, Decimal("0"))
                effective_qty = max(Decimal("0"), qty - returned_qty)
                inv_profit += (sale - cost) * effective_qty

        invoice_list.append({
            "id": inv.id,
            "invoice_type": inv.invoice_type.value if inv.invoice_type else None,
            "total_amount": float(total_amt),
            "paid_amount": float(inv_paid),
            "balance": float(inv_balance),
            "delivery_fee": float(inv.delivery_fee or 0),
            "discount_amount": float(inv.discount_amount or inv.total_discount or 0),
            "total_discount": float(inv.total_discount or inv.discount_amount or 0),
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

    product_ids = set()
    for inv in invoices:
        for item in inv.items:
            if item.batch and item.batch.product_id:
                product_ids.add(item.batch.product_id)

    product_summary = []
    if product_ids:
        products = db.execute(
            select(Product).where(
                Product.id.in_(product_ids), 
                Product.tenant_id == current_user.tenant_id
            )
        ).scalars().all()
        
        stock_sums = db.execute(
            select(StockBatch.product_id, func.coalesce(func.sum(StockBatch.remaining_quantity), 0))
            .where(
                StockBatch.product_id.in_(product_ids), 
                StockBatch.tenant_id == current_user.tenant_id
            )
            .group_by(StockBatch.product_id)
        ).all()
        
        stock_map = {pid: qty for pid, qty in stock_sums}
        
        for p in products:
            product_summary.append({
                "id": p.id,
                "name": p.name,
                "remaining_stock": float(stock_map.get(p.id, 0)),
            })

    total_profit = sum(inv.get("invoice_profit", 0) for inv in invoice_list)

    payments = db.execute(
        select(Payment).where(Payment.party_id == customer_id).order_by(Payment.payment_date.desc())
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
        "customer": {
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


@router.post("/{customer_id}/stock-return")
def customer_stock_return(
    customer_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == customer_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.CLIENT
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Customer not found")

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
                )
            ).scalar_one()

            if Decimal(str(current_stock)) < ret_qty:
                product_name = db.execute(
                    select(Product.name).where(Product.id == product_id, Product.tenant_id == current_user.tenant_id)
                ).scalar_one_or_none() or f"Product #{product_id}"
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient stock for '{product_name}'. Available: {current_stock}, Requested: {ret_qty}",
                )

            batches = db.execute(
                select(StockBatch).where(
                    StockBatch.product_id == product_id,
                    StockBatch.tenant_id == current_user.tenant_id,
                    StockBatch.remaining_quantity > 0,
                ).order_by(StockBatch.created_at.asc())
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
            party_id=customer_id,
            invoice_type=InvoiceType.SELL_RETURN,
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
        invalidate_tenant_cache_sync(current_user.tenant_id, ["products", "dashboard", "reports:profit", "reports:net-profit", "reports:inventory", "reports:party-profits", "parties"])
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return customer_summary(customer_id, db, current_user)


@router.delete("/{customer_id}")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == customer_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.CLIENT
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Customer not found")
    invoices_count = db.execute(
        select(func.count(Invoice.id)).where(
            Invoice.party_id == customer_id,
            Invoice.tenant_id == current_user.tenant_id,
        )
    ).scalar_one()
    payments_count = db.execute(
        select(func.count(Payment.id)).where(Payment.party_id == customer_id)
    ).scalar_one()
    if invoices_count > 0 or payments_count > 0:
        raise HTTPException(status_code=400, detail="لا يمكن حذف العميل لوجود فواتير او دفعات")
    db.delete(party)
    db.commit()
    return {"status": "deleted"}


@router.patch("/{customer_id}/payments/{payment_id}")
def update_customer_payment(
    customer_id: int,
    payment_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == customer_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.CLIENT
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Customer not found")

    payment = db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.party_id == customer_id)
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
    return customer_summary(customer_id, db, current_user)


@router.delete("/{customer_id}/payments/{payment_id}")
def delete_customer_payment(
    customer_id: int,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = db.execute(
        select(Party).where(
            Party.id == customer_id, 
            Party.tenant_id == current_user.tenant_id,
            Party.party_type == PartyType.CLIENT
        )
    ).scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Customer not found")

    payment = db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.party_id == customer_id)
    ).scalar_one_or_none()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    db.delete(payment)
    db.commit()
    db.refresh(party)
    return customer_summary(customer_id, db, current_user)
