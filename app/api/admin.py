"""
app/api/admin  –  Super-Admin endpoints for platform management
================================================================
Only users with role == "super_admin" can access these routes.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.domain import Tenant, User, Invoice, Product, Party

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Guard: require super_admin role ──────────────────────────────────────────
def require_super_admin(current_user: User = Depends(get_current_user)):
    if current_user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super-admin access required.",
        )
    return current_user


# ── Platform statistics ──────────────────────────────────────────────────────
@router.get("/stats")
def get_platform_stats(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    """Return aggregate platform metrics."""
    total_tenants = db.query(func.count(Tenant.id)).scalar() or 0
    active_tenants = db.query(func.count(Tenant.id)).filter(Tenant.is_active.is_(True)).scalar() or 0
    approved_tenants = db.query(func.count(Tenant.id)).filter(Tenant.is_approved.is_(True)).scalar() or 0
    pending_tenants = db.query(func.count(Tenant.id)).filter(Tenant.is_approved.is_(False)).scalar() or 0
    total_users = db.query(func.count(User.id)).scalar() or 0
    total_products = db.query(func.count(Product.id)).scalar() or 0
    total_invoices = db.query(func.count(Invoice.id)).scalar() or 0
    total_parties = db.query(func.count(Party.id)).scalar() or 0

    return {
        "total_tenants": total_tenants,
        "active_tenants": active_tenants,
        "approved_tenants": approved_tenants,
        "pending_tenants": pending_tenants,
        "total_users": total_users,
        "total_products": total_products,
        "total_invoices": total_invoices,
        "total_parties": total_parties,
    }


# ── List all tenants ─────────────────────────────────────────────────────────
@router.get("/tenants")
def list_all_tenants(
    skip: int = 0,
    limit: int = 100,
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    """List all tenants on the platform with their owner info."""
    query = db.query(Tenant)
    if status_filter == "approved":
        query = query.filter(Tenant.is_approved.is_(True))
    elif status_filter == "pending":
        query = query.filter(Tenant.is_approved.is_(False))
    elif status_filter == "inactive":
        query = query.filter(Tenant.is_active.is_(False))

    tenants = query.order_by(Tenant.id.desc()).offset(skip).limit(limit).all()

    results = []
    for t in tenants:
        # Get the admin user for this tenant
        owner = db.query(User).filter(User.tenant_id == t.id, User.role.in_(["admin", "super_admin"])).first()
        user_count = db.query(func.count(User.id)).filter(User.tenant_id == t.id).scalar() or 0
        product_count = db.query(func.count(Product.id)).filter(Product.tenant_id == t.id).scalar() or 0
        invoice_count = db.query(func.count(Invoice.id)).filter(Invoice.tenant_id == t.id).scalar() or 0

        results.append({
            "id": t.id,
            "company_name": t.company_name,
            "store_name": t.store_name,
            "phone": t.phone,
            "address": t.address,
            "is_active": t.is_active,
            "is_approved": t.is_approved,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "owner_username": owner.username if owner else None,
            "owner_full_name": owner.full_name if owner else None,
            "user_count": user_count,
            "product_count": product_count,
            "invoice_count": invoice_count,
        })

    return results


# ── Approve a tenant ──────────────────────────────────────────────────────────
@router.patch("/tenants/{tenant_id}/approve")
def approve_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.is_approved = True
    tenant.is_active = True
    db.commit()
    return {"message": "Tenant approved", "tenant_id": tenant_id}


# ── Reject (deactivate) a tenant ─────────────────────────────────────────────
@router.patch("/tenants/{tenant_id}/reject")
def reject_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.is_approved = False
    tenant.is_active = False
    db.commit()
    return {"message": "Tenant rejected", "tenant_id": tenant_id}


# ── Toggle tenant active status ──────────────────────────────────────────────
@router.patch("/tenants/{tenant_id}/toggle-active")
def toggle_tenant_active(
    tenant_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.is_active = not tenant.is_active
    db.commit()
    return {"message": f"Tenant {'activated' if tenant.is_active else 'deactivated'}", "is_active": tenant.is_active}


# ── Delete a tenant (Account Deletion) ───────────────────────────────────────
@router.delete("/tenants/{tenant_id}")
def delete_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    db.delete(tenant)
    db.commit()
    return {"message": "Tenant deleted successfully"}


# ── List all users (System-wide) ─────────────────────────────────────────────
@router.get("/users")
def list_all_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    users = db.query(User).order_by(User.id.desc()).offset(skip).limit(limit).all()
    results = []
    for u in users:
        tenant_name = u.tenant.company_name if u.tenant else "Unknown"
        results.append({
            "id": u.id,
            "username": u.username,
            "full_name": u.full_name,
            "role": u.role,
            "tenant_id": u.tenant_id,
            "company_name": tenant_name
        })
    return results


# ── Delete a user ────────────────────────────────────────────────────────────
@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "super_admin":
        raise HTTPException(status_code=403, detail="Cannot delete super admin")
    db.delete(user)
    db.commit()
    return {"message": "User deleted successfully"}

# ── Get user details ─────────────────────────────────────────────────────────
@router.get("/users/{user_id}")
def get_user_details(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    tenant = user.tenant
    
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "tenant_id": user.tenant_id,
        "company_name": tenant.company_name if tenant else "Unknown",
        "tenant_is_active": tenant.is_active if tenant else False,
        "tenant_is_approved": tenant.is_approved if tenant else False,
    }


# ── Stock & Invoice diagnostics / repair ─────────────────────────────────────
from decimal import Decimal
from sqlalchemy import select
from app.models.domain import Invoice, InvoiceItem, InvoiceType, Payment, StockBatch


def _diagnose_tenant(db: Session, tenant_id: int):
    """Read-only: compute discrepancies in stock and invoice totals."""
    from sqlalchemy.orm import selectinload

    batches = db.execute(
        select(StockBatch).where(StockBatch.tenant_id == tenant_id)
    ).scalars().all()

    batch_issues = []
    for batch in batches:
        sold = Decimal(str(db.execute(
            select(func.coalesce(func.sum(InvoiceItem.quantity), 0))
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .where(InvoiceItem.batch_id == batch.id,
                   Invoice.invoice_type == InvoiceType.SELL,
                   Invoice.tenant_id == tenant_id)
        ).scalar_one()))
        sell_ret = Decimal(str(db.execute(
            select(func.coalesce(func.sum(InvoiceItem.quantity), 0))
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .where(InvoiceItem.batch_id == batch.id,
                   Invoice.invoice_type == InvoiceType.SELL_RETURN,
                   Invoice.tenant_id == tenant_id)
        ).scalar_one()))
        purch_ret = Decimal(str(db.execute(
            select(func.coalesce(func.sum(InvoiceItem.quantity), 0))
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .where(InvoiceItem.batch_id == batch.id,
                   Invoice.invoice_type == InvoiceType.PURCHASE_RETURN,
                   Invoice.tenant_id == tenant_id)
        ).scalar_one()))

        initial = Decimal(str(batch.initial_quantity or 0))
        # Note: SELL_RETURN creates a new StockBatch with its own initial_quantity.
        # Adding sell_ret here would double-count the returned stock for that new batch.
        correct = initial - sold - purch_ret
        actual  = Decimal(str(batch.remaining_quantity or 0))
        diff    = float(correct - actual)

        if abs(diff) > 0.001:
            batch_issues.append({
                "batch_id":          batch.id,
                "product_id":        batch.product_id,
                "initial":           float(initial),
                "sold":              float(sold),
                "sell_returns":      float(sell_ret),
                "purchase_returns":  float(purch_ret),
                "correct_remaining": float(correct),
                "actual_remaining":  float(actual),
                "difference":        diff,
            })

    invoices = db.execute(
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.tenant_id == tenant_id)
    ).unique().scalars().all()

    invoice_issues = []
    for inv in invoices:
        computed = float(sum(
            Decimal(str(item.quantity or 0)) * Decimal(str(item.unit_price or 0))
            for item in inv.items
        ))
        stored = float(inv.total_amount or 0)
        if abs(computed - stored) > 0.01:
            invoice_issues.append({
                "invoice_id":    inv.id,
                "invoice_type":  inv.invoice_type.value if inv.invoice_type else None,
                "party_id":      inv.party_id,
                "stored_total":  stored,
                "correct_total": computed,
                "difference":    round(computed - stored, 2),
            })

    return batch_issues, invoice_issues


@router.get("/tenants/{tenant_id}/diagnose")
def diagnose_tenant_data(
    tenant_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    """Diagnose stock & invoice inconsistencies for a tenant (read-only)."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    batch_issues, invoice_issues = _diagnose_tenant(db, tenant_id)

    return {
        "tenant_id":             tenant_id,
        "company_name":          tenant.company_name,
        "batch_issues_count":    len(batch_issues),
        "invoice_issues_count":  len(invoice_issues),
        "batch_issues":          batch_issues,
        "invoice_issues":        invoice_issues,
        "status":                "clean" if not batch_issues and not invoice_issues else "has_issues",
    }


