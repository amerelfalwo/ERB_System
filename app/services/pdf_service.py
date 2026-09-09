import re
import os
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session
from sqlalchemy import select
from weasyprint import HTML

from app.models.domain import Invoice, Party, Tenant, InvoiceItem


TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(enabled_extensions=("html", "xml")),
)


def generate_pdf_filename(party_name: str | None, date_val: datetime | str | None, invoice_type: str | None) -> str:
    raw_name = (party_name or "Customer").strip()
    clean_name = re.sub(r"^Dr\s*/?\s*", "", raw_name, flags=re.IGNORECASE).strip()
    clean_name = re.sub(r'[\\/:*?"<>|]', "_", clean_name)
    clean_name = re.sub(r"\s+", "_", clean_name)
    if not clean_name:
        clean_name = "Customer"

    if isinstance(date_val, datetime):
        date_str = date_val.strftime("%Y-%m-%d")
    elif date_val and isinstance(date_val, str):
        try:
            date_str = datetime.fromisoformat(date_val.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except Exception:
            date_str = date_val[:10]
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    is_return = invoice_type and "RETURN" in str(invoice_type).upper()
    if is_return:
        return f"{clean_name}-مرتجع-{date_str}.pdf"
    return f"{clean_name}-{date_str}.pdf"


def _fmt_money(val: float | Decimal | int) -> str:
    num = float(val or 0)
    return f"{num:,.2f}"


def _format_date(dt: datetime | str | None) -> str:
    if not dt:
        return ""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return dt
    return dt.strftime("%b %d, %Y")


def generate_invoice_pdf(db: Session, invoice: Invoice) -> bytes:
    """
    Generates a PDF for an invoice using Jinja2 and WeasyPrint matching InvoiceDocument.jsx.
    """
    # Fetch tenant details
    tenant = db.execute(
        select(Tenant).where(Tenant.id == invoice.tenant_id)
    ).scalar_one_or_none()

    # Fetch party details
    party = getattr(invoice, "party", None)
    if not party and invoice.party_id:
        party = db.execute(
            select(Party).where(Party.id == invoice.party_id)
        ).scalar_one_or_none()

    # Extract invoice properties
    invoice_number = f"#{str(invoice.id).zfill(5)}"
    raw_type = str(invoice.invoice_type or "SELL").upper()
    is_return = "RETURN" in raw_type
    is_purchase_return = "PURCHASE_RETURN" in raw_type
    is_sell_return = "SELL_RETURN" in raw_type or (is_return and not is_purchase_return)
    is_purchase = raw_type == "PURCHASE"

    if is_sell_return:
        title_text = "SELL RETURN"
    elif is_purchase_return:
        title_text = "PURCHASE RETURN"
    elif is_purchase:
        title_text = "PURCHASE INVOICE"
    else:
        title_text = "SELL INVOICE"

    # Party Name & Phone
    raw_party_name = party.name if party else (getattr(invoice, "party_name", None) or "")
    clean_party_name = re.sub(r"^Dr\s*/?\s*", "", raw_party_name, flags=re.IGNORECASE).strip()
    party_phone = party.phone if party else (getattr(invoice, "party_phone", None) or "")

    # Date
    raw_date = invoice.issue_date or invoice.created_at
    invoice_date = _format_date(raw_date)

    # Items & Serials
    items_formatted = []
    serial_items = []
    calculated_items_total = Decimal("0")

    for item in invoice.items:
        # Product Name
        prod_name = "Item"
        if hasattr(item, "batch") and item.batch and hasattr(item.batch, "product") and item.batch.product:
            prod_name = item.batch.product.name
        elif getattr(item, "product_name", None):
            prod_name = item.product_name

        qty = item.quantity or 0
        if isinstance(qty, Decimal) and qty == qty.to_integral_value():
            qty_display = int(qty)
        else:
            qty_display = float(qty)

        price = item.unit_price or getattr(item, "sell_price", None) or getattr(item, "purchase_price", None) or Decimal("0")
        total = qty * price
        calculated_items_total += total

        items_formatted.append({
            "name": prod_name,
            "quantity": qty_display,
            "unit_price": price,
            "total": total,
            "formatted_price": _fmt_money(price),
            "formatted_total": _fmt_money(total),
        })

        # Serial numbers
        raw_sn = getattr(item, "serial_number", None) or getattr(item, "serial_numbers", None) or getattr(item, "serials", None)
        if raw_sn:
            if isinstance(raw_sn, list):
                sn_str = ", ".join(str(s) for s in raw_sn if s)
            else:
                sn_str = str(raw_sn).strip()
            if sn_str:
                serial_items.append({
                    "name": prod_name,
                    "serial": sn_str
                })

    # Totals calculation
    items_total = calculated_items_total
    delivery_fee = Decimal(str(invoice.delivery_fee or 0))
    discount_amount = Decimal(str(getattr(invoice, "discount_amount", 0) or getattr(invoice, "total_discount", 0) or 0))
    grand_total = items_total + delivery_fee - discount_amount

    # Tenant info
    tenant_name = tenant.company_name if tenant and tenant.company_name else "DOCTOR M - Dental Supplies"
    tenant_logo_url = tenant.logo_url if tenant else None

    # Handle logo path for WeasyPrint if it's local
    if tenant_logo_url and tenant_logo_url.startswith("/"):
        backend_root = Path(__file__).parent.parent.parent
        potential_file = backend_root / tenant_logo_url.lstrip("/")
        if potential_file.exists():
            tenant_logo_url = potential_file.as_uri()

    website = tenant.website if tenant else ""
    website_url = website
    if website and not (website.startswith("http://") or website.startswith("https://")):
        website_url = f"https://{website}"

    # Footer text
    custom_footer = getattr(invoice, "footer_custom_text", None) or (tenant.default_footer_text if tenant else None)
    if custom_footer:
        footer_text = custom_footer
    else:
        brand_short = tenant_name.split("-")[0].strip()
        footer_text = f"Thank You For Choosing {brand_short}"

    fonts_dir = (Path(__file__).parent.parent / "static" / "fonts").as_uri()

    context: Dict[str, Any] = {
        "fonts_dir": fonts_dir,
        "tenant_name": tenant_name,
        "tenant_logo_url": tenant_logo_url,
        "invoice_date": invoice_date,
        "title_text": title_text,
        "is_return": is_sell_return,
        "invoice_number": invoice_number,
        "clean_party_name": clean_party_name,
        "party_phone": party_phone,
        "items": items_formatted,
        "formatted_items_total": _fmt_money(items_total),
        "formatted_delivery_fee": _fmt_money(delivery_fee),
        "has_discount": discount_amount > 0,
        "formatted_discount": _fmt_money(discount_amount),
        "formatted_grand_total": _fmt_money(grand_total),
        "footer_text": footer_text,
        "website": website,
        "website_url": website_url,
        "serial_items": serial_items,
    }

    template = jinja_env.get_template("invoice_pdf.html")
    html_content = template.render(**context)

    # Convert HTML to PDF using WeasyPrint
    pdf_bytes = HTML(string=html_content).write_pdf()
    return pdf_bytes
