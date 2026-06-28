import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.models.domain import Invoice, InvoiceItem, InvoiceType, StockBatch, Payment, Party, PartyType
from sqlalchemy import select
from decimal import Decimal

def audit_system():
    db = SessionLocal()
    try:
        inconsistencies = 0
        
        # 1. Check Invoice Totals
        print("--- Checking Invoice Totals ---")
        invoices = db.execute(select(Invoice)).scalars().all()
        for inv in invoices:
            items = db.execute(select(InvoiceItem).where(InvoiceItem.invoice_id == inv.id)).scalars().all()
            if len(items) == 0:
                print(f"[INVOICE EMPTY] Invoice #{inv.id} (Type: {inv.invoice_type}) has no items.")
                inconsistencies += 1
                continue
                
            expected_total = sum(item.quantity * item.unit_price for item in items) + (inv.delivery_fee or Decimal(0))
            if abs(expected_total - inv.total_amount) > Decimal('0.01'):
                print(f"[TOTAL MISMATCH] Invoice #{inv.id} Total: {inv.total_amount}, Expected: {expected_total}")
                inconsistencies += 1
                
        # 2. Check Purchase Invoices vs StockBatches
        print("\n--- Checking Purchase Invoices vs StockBatches ---")
        purchase_items = db.execute(
            select(InvoiceItem)
            .join(Invoice)
            .where(Invoice.invoice_type == InvoiceType.PURCHASE)
        ).scalars().all()
        
        for item in purchase_items:
            if item.batch_id is None:
                print(f"[MISSING BATCH] Purchase InvoiceItem #{item.id} (Invoice #{item.invoice_id}) has no batch_id!")
                inconsistencies += 1
                continue
                
            batch = db.execute(select(StockBatch).where(StockBatch.id == item.batch_id)).scalar_one_or_none()
            if not batch:
                print(f"[ORPHAN BATCH ID] Purchase InvoiceItem #{item.id} refers to non-existent batch {item.batch_id}")
                inconsistencies += 1
                continue
                
            if batch.initial_quantity != item.quantity:
                print(f"[QTY MISMATCH] Purchase InvoiceItem #{item.id} Qty ({item.quantity}) != Batch #{batch.id} Initial Qty ({batch.initial_quantity})")
                inconsistencies += 1

        # 3. Check StockBatch Remaining Quantities
        print("\n--- Checking StockBatch Remaining Quantities ---")
        batches = db.execute(select(StockBatch)).scalars().all()
        for batch in batches:
            # Sell items
            sells = db.execute(
                select(InvoiceItem).join(Invoice).where(
                    InvoiceItem.batch_id == batch.id,
                    Invoice.invoice_type == InvoiceType.SELL
                )
            ).scalars().all()
            sell_qty = sum(item.quantity for item in sells)
            
            # Purchase Returns
            purch_returns = db.execute(
                select(InvoiceItem).join(Invoice).where(
                    InvoiceItem.batch_id == batch.id,
                    Invoice.invoice_type == InvoiceType.PURCHASE_RETURN
                )
            ).scalars().all()
            purch_ret_qty = sum(item.quantity for item in purch_returns)
            
            # Sell Returns
            sell_returns = db.execute(
                select(InvoiceItem).join(Invoice).where(
                    InvoiceItem.batch_id == batch.id,
                    Invoice.invoice_type == InvoiceType.SELL_RETURN
                )
            ).scalars().all()
            sell_ret_qty = sum(item.quantity for item in sell_returns)
            
            expected_remaining = batch.initial_quantity - sell_qty - purch_ret_qty + sell_ret_qty
            
            if batch.remaining_quantity != expected_remaining:
                print(f"[STOCK MISMATCH] Batch #{batch.id} (Product #{batch.product_id}): Actual Remaining = {batch.remaining_quantity}, Expected = {expected_remaining} (Initial: {batch.initial_quantity}, Sold: {sell_qty}, PurchRet: {purch_ret_qty}, SellRet: {sell_ret_qty})")
                inconsistencies += 1
                
        print(f"\n--- Audit Complete. Total Inconsistencies Found: {inconsistencies} ---")

    finally:
        db.close()

if __name__ == "__main__":
    audit_system()
