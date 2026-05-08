from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.domain import PrintTemplate, User
from app.schemas.template import PrintPreviewOut, PrintTemplateCreate, PrintTemplateOut, PrintTemplateUpdate
from app.services.printing import create_template, render_invoice_html, update_template

router = APIRouter(prefix="/templates", tags=["templates"])


@router.post("", response_model=PrintTemplateOut)
def create_print_template(
    data: PrintTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return create_template(db, data.name, data.html_content, data.settings, current_user.tenant_id)


@router.get("", response_model=list[PrintTemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.execute(
        select(PrintTemplate).where(PrintTemplate.tenant_id == current_user.tenant_id)
    ).scalars().all()


@router.get("/{template_id}", response_model=PrintTemplateOut)
def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    template = db.execute(
        select(PrintTemplate).where(
            PrintTemplate.id == template_id,
            PrintTemplate.tenant_id == current_user.tenant_id,
        )
    ).scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.patch("/{template_id}", response_model=PrintTemplateOut)
def patch_template(
    template_id: int,
    data: PrintTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    template = db.execute(
        select(PrintTemplate).where(
            PrintTemplate.id == template_id,
            PrintTemplate.tenant_id == current_user.tenant_id,
        )
    ).scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return update_template(db, template, data.name, data.html_content, data.settings)


@router.get("/{template_id}/preview/{invoice_id}", response_model=PrintPreviewOut)
def preview_template(
    template_id: int,
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        html = render_invoice_html(db, invoice_id, template_id, current_user.tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return PrintPreviewOut(html=html)
