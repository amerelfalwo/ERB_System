from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.domain import Tenant, User


class TenantLogoUpdate(BaseModel):
    logo_url: str


class TenantSettingsUpdate(BaseModel):
    company_name: Optional[str] = None
    store_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_number: Optional[str] = None
    print_notes: Optional[str] = None
    primary_color: Optional[str] = None
    default_footer_text: Optional[str] = None


class TenantUpdate(BaseModel):
    company_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_number: Optional[str] = None
    default_invoice_footer: Optional[str] = None


class TenantOut(BaseModel):
    id: int
    company_name: str
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    default_footer_text: Optional[str] = None
    store_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_number: Optional[str] = None
    print_notes: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True

    @model_validator(mode='after')
    def populate_aliases(self):
        # store_name is an alias for company_name
        if self.store_name is None:
            self.store_name = self.company_name
        # print_notes is an alias for default_footer_text
        if self.print_notes is None:
            self.print_notes = self.default_footer_text
        return self


router = APIRouter(prefix="/tenants", tags=["tenants"])

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
LOGOS_DIR = STATIC_DIR / "logos"


@router.get("/me", response_model=TenantOut)
def get_my_tenant(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id, Tenant.is_active.is_(True))
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.patch("/me", response_model=TenantOut)
def update_tenant_settings(
    data: TenantSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id, Tenant.is_active.is_(True))
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    update_data = data.model_dump(exclude_unset=True)
    # Handle aliases: store_name → company_name, print_notes → default_footer_text
    if "store_name" in update_data:
        tenant.company_name = update_data.pop("store_name")
    if "print_notes" in update_data:
        tenant.default_footer_text = update_data.pop("print_notes")
    # Apply remaining fields that exist on the model
    for field, value in update_data.items():
        if hasattr(tenant, field):
            setattr(tenant, field, value)
    db.commit()
    db.refresh(tenant)
    return tenant


@router.put("/settings", response_model=TenantOut)
def update_tenant_settings_put(
    data: TenantUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id, Tenant.is_active.is_(True))
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    update_data = data.model_dump(exclude_unset=True)
    if "default_invoice_footer" in update_data:
        tenant.default_footer_text = update_data.pop("default_invoice_footer")
        
    for field, value in update_data.items():
        if hasattr(tenant, field):
            setattr(tenant, field, value)
            
    db.commit()
    db.refresh(tenant)
    return tenant


@router.patch("/me/logo", response_model=TenantOut)
def update_tenant_logo(
    data: TenantLogoUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id, Tenant.is_active.is_(True))
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.logo_url = data.logo_url
    db.commit()
    db.refresh(tenant)
    return tenant


@router.post("/upload-logo", response_model=TenantOut)
async def upload_tenant_logo(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id, Tenant.is_active.is_(True))
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid file type")
    LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "").suffix.lower() or ".png"
    filename = f"tenant_{tenant.id}_{uuid4().hex}{suffix}"
    file_path = LOGOS_DIR / filename
    content = await file.read()
    file_path.write_bytes(content)
    logo_url = f"/static/logos/{filename}"
    tenant.logo_url = logo_url
    db.commit()
    db.refresh(tenant)
    return tenant
