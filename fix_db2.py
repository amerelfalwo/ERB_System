import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("No DATABASE_URL found.")
    exit(1)

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE invoice_items ALTER COLUMN original_invoice_item_id DROP NOT NULL;")
    print("Successfully dropped NOT NULL constraint on original_invoice_item_id.")
except Exception as e:
    print(f"Error: {e}")
finally:
    cursor.close()
    conn.close()
