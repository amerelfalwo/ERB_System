from app.core.database import SessionLocal
from sqlalchemy import text

def run():
    db = SessionLocal()
    try:
        db.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS default_footer_text TEXT;"))
        db.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS store_name VARCHAR;"))
        db.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS phone VARCHAR;"))
        db.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS address TEXT;"))
        db.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS tax_number VARCHAR;"))
        db.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS print_notes TEXT;"))
        db.commit()
        print("Migration successful")
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    run()
