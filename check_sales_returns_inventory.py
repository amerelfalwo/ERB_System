import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.models.domain import Invoice, InvoiceItem, InvoiceType
from sqlalchemy import select
from decimal import Decimal

def check_sales_returns():
    db = SessionLocal()
    try:
        # Check SELL invoices
        sell_invoices = db.execute(
            select(Invoice).where(Invoice.invoice_type == InvoiceType.SELL)
        ).scalars().all()
        
        # Check SELL_RETURN invoices
        sell_returns = db.execute(
            select(Invoice).where(Invoice.invoice_type == InvoiceType.SELL_RETURN)
        ).scalars().all()
        
        # Check PURCHASE_RETURN invoices
        purchase_returns = db.execute(
            select(Invoice).where(Invoice.invoice_type == InvoiceType.PURCHASE_RETURN)
        ).scalars().all()
        
        print(f"Found {len(sell_invoices)} SELL invoices")
        print(f"Found {len(sell_returns)} SELL_RETURN invoices")
        print(f"Found {len(purchase_returns)} PURCHASE_RETURN invoices")
        
        inconsistencies_found = 0
        
        for inv_type, invoices in [("SELL", sell_invoices), ("SELL_RETURN", sell_returns), ("PURCHASE_RETURN", purchase_returns)]:
            for inv in invoices:
                items = db.execute(select(InvoiceItem).where(InvoiceItem.invoice_id == inv.id)).scalars().all()
                
                if len(items) == 0:
                    print(f"[INCONSISTENCY] {inv_type} Invoice #{inv.id} has NO items attached to it!")
                    inconsistencies_found += 1
                
                for item in items:
                    if item.batch_id is None:
                        print(f"[INCONSISTENCY] {inv_type} Invoice #{inv.id}, Item #{item.id} is missing a batch_id!")
                        inconsistencies_found += 1
                    if item.quantity <= 0:
                        print(f"[INCONSISTENCY] {inv_type} Invoice #{inv.id}, Item #{item.id} has quantity <= 0 ({item.quantity})!")
                        inconsistencies_found += 1

        if inconsistencies_found == 0:
            print("\n--- NO INCONSISTENCIES FOUND IN SALES/RETURNS ---")
        else:
            print(f"\n--- FOUND {inconsistencies_found} INCONSISTENCIES IN SALES/RETURNS ---")

    finally:
        db.close()

if __name__ == "__main__":
    check_sales_returns()
