import sys
import os

from app.core.database import SessionLocal
from app.models.domain import InvoiceItem

db = SessionLocal()
items = db.query(InvoiceItem).filter(InvoiceItem.quantity <= 0).all()
print("Found items with quantity <= 0:")
for i in items:
    print(i.id, i.invoice_id, i.batch_id, i.quantity)
