from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.domain import User
from app.schemas.payment import PaymentCreate, PaymentOut
from app.services.payments import create_payment

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("", response_model=PaymentOut)
def add_payment(
    data: PaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return create_payment(db, data, current_user.tenant_id)
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
