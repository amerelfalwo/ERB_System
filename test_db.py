import asyncio
from app.core.database import engine
from sqlalchemy import text

def check_db():
    with engine.connect() as conn:
        res = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'invoices';"))
        columns = [r[0] for r in res]
        print("Columns in invoices:", columns)

if __name__ == "__main__":
    check_db()
