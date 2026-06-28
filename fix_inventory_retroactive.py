import sys
import os

# Add ERB_Backend to path so imports work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.models.domain import Invoice, InvoiceItem, StockBatch, Product
from sqlalchemy import select
from decimal import Decimal
from app.core.constants import INVOICE_TYPE_PURCHASE

def fix_inventory_retroactive():
    db = SessionLocal()
    try:
        # Get all purchase invoices
        purchase_invoices = db.execute(
            select(Invoice).where(Invoice.invoice_type == INVOICE_TYPE_PURCHASE)
        ).scalars().all()
        
        if not purchase_invoices:
            print("No purchase invoices found in the system.")
            return
            
        print(f"Found {len(purchase_invoices)} purchase invoices. Starting verification...")
        
        missing_batches_created = 0
        batches_adjusted = 0
        total_quantity_added = Decimal("0")
        
        for inv in purchase_invoices:
            items = db.execute(
                select(InvoiceItem).where(InvoiceItem.invoice_id == inv.id)
            ).scalars().all()
            
            for item in items:
                # 1. If batch is missing, create it entirely
                batch_exists = False
                batch = None
                if item.batch_id:
                    batch = db.execute(select(StockBatch).where(StockBatch.id == item.batch_id)).scalar_one_or_none()
                    batch_exists = batch is not None
                    
                if not batch_exists:
                    print(f"[MISSING BATCH] Invoice #{inv.id} | Item #{item.id} | Product #{item.product_id}")
                    product = db.execute(select(Product).where(Product.id == item.product_id)).scalar_one_or_none()
                    if not product:
                        print(f"  -> Product #{item.product_id} not found, skipping.")
                        continue
                        
                    purchase_price = item.purchase_price or item.unit_price or product.purchase_price or Decimal("0")
                    sell_price = item.sell_price or product.sell_price or Decimal("0")
                    
                    batch = StockBatch(
                        product_id=item.product_id,
                        purchase_price=purchase_price,
                        current_selling_price=sell_price,
                        initial_quantity=item.quantity,
                        remaining_quantity=item.quantity,
                        tenant_id=inv.tenant_id,
                        party_id=inv.party_id,
                    )
                    db.add(batch)
                    db.flush()
                    
                    item.batch_id = batch.id
                    db.add(item)
                    missing_batches_created += 1
                    total_quantity_added += Decimal(str(item.quantity))
                    print(f"  -> Created new batch #{batch.id} with quantity {item.quantity}")
                
                # 2. If batch exists, verify if quantities match
                else:
                    item_qty = Decimal(str(item.quantity))
                    batch_initial_qty = Decimal(str(batch.initial_quantity))
                    
                    if item_qty > batch_initial_qty:
                        diff = item_qty - batch_initial_qty
                        print(f"[QTY MISMATCH] Invoice #{inv.id} | Batch #{batch.id} | Product #{item.product_id}")
                        print(f"  -> Invoice Qty: {item_qty}, Batch Initial Qty: {batch_initial_qty}. Missing: {diff}")
                        
                        # Adjust batch
                        batch.initial_quantity = item_qty
                        batch.remaining_quantity = Decimal(str(batch.remaining_quantity)) + diff
                        db.add(batch)
                        
                        batches_adjusted += 1
                        total_quantity_added += diff
                        print(f"  -> Adjusted batch #{batch.id} remaining quantity by +{diff}")
                        
        if missing_batches_created > 0 or batches_adjusted > 0:
            db.commit()
            print("\n--- FIX COMPLETED SUCCESSFULLY ---")
            print(f"Missing Batches Created: {missing_batches_created}")
            print(f"Existing Batches Adjusted: {batches_adjusted}")
            print(f"Total Quantity Restored to Inventory: {total_quantity_added}")
        else:
            print("\n--- INVENTORY IS ALREADY 100% ACCURATE ---")
            print("No missing quantities found.")
            
    except Exception as e:
        db.rollback()
        print(f"An error occurred: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    fix_inventory_retroactive()
