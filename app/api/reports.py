from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.domain import User
from app.schemas.report import InventoryReportOut, ProfitReportOut, StatementOut, DashboardAnalyticsOut, PartyProfitSummaryOut, NetProfitReportOut, UnifiedDashboardOut
from app.services.reports import inventory_report, party_statement, profit_report, dashboard_analytics, party_profit_summary, net_profit_report, unified_dashboard_report
from typing import List, Optional

from app.core.cache import get_cache, set_cache

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/dashboard", response_model=UnifiedDashboardOut)
@router.get("/dashboard-unified", response_model=UnifiedDashboardOut)
async def dashboard(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    df = date_from or start_date
    dt = date_to or end_date
    cache_key = f"dashboard:{df or 'all'}:{dt or 'all'}"

    cached_data = await get_cache(current_user.tenant_id, cache_key)
    if cached_data is not None:
        return cached_data

    result = unified_dashboard_report(db, current_user.tenant_id, df, dt)
    result_dict = result.model_dump() if hasattr(result, "model_dump") else (result.dict() if hasattr(result, "dict") else result)
    await set_cache(current_user.tenant_id, cache_key, result_dict, ttl=300)
    return result


@router.get("/profit", response_model=ProfitReportOut)
async def profit(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = "reports:profit"
    cached = await get_cache(current_user.tenant_id, cache_key)
    if cached is not None:
        return cached
    result = profit_report(db, current_user.tenant_id)
    res_dict = result.model_dump() if hasattr(result, "model_dump") else (result.dict() if hasattr(result, "dict") else result)
    await set_cache(current_user.tenant_id, cache_key, res_dict, ttl=300)
    return result


@router.get("/net-profit", response_model=NetProfitReportOut)
async def net_profit(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"reports:net-profit:{start_date or 'all'}:{end_date or 'all'}"
    cached = await get_cache(current_user.tenant_id, cache_key)
    if cached is not None:
        return cached
    result = net_profit_report(db, current_user.tenant_id, start_date, end_date)
    res_dict = result.model_dump() if hasattr(result, "model_dump") else (result.dict() if hasattr(result, "dict") else result)
    await set_cache(current_user.tenant_id, cache_key, res_dict, ttl=300)
    return result


@router.get("/inventory", response_model=InventoryReportOut)
async def inventory(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = "reports:inventory"
    cached = await get_cache(current_user.tenant_id, cache_key)
    if cached is not None:
        return cached
    result = inventory_report(db, current_user.tenant_id)
    res_dict = result.model_dump() if hasattr(result, "model_dump") else (result.dict() if hasattr(result, "dict") else result)
    await set_cache(current_user.tenant_id, cache_key, res_dict, ttl=600)
    return result


@router.get("/statement/{party_id}", response_model=StatementOut)
def statement(
    party_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return party_statement(db, party_id, current_user.tenant_id)


@router.get("/party-profits", response_model=List[PartyProfitSummaryOut])
async def party_profits(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    df = date_from or start_date
    dt = date_to or end_date
    cache_key = f"reports:party-profits:{df or 'all'}:{dt or 'all'}"
    cached = await get_cache(current_user.tenant_id, cache_key)
    if cached is not None:
        return cached
    result = party_profit_summary(db, current_user.tenant_id, df, dt)
    res_dict = [r.model_dump() if hasattr(r, "model_dump") else (r.dict() if hasattr(r, "dict") else r) for r in result] if isinstance(result, list) else result
    await set_cache(current_user.tenant_id, cache_key, res_dict, ttl=600)
    return result


@router.get("/stock-ledger/{product_id}")
def stock_ledger(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.stock_ledger import get_product_stock_ledger
    return get_product_stock_ledger(db, product_id, current_user.tenant_id)

