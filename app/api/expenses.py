from typing import List, Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from decimal import Decimal
from sqlalchemy import desc, func

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.domain import User, Expense
from app.schemas.expense import ExpenseCreate, ExpenseRead, ExpenseSummaryRead

router = APIRouter(prefix="/expenses", tags=["Expenses"])

@router.get("/summary", response_model=ExpenseSummaryRead)
def get_expenses_summary(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get aggregated expenses summary (total amount, count, top category).
    """
    from datetime import datetime, time

    query = db.query(Expense).filter(Expense.tenant_id == current_user.tenant_id)
    if date_from:
        dt_from = datetime.combine(date_from, time.min)
        query = query.filter(Expense.expense_date >= dt_from)
    if date_to:
        dt_to = datetime.combine(date_to, time.max)
        query = query.filter(Expense.expense_date <= dt_to)

    total_expenses = query.with_entities(func.coalesce(func.sum(Expense.amount), 0)).scalar() or Decimal("0")
    expenses_count = query.count()

    top_cat_query = (
        query.filter(Expense.category.isnot(None), Expense.category != "")
        .with_entities(Expense.category, func.sum(Expense.amount).label("cat_total"))
        .group_by(Expense.category)
        .order_by(desc("cat_total"))
        .first()
    )

    top_category = top_cat_query[0] if top_cat_query else None

    return ExpenseSummaryRead(
        total_expenses=Decimal(str(total_expenses)),
        expenses_count=expenses_count,
        top_category=top_category
    )

@router.post("", response_model=ExpenseRead, status_code=status.HTTP_201_CREATED)
def create_expense(
    expense_in: ExpenseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new expense for the current tenant.
    """
    from datetime import datetime, time
    expense_datetime = datetime.combine(expense_in.expense_date, time.min)

    expense = Expense(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        description=expense_in.description,
        amount=expense_in.amount,
        expense_date=expense_datetime,
        category=expense_in.category
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense

@router.get("", response_model=List[ExpenseRead])
def get_expenses(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List expenses for the current tenant.
    """
    query = db.query(Expense).filter(Expense.tenant_id == current_user.tenant_id)

    from datetime import datetime, time

    if date_from:
        dt_from = datetime.combine(date_from, time.min)
        query = query.filter(Expense.expense_date >= dt_from)
    if date_to:
        dt_to = datetime.combine(date_to, time.max)
        query = query.filter(Expense.expense_date <= dt_to)
    if category:
        query = query.filter(Expense.category == category)

    query = query.order_by(desc(Expense.expense_date), desc(Expense.created_at))
    return query.all()

@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete an expense.
    """
    expense = db.query(Expense).filter(
        Expense.id == expense_id,
        Expense.tenant_id == current_user.tenant_id
    ).first()

    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    db.delete(expense)
    db.commit()
    return None
