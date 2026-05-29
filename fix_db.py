from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()
db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("No DATABASE_URL")
    exit(1)

engine = create_engine(db_url)
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE invoice_items ALTER COLUMN original_invoice_item_id DROP NOT NULL;"))
    print("Successfully dropped NOT NULL constraint on original_invoice_item_id")
