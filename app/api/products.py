from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.domain import Invoice, InvoiceItem, InvoiceType, Product, StockBatch, User, Party
from app.repositories.base import ProductRepository
from app.schemas.product import ProductCreate

from sqlalchemy import text
router = APIRouter(prefix="/products", tags=["products"])

@router.get("/migrate-party")
def migrate_party(db: Session = Depends(get_db)):
    try:
        db.execute(text("ALTER TABLE stock_batches ADD COLUMN party_id INTEGER REFERENCES parties(id) NULL"))
        db.execute(text("CREATE INDEX ix_stock_batches_party_id ON stock_batches (party_id)"))
        db.commit()
        return "done"
    except Exception as e:
        db.rollback()
        return str(e)



class ProductWithCostOut(BaseModel):
    id: int
    name: str
    last_purchase_price: Optional[float] = 0.0
    purchase_price: Optional[float] = 0.0
    sell_price: Optional[float] = 0.0
    supplier_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)





from app.core.cache import get_cache, set_cache, invalidate_tenant_cache


@router.post("", response_model=ProductWithCostOut)
async def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = Product(
        name=data.name,
        tenant_id=current_user.tenant_id,
        purchase_price=data.purchase_price,
        sell_price=data.sell_price
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    
    await invalidate_tenant_cache(current_user.tenant_id, ["products", "reports:inventory"])

    return ProductWithCostOut(
        id=product.id,
        name=product.name,
        last_purchase_price=float(product.last_purchase_price or 0),
        purchase_price=float(product.purchase_price or 0),
        sell_price=float(product.sell_price or 0),
        supplier_name=None,
    )


@router.get("", response_model=list[ProductWithCostOut])
async def list_products(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"products:list:{skip}:{limit}:{search or ''}"
    cached = await get_cache(current_user.tenant_id, cache_key)
    if cached is not None:
        return cached

    prod_repo = ProductRepository(db, current_user.tenant_id)
    products = prod_repo.list(skip=skip, limit=limit, search=search)
    if not products:
        return []

    product_ids = [p.id for p in products]
    latest_batch_by_product = prod_repo.get_latest_batches_for_products(product_ids)
    supplier_dict = prod_repo.get_latest_suppliers_for_products(product_ids)

    result = []
    for product in products:
        latest_batch = latest_batch_by_product.get(product.id)
        
        purchase_price = float(product.purchase_price or 0)
        sell_price = float(product.sell_price or 0)
        
        if latest_batch:
            if purchase_price == 0:
                purchase_price = float(latest_batch.purchase_price or 0)
            if sell_price == 0:
                sell_price = float(latest_batch.current_selling_price or 0)
                
        result.append(
            ProductWithCostOut(
                id=product.id,
                name=product.name,
                last_purchase_price=float(product.last_purchase_price or 0),
                purchase_price=purchase_price,
                sell_price=sell_price,
                supplier_name=supplier_dict.get(product.id)
            )
        )

    res_dict = [r.model_dump() if hasattr(r, "model_dump") else r.dict() for r in result]
    await set_cache(current_user.tenant_id, cache_key, res_dict, ttl=300)
    return result


@router.get("/select")
def list_products_select(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prod_repo = ProductRepository(db, current_user.tenant_id)
    return prod_repo.get_all_for_select()


@router.delete("/{product_id}")
async def delete_product(
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

    await invalidate_tenant_cache(current_user.tenant_id, ["products", "reports:inventory"])
    return {"status": "deleted"}


from app.schemas.product import ProductUpdate

@router.put("/{product_id}", response_model=ProductWithCostOut)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == current_user.tenant_id)
    ).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if data.name is not None:
        product.name = data.name
    if data.purchase_price is not None:
        product.purchase_price = data.purchase_price
    if data.sell_price is not None:
        product.sell_price = data.sell_price

    db.commit()
    db.refresh(product)

    await invalidate_tenant_cache(current_user.tenant_id, ["products", "reports:inventory"])

    return ProductWithCostOut(
        id=product.id,
        name=product.name,
        last_purchase_price=float(product.last_purchase_price or 0),
        purchase_price=float(product.purchase_price or 0),
        sell_price=float(product.sell_price or 0),
        supplier_name=None,
    )
