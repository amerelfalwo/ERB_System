from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.domain import Invoice, InvoiceItem, InvoiceType, Party, PartyType, Payment, Product, StockBatch, User
from app.schemas.party import PartyCreate, PartyOut
from app.services.payments import get_party_balance

router = APIRouter(prefix="/parties", tags=["parties"])


@router.post("", response_model=PartyOut)
def create_party(
    data: PartyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    party = Party(name=data.name, party_type=data.party_type, phone=data.phone, address=data.address, tenant_id=current_user.tenant_id)
    db.add(party)
    db.commit()
    db.refresh(party)
    return party


@router.get("", response_model=list[PartyOut])
def list_parties(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.execute(select(Party).where(Party.tenant_id == current_user.tenant_id)).scalars().all()


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
        invoice_type = InvoiceType.SALE
    else:
        invoice_type = InvoiceType.PURCHASE

    total_invoiced = db.execute(
        select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.party_id == party_id,
            Invoice.invoice_type == invoice_type,
            Invoice.tenant_id == current_user.tenant_id,
        )
    ).scalar_one()

    total_paid = db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.party_id == party_id,
        )
    ).scalar_one()

    balance = total_invoiced - total_paid

    invoices = db.execute(
        select(Invoice).options(
            joinedload(Invoice.items).joinedload(InvoiceItem.batch).joinedload(StockBatch.product)
        ).where(
            Invoice.party_id == party_id,
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

        # Calculate per-invoice profit (for SALE invoices)
        inv_profit = Decimal("0")
        if inv.invoice_type == InvoiceType.SALE:
            for item in inv.items:
                cost = item.purchase_price if item.purchase_price is not None else (
                    item.batch.purchase_price if item.batch else Decimal("0")
                )
                sale = item.sale_price if item.sale_price is not None else item.unit_price
                inv_profit += (sale - cost) * item.quantity

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
                    "sale_price": float(item.sale_price) if item.sale_price else None,
                    "product_name": item.batch.product.name if item.batch and item.batch.product else None,
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

    return {
        "party": {
            "id": party.id,
            "name": party.name,
            "party_type": party.party_type.value if party.party_type else None,
        },
        "financials": {
            "total_invoiced": float(total_invoiced),
            "total_paid": float(total_paid),
            "balance": float(balance),
            "total_profit": total_profit,
        },
        "invoices": invoice_list,
        "products": product_summary,
    }


@router.delete("/{party_id}")
def delete_party(
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
    return {"status": "deleted"}
