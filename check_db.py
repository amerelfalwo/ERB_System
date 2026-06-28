 from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.domain import StockBatch, Invoice, InvoiceItem

db = SessionLocal()
print("Total Stock Batches:", db.query(StockBatch).count())
print("Total Invoices:", db.query(Invoice).count())
print("Purchase Invoices:", db.query(Invoice).filter(Invoice.invoice_type == "purchase").count())

invoices = db.query(Invoice).filter(Invoice.invoice_type == "purchase").order_by(Invoice.id.desc()).limit(1).all()
if invoices:
    inv = invoices[0]
    print(f"Latest Purchase Invoice: {inv.id}")
    items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == inv.id).all()
    for item in items:
        print(f" - Item: {item.id}, product_id: {item.product_id}, batch_id: {item.batch_id}")
        if item.batch_id:
            batch = db.query(StockBatch).filter(StockBatch.id == item.batch_id).first()
            if batch:
                print(f"   -> Batch: {batch.id}, rem_qty: {batch.remaining_quantity}, tenant_id: {batch.tenant_id}")
            else:
                print(f"   -> Batch NOT FOUND!")
else:
    print("No purchase invoices")

db.close()
