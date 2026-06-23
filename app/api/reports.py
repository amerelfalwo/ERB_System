from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.domain import User
from app.schemas.report import InventoryReportOut, ProfitReportOut, StatementOut, DashboardAnalyticsOut, PartyProfitSummaryOut
from app.services.reports import inventory_report, party_statement, profit_report, dashboard_analytics, party_profit_summary
from typing import List

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/dashboard", response_model=DashboardAnalyticsOut)
def dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_analytics(db, current_user.tenant_id)


@router.get("/profit", response_model=ProfitReportOut)
def profit(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return profit_report(db, current_user.tenant_id)


@router.get("/inventory", response_model=InventoryReportOut)
def inventory(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return inventory_report(db, current_user.tenant_id)


@router.get("/statement/{party_id}", response_model=StatementOut)
def statement(
    party_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return party_statement(db, party_id, current_user.tenant_id)


@router.get("/party-profits", response_model=List[PartyProfitSummaryOut])
def party_profits(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return party_profit_summary(db, current_user.tenant_id)
