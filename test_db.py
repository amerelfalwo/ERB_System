from app.core.database import SessionLocal
from app.models.domain import Party, Invoice, InvoiceItem
from decimal import Decimal

db = SessionLocal()
party = db.query(Party).filter(Party.id == 32).first()
if not party:
    print("Customer 32 not found.")
else:
    invoices = db.query(Invoice).filter(Invoice.party_id == 32).all()
    print(f"Customer {party.name} has {len(invoices)} invoices")
    for inv in invoices:
        print(f"Invoice {inv.id} type {inv.invoice_type.value} total {inv.total_amount}")
        for item in inv.items:
            print(f"  Item {item.id} qty {item.quantity} cost {item.purchase_price} batch_cost {item.batch.purchase_price if item.batch else 'None'} sell {item.sell_price} unit {item.unit_price}")
