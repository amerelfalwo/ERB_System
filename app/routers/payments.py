from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.payment import PaymentCreate, PaymentOut
from app.services.payments import create_payment

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("", response_model=PaymentOut)
def add_payment(data: PaymentCreate, db: Session = Depends(get_db)):
    return create_payment(db, data)
