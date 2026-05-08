from app.core.database import SessionLocal
from sqlalchemy import text

def run():
    db = SessionLocal()
    try:
        db.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS delivery_fee NUMERIC(10, 2);"))
        db.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS footer_custom_text TEXT;"))
        db.execute(text("ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS purchase_price NUMERIC(10, 2);"))
        db.execute(text("ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS sale_price NUMERIC(10, 2);"))
        db.commit()
        print("Migration successful")
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    run()
