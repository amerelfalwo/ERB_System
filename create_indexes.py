import asyncio
from sqlalchemy import text
from app.core.database import SessionLocal

db = SessionLocal()
try:
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_payment_party_amount ON payments (party_id, amount);"))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_invoice_party_type_total ON invoices (party_id, invoice_type, total_amount);"))
    db.commit()
    print("Indexes created successfully.")
except Exception as e:
    print(f"Error: {e}")
finally:
    db.close()
