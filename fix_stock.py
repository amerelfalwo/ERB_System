import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.models.domain import Invoice, InvoiceItem, InvoiceType, StockBatch
from sqlalchemy import select
from decimal import Decimal

def fix_system_data():
    db = SessionLocal()
    try:
        # 1. Fix Invoice Totals
        print("--- Fixing Invoice Totals ---")
        invoices = db.execute(select(Invoice)).scalars().all()
        for inv in invoices:
            items = db.execute(select(InvoiceItem).where(InvoiceItem.invoice_id == inv.id)).scalars().all()
            if len(items) == 0:
                continue
                
            expected_total = sum(item.quantity * item.unit_price for item in items) + (inv.delivery_fee or Decimal(0))
            if abs(expected_total - inv.total_amount) > Decimal('0.01'):
                print(f"Fixing Invoice #{inv.id}: Updating Total from {inv.total_amount} to {expected_total}")
                inv.total_amount = expected_total
                db.add(inv)

        # 2. Fix StockBatch Quantities
        print("\n--- Fixing StockBatch Remaining Quantities ---")
        batches = db.execute(select(StockBatch)).scalars().all()
        for batch in batches:
            # Sold quantities
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
            
            # Note: Sell Returns create a NEW batch with their own Initial Quantity.
            # So we DO NOT add sell_ret_qty. The formula is simply:
            expected_remaining = batch.initial_quantity - sell_qty - purch_ret_qty
            
            if expected_remaining < 0:
                expected_remaining = Decimal('0.000') # Clamp to 0 if it goes negative to prevent stock issues
            
            if batch.remaining_quantity != expected_remaining:
                print(f"Fixing Batch #{batch.id} (Product #{batch.product_id}): Updating Remaining Qty from {batch.remaining_quantity} to {expected_remaining}")
                batch.remaining_quantity = expected_remaining
                db.add(batch)
                
        # Commit the changes
        db.commit()
        print("\n--- Fixes Applied Successfully ---")

    except Exception as e:
        db.rollback()
        print(f"An error occurred: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    fix_system_data()
