from decimal import Decimal
from typing import Dict

from jinja2 import BaseLoader, Environment, select_autoescape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.domain import Invoice, InvoiceItem, Party, Payment, PrintTemplate


def render_invoice_html(db: Session, invoice_id: int, template_id: int, tenant_id: int) -> str:
    invoice = db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not invoice:
        raise ValueError("Invoice not found")

    template = db.execute(
        select(PrintTemplate).where(PrintTemplate.id == template_id, PrintTemplate.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not template:
        raise ValueError("Template not found")

    items = db.execute(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice_id)).scalars().all()
    party = db.execute(
        select(Party).where(Party.id == invoice.party_id, Party.tenant_id == tenant_id)
    ).scalar_one_or_none()
    paid = db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.invoice_id == invoice_id)
    ).scalar_one()
    balance = invoice.total_amount - paid

    context: Dict[str, object] = {
        "invoice": invoice,
        "party": party,
        "items": items,
        "total": invoice.total_amount,
        "paid": paid,
        "balance": balance,
        "status": "paid" if balance <= 0 else "partial" if paid > 0 else "unpaid",
        "settings": template.settings or {},
    }

    env = Environment(loader=BaseLoader(), autoescape=select_autoescape(enabled_extensions=("html", "xml")))
    tmpl = env.from_string(template.html_content)
    return tmpl.render(**context)


def create_template(db: Session, name: str, html_content: str, settings: Dict | None, tenant_id: int) -> PrintTemplate:
    template = PrintTemplate(name=name, html_content=html_content, settings=settings, tenant_id=tenant_id)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def update_template(db: Session, template: PrintTemplate, name: str | None, html_content: str | None, settings: Dict | None) -> PrintTemplate:
    if name is not None:
        template.name = name
    if html_content is not None:
        template.html_content = html_content
    if settings is not None:
        template.settings = settings
    db.commit()
    db.refresh(template)
    return template
