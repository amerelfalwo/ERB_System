from app.core.database import SessionLocal
from sqlalchemy import text


def run():
    db = SessionLocal()
    try:
        db.execute(text("""
        ALTER TABLE invoice_items
        ADD COLUMN IF NOT EXISTS original_invoice_item_id INTEGER;
        CREATE INDEX IF NOT EXISTS idx_invoice_items_original_invoice_item_id ON invoice_items (original_invoice_item_id);
        """))
        db.commit()
        print("Migration applied: original_invoice_item_id ensured")
    except Exception as e:
        print(f"Migration error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    run()
