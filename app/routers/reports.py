from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.report import InventoryReportOut, ProfitReportOut, StatementOut
from app.services.reports import inventory_report, party_statement, profit_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/profit", response_model=ProfitReportOut)
def profit(db: Session = Depends(get_db)):
    return profit_report(db)


@router.get("/inventory", response_model=InventoryReportOut)
def inventory(db: Session = Depends(get_db)):
    return inventory_report(db)


@router.get("/statement/{party_id}", response_model=StatementOut)
def statement(party_id: int, db: Session = Depends(get_db)):
    return party_statement(db, party_id)
