import asyncio
from sqlalchemy import text
from app.core.database import SessionLocal

def run():
    db = SessionLocal()
    try:
        # Enable pg_trgm extension
        db.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        db.commit()
        print("pg_trgm extension enabled.")

        # Parties indexes
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_parties_name_trgm ON parties USING gin (name gin_trgm_ops);"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_parties_phone_trgm ON parties USING gin (phone gin_trgm_ops);"))
        
        # Normalized Arabic Name Index for Parties
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_parties_name_norm_trgm ON parties USING gin (
                replace(replace(replace(replace(replace(lower(name), 'أ', 'ا'), 'إ', 'ا'), 'آ', 'ا'), 'ة', 'ه'), 'ى', 'ي') gin_trgm_ops
            );
        """))

        # Products indexes
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_products_name_trgm ON products USING gin (name gin_trgm_ops);"))
        
        # Normalized Arabic Name Index for Products
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_products_name_norm_trgm ON products USING gin (
                replace(replace(replace(replace(replace(lower(name), 'أ', 'ا'), 'إ', 'ا'), 'آ', 'ا'), 'ة', 'ه'), 'ى', 'ي') gin_trgm_ops
            );
        """))

        db.commit()
        print("Search indexes created successfully.")
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    run()
