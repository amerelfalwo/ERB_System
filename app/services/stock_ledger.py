from decimal import Decimal
from typing import List, Optional
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.domain import Invoice, InvoiceItem, InvoiceType, Product, StockBatch, Party

def get_product_stock_ledger(db: Session, product_id: int, tenant_id: int = None) -> List[dict]:
    product = db.execute(
        select(Product).where(Product.id == product_id)
    ).scalar_one_or_none()
    if not product:
        return []

    entries = []

    # 1. Batches without purchase invoice (Initial Stock / Seeding)
    batches = db.execute(
        select(StockBatch).where(
            StockBatch.product_id == product_id,
            StockBatch.tenant_id == tenant_id if tenant_id is not None else True
        ).order_by(StockBatch.created_at.asc())
    ).scalars().all()

    purch_item_batches = set()
    purch_items = db.execute(
        select(InvoiceItem, Invoice)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(
            InvoiceItem.batch_id.in_([b.id for b in batches]) if batches else False,
            Invoice.invoice_type == InvoiceType.PURCHASE
        )
    ).all()
    for item, inv in purch_items:
        purch_item_batches.add(item.batch_id)

    for b in batches:
        if b.id not in purch_item_batches:
            # Check if created from SELL_RETURN
            ret_item = db.execute(
                select(InvoiceItem).where(InvoiceItem.batch_id == b.id, InvoiceItem.original_invoice_item_id != None)
            ).scalar_one_or_none()
            if not ret_item:
                qty_in = Decimal(str(b.initial_quantity or 0))
                unit_cost = Decimal(str(b.purchase_price or 0))
                entries.append({
                    "date": b.created_at,
                    "movement_type": "OPENING_STOCK",
                    "reference": f"Initial Batch #{b.id}",
                    "product_id": product.id,
                    "product_name": product.name,
                    "qty_in": qty_in,
                    "qty_out": Decimal("0"),
                    "unit_cost": unit_cost,
                    "total_cost": qty_in * unit_cost,
                    "party_name": "Initial Inventory Setup"
                })

    # 2. Invoice Movements (PURCHASE, SALE, SELL_RETURN, PURCHASE_RETURN)
    invoice_items = db.execute(
        select(InvoiceItem, Invoice, StockBatch, Party)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .join(StockBatch, StockBatch.id == InvoiceItem.batch_id)
        .outerjoin(Party, Party.id == Invoice.party_id)
        .where(
            StockBatch.product_id == product_id,
            Invoice.tenant_id == tenant_id if tenant_id is not None else True
        ).order_by(Invoice.created_at.asc())
    ).all()

    for item, inv, batch, party in invoice_items:
        qty = Decimal(str(item.quantity or 0))
        cost = Decimal(str(item.purchase_price if item.purchase_price is not None else (batch.purchase_price or 0)))
        party_name = party.name if party else "N/A"

        if inv.invoice_type == InvoiceType.PURCHASE:
            entries.append({
                "date": inv.created_at,
                "movement_type": "PURCHASE",
                "reference": f"Purchase Invoice #{inv.id}",
                "product_id": product.id,
                "product_name": product.name,
                "qty_in": qty,
                "qty_out": Decimal("0"),
                "unit_cost": cost,
                "total_cost": qty * cost,
                "party_name": party_name
            })
        elif inv.invoice_type == InvoiceType.SELL:
            entries.append({
                "date": inv.created_at,
                "movement_type": "SALE",
                "reference": f"Sell Invoice #{inv.id}",
                "product_id": product.id,
                "product_name": product.name,
                "qty_in": Decimal("0"),
                "qty_out": qty,
                "unit_cost": cost,
                "total_cost": qty * cost,
                "party_name": party_name
            })
        elif inv.invoice_type == InvoiceType.SELL_RETURN:
            entries.append({
                "date": inv.created_at,
                "movement_type": "SELL_RETURN",
                "reference": f"Sell Return #{inv.id}",
                "product_id": product.id,
                "product_name": product.name,
                "qty_in": qty,
                "qty_out": Decimal("0"),
                "unit_cost": cost,
                "total_cost": qty * cost,
                "party_name": party_name
            })
        elif inv.invoice_type == InvoiceType.PURCHASE_RETURN:
            entries.append({
                "date": inv.created_at,
                "movement_type": "PURCHASE_RETURN",
                "reference": f"Purchase Return #{inv.id}",
                "product_id": product.id,
                "product_name": product.name,
                "qty_in": Decimal("0"),
                "qty_out": qty,
                "unit_cost": cost,
                "total_cost": qty * cost,
                "party_name": party_name
            })

    entries.sort(key=lambda x: x["date"])

    running_stock = Decimal("0")
    result = []
    for entry in entries:
        running_stock += entry["qty_in"] - entry["qty_out"]
        result.append({
            "date": entry["date"].strftime("%Y-%m-%d %H:%M"),
            "movement_type": entry["movement_type"],
            "reference": entry["reference"],
            "product_id": entry["product_id"],
            "product_name": entry["product_name"],
            "qty_in": float(entry["qty_in"]),
            "qty_out": float(entry["qty_out"]),
            "unit_cost": float(entry["unit_cost"]),
            "total_cost": float(entry["total_cost"]),
            "running_stock": float(running_stock),
            "party_name": entry["party_name"]
        })

    return result
