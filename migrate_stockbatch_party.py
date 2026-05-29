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
        WHERE table_name = 'stock_batches';
    """)
    columns = [row[0] for row in cursor.fetchall()]
    print(f"Current columns in stock_batches: {columns}")
    
    # 2. Add column if missing
    if "party_id" not in columns:
        print("party_id column is missing. Adding it...")
        cursor.execute("""
            ALTER TABLE stock_batches 
            ADD COLUMN party_id INTEGER REFERENCES parties(id) NULL;
        """)
        cursor.execute("""
            CREATE INDEX ix_stock_batches_party_id ON stock_batches (party_id);
        """)
        print("Successfully added party_id column!")
    else:
        print("party_id already exists.")
        
except Exception as e:
    print(f"Error during migration: {e}")
finally:
    cursor.close()
    conn.close()
