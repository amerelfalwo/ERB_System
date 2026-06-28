import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.models.domain import Invoice, InvoiceItem, StockBatch, InvoiceType
from sqlalchemy import select
from decimal import Decimal

def verify_inventory():
    db = SessionLocal()
    try:
        batches = db.execute(select(StockBatch)).scalars().all()
        print(f"Analyzing {len(batches)} stock batches...")
        
        inconsistencies_found = 0
        
        for batch in batches:
            # All items that created stock (Purchase or Sell Return)
            stock_in_items = db.execute(
                select(InvoiceItem)
                .join(Invoice)
                .where(InvoiceItem.batch_id == batch.id)
                .where(Invoice.invoice_type.in_([InvoiceType.PURCHASE, InvoiceType.SELL_RETURN]))
            ).scalars().all()
            
            # All items that reduced stock (Sell or Purchase Return)
            stock_out_items = db.execute(
                select(InvoiceItem)
                .join(Invoice)
                .where(InvoiceItem.batch_id == batch.id)
                .where(Invoice.invoice_type.in_([InvoiceType.SELL, InvoiceType.PURCHASE_RETURN]))
            ).scalars().all()
            
            expected_initial = sum((item.quantity for item in stock_in_items), Decimal("0"))
            expected_sold = sum((item.quantity for item in stock_out_items), Decimal("0"))
            expected_remaining = expected_initial - expected_sold
            
            actual_initial = Decimal(str(batch.initial_quantity))
            actual_remaining = Decimal(str(batch.remaining_quantity))
            actual_sold = actual_initial - actual_remaining
            
            if expected_initial != actual_initial or expected_sold != actual_sold:
                inconsistencies_found += 1
                print(f"\n[INCONSISTENCY] Batch #{batch.id} (Product #{batch.product_id}):")
                if expected_initial != actual_initial:
                    print(f"  -> Initial Qty Mismatch: Expected {expected_initial}, found {actual_initial}")
                if expected_sold != actual_sold:
                    print(f"  -> Sold/Out Qty Mismatch: Expected {expected_sold} based on invoices, but batch shows {actual_sold} sold")
                print(f"  -> Remaining Qty Mismatch: Expected {expected_remaining}, found {actual_remaining}")
                
        # Also check if there are any invoice items missing a batch
        items_without_batch = db.execute(
            select(InvoiceItem).where(InvoiceItem.batch_id == None)
        ).scalars().all()
        
        if items_without_batch:
            print(f"\n[WARNING] Found {len(items_without_batch)} invoice items completely missing a batch link!")
            inconsistencies_found += 1
            for i in items_without_batch:
                print(f"  -> Item #{i.id} on Invoice #{i.invoice_id} missing batch.")

        if inconsistencies_found == 0:
            print("\n--- ALL BATCHES AND INVOICE ITEMS ARE 100% IN SYNC ---")
        else:
            print(f"\n--- FOUND {inconsistencies_found} INCONSISTENCIES ---")
            
    finally:
        db.close()

if __name__ == "__main__":
    verify_inventory()