@router.post("/tenants/{tenant_id}/fix-stock")
def fix_tenant_stock(
    tenant_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    """
    Apply fixes for a tenant:
    - Correct StockBatch.remaining_quantity from actual invoice items.
    - Correct Invoice.total_amount from sum of line items.
    """
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    batch_issues, invoice_issues = _diagnose_tenant(db, tenant_id)

    fixed_batches:  list = []
    fixed_invoices: list = []

    try:
        for issue in batch_issues:
            batch = db.get(StockBatch, issue["batch_id"])
            if batch:
                batch.remaining_quantity = issue["correct_remaining"]
                fixed_batches.append({
                    "batch_id":   issue["batch_id"],
                    "product_id": issue["product_id"],
                    "old_value":  issue["actual_remaining"],
                    "new_value":  issue["correct_remaining"],
                })

        for issue in invoice_issues:
            inv = db.get(Invoice, issue["invoice_id"])
            if inv:
                inv.total_amount = issue["correct_total"]
                fixed_invoices.append({
                    "invoice_id":   issue["invoice_id"],
                    "invoice_type": issue["invoice_type"],
                    "old_value":    issue["stored_total"],
                    "new_value":    issue["correct_total"],
                })

        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Fix failed: {exc}")

    return {
        "tenant_id":             tenant_id,
        "company_name":          tenant.company_name,
        "fixed_batches_count":   len(fixed_batches),
        "fixed_invoices_count":  len(fixed_invoices),
        "fixed_batches":         fixed_batches,
        "fixed_invoices":        fixed_invoices,
        "status":                "ok",
    }
