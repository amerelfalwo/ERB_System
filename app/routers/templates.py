from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.domain import PrintTemplate
from app.schemas.template import PrintPreviewOut, PrintTemplateCreate, PrintTemplateOut, PrintTemplateUpdate
from app.services.printing import create_template, render_invoice_html, update_template

router = APIRouter(prefix="/templates", tags=["templates"])


@router.post("", response_model=PrintTemplateOut)
def create_print_template(data: PrintTemplateCreate, db: Session = Depends(get_db)):
    return create_template(db, data.name, data.html_content, data.settings)


@router.get("", response_model=list[PrintTemplateOut])
def list_templates(db: Session = Depends(get_db)):
    return db.execute(select(PrintTemplate)).scalars().all()


@router.get("/{template_id}", response_model=PrintTemplateOut)
def get_template(template_id: int, db: Session = Depends(get_db)):
    template = db.get(PrintTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.patch("/{template_id}", response_model=PrintTemplateOut)
def patch_template(template_id: int, data: PrintTemplateUpdate, db: Session = Depends(get_db)):
    template = db.get(PrintTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return update_template(db, template, data.name, data.html_content, data.settings)


@router.get("/{template_id}/preview/{invoice_id}", response_model=PrintPreviewOut)
def preview_template(template_id: int, invoice_id: int, db: Session = Depends(get_db)):
    try:
        html = render_invoice_html(db, invoice_id, template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return PrintPreviewOut(html=html)
