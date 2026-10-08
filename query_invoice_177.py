import sys
import os
from pprint import pprint

from app.core.database import SessionLocal
from app.models.domain import Invoice, InvoiceItem

db = SessionLocal()
invoice = db.query(Invoice).filter(Invoice.id == 177).first()
print(f"Invoice 177 Type: {invoice.invoice_type}")
for i in invoice.items:
    print(f"ID: {i.id}, Batch: {i.batch_id}, Qty: {i.quantity}, Unit Price: {i.unit_price}, Product: {i.batch.product.name if i.batch else 'None'}")

