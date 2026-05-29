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
    # 1. Add notes and credit_limit if missing
    cursor.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'parties';
    """)
    columns = [row[0] for row in cursor.fetchall()]
    print(f"Current columns in parties: {columns}")
    
    if "notes" not in columns:
        print("notes column is missing. Adding it...")
        cursor.execute("ALTER TABLE parties ADD COLUMN notes TEXT;")
        print("Successfully added notes column!")
    else:
        print("notes column already exists.")

    if "credit_limit" not in columns:
        print("credit_limit column is missing. Adding it...")
        cursor.execute("ALTER TABLE parties ADD COLUMN credit_limit NUMERIC(12, 2) DEFAULT 0.00;")
        print("Successfully added credit_limit column!")
    else:
        print("credit_limit column already exists.")
        
except Exception as e:
    print(f"Error during migration: {e}")
finally:
    cursor.close()
    conn.close()
