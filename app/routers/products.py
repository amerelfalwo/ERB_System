from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.domain import Invoice, InvoiceItem, InvoiceType, Product, StockBatch, User
from app.schemas.product import ProductCreate

router = APIRouter(prefix="/products", tags=["products"])


class ProductWithCostOut(BaseModel):
    id: int
    name: str
    last_purchase_price: Optional[float] = 0.0
    current_cost: Optional[float] = None
    current_selling_price: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


def _get_current_cost(db: Session, product_id: int, tenant_id: int) -> Optional[Decimal]:
    fifo_price = db.execute(
        select(StockBatch.purchase_price)
        .where(
            StockBatch.product_id == product_id,
            StockBatch.tenant_id == tenant_id,
            StockBatch.remaining_quantity > 0,
        )
        .order_by(StockBatch.created_at.asc(), StockBatch.id.asc())
        .limit(1)
    ).scalar_one_or_none()

    if fifo_price is not None:
        return fifo_price

    last_purchase_price = db.execute(
        select(InvoiceItem.purchase_price)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(
            Invoice.invoice_type == InvoiceType.PURCHASE,
            Invoice.tenant_id == tenant_id,
            InvoiceItem.batch_id.in_(
                select(StockBatch.id).where(
                    StockBatch.product_id == product_id,
                    StockBatch.tenant_id == tenant_id,
                )
            ),
        )
        .order_by(Invoice.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    return last_purchase_price


def _get_current_selling_price(db: Session, product_id: int, tenant_id: int) -> Optional[Decimal]:
    return db.execute(
        select(StockBatch.current_selling_price)
        .where(
            StockBatch.product_id == product_id,
            StockBatch.tenant_id == tenant_id,
            StockBatch.remaining_quantity > 0,
        )
        .order_by(StockBatch.current_selling_price.desc())
        .limit(1)
    ).scalar_one_or_none()


@router.post("", response_model=ProductWithCostOut)
def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = Product(name=data.name, tenant_id=current_user.tenant_id)
    db.add(product)
    db.commit()
    db.refresh(product)
    return ProductWithCostOut(
        id=product.id,
        name=product.name,
        last_purchase_price=float(product.last_purchase_price or 0),
        current_cost=None,
        current_selling_price=None,
    )


@router.get("", response_model=list[ProductWithCostOut])
def list_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    products = db.execute(
        select(Product).where(Product.tenant_id == current_user.tenant_id)
    ).scalars().all()

    result = []
    for product in products:
        cost = _get_current_cost(db, product.id, current_user.tenant_id)
        sell = _get_current_selling_price(db, product.id, current_user.tenant_id)
        result.append(
            ProductWithCostOut(
                id=product.id,
                name=product.name,
                last_purchase_price=float(product.last_purchase_price or 0),
                current_cost=float(cost) if cost is not None else None,
                current_selling_price=float(sell) if sell is not None else None,
            )
        )
    return result


@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == current_user.tenant_id)
    ).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    batches_count = db.execute(
        select(func.count(StockBatch.id)).where(
            StockBatch.product_id == product_id,
            StockBatch.tenant_id == current_user.tenant_id,
        )
    ).scalar_one()
    if batches_count > 0:
        raise HTTPException(status_code=400, detail="لا يمكن حذف المنتج لوجود مخزون")
    db.delete(product)
    db.commit()
    return {"status": "deleted"}
