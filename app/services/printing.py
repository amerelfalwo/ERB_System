from decimal import Decimal
from typing import Dict

from jinja2 import BaseLoader, Environment
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.domain import Invoice, InvoiceItem, Party, Payment, PrintTemplate


def render_invoice_html(db: Session, invoice_id: int, template_id: int) -> str:
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise ValueError("Invoice not found")

    template = db.get(PrintTemplate, template_id)
    if not template:
        raise ValueError("Template not found")

    items = db.execute(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice_id)).scalars().all()
    party = db.get(Party, invoice.party_id)
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

    env = Environment(loader=BaseLoader())
    tmpl = env.from_string(template.html_content)
    return tmpl.render(**context)


def create_template(db: Session, name: str, html_content: str, settings: Dict | None) -> PrintTemplate:
    template = PrintTemplate(name=name, html_content=html_content, settings=settings)
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
