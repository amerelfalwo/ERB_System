"""
Migration: Add initial_balance column to parties table.

Run with:  uv run python add_initial_balance.py
"""
from app.core.database import SessionLocal
from sqlalchemy import text


def run():
    db = SessionLocal()
    try:
        db.execute(text(
            "ALTER TABLE parties ADD COLUMN IF NOT EXISTS initial_balance NUMERIC(12, 2) DEFAULT 0;"
        ))
        db.commit()
        print("✅  Migration successful: parties.initial_balance added.")
    except Exception as e:
        print(f"❌  Error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    run()
