from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.domain import StockBatch, User
from app.schemas.batch import StockBatchOut, StockBatchUpdate

router = APIRouter(prefix="/batches", tags=["batches"])


@router.get("/product/{product_id}", response_model=list[StockBatchOut])
def list_batches_by_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(StockBatch).where(
        StockBatch.product_id == product_id,
        StockBatch.tenant_id == current_user.tenant_id,
    )
    return db.execute(stmt).scalars().all()


@router.patch("/{batch_id}", response_model=StockBatchOut)
def update_batch(
    batch_id: int,
    data: StockBatchUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    batch = db.execute(
        select(StockBatch).where(StockBatch.id == batch_id, StockBatch.tenant_id == current_user.tenant_id)
    ).scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    batch.current_selling_price = data.current_selling_price
    db.commit()
    db.refresh(batch)
    return batch
