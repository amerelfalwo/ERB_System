from app.core.database import SessionLocal
from app.models.domain import InvoiceItem

db = SessionLocal()
items = db.query(InvoiceItem).filter(InvoiceItem.quantity <= 0).all()
deleted = 0
for i in items:
    db.delete(i)
    deleted += 1

db.commit()
print(f"Deleted {deleted} items with quantity <= 0")
