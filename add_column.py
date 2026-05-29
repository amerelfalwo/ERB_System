import os
import psycopg2
from dotenv import load_dotenv

# Load env from .env
load_dotenv("/mnt/work/ERB/ERB_Backend/.env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("No DATABASE_URL found.")
    exit(1)

print(f"Connecting to: {DATABASE_URL}")
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cursor = conn.cursor()

try:
    # 1. Inspect existing columns
    cursor.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'invoice_items';
    """)
    columns = [row[0] for row in cursor.fetchall()]
    print(f"Current columns in invoice_items: {columns}")
    
    # 2. Add column if missing
    if "original_invoice_item_id" not in columns:
        print("original_invoice_item_id column is missing. Adding it...")
        cursor.execute("""
            ALTER TABLE invoice_items 
            ADD COLUMN original_invoice_item_id INTEGER REFERENCES invoice_items(id) NULL;
        """)
        print("Successfully added original_invoice_item_id column!")
    else:
        print("original_invoice_item_id already exists.")
        
except Exception as e:
    print(f"Error during migration: {e}")
finally:
    cursor.close()
    conn.close()
