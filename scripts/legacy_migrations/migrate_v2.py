"""
Migration: Add delivery_fee, footer_custom_text to invoices;
           purchase_price, sale_price to invoice_items (if not present).
Run: .venv/bin/python migrate_v2.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from app.core.config import settings
import psycopg2
from urllib.parse import urlparse

def run():
    url = urlparse(settings.DATABASE_URL)
    conn = psycopg2.connect(
        dbname=url.path.lstrip('/'), user=url.username,
        password=url.password, host=url.hostname, port=url.port or 5432,
    )
    conn.autocommit = True
    cur = conn.cursor()

    migrations = [
        ("invoices", "delivery_fee",         "NUMERIC(12,2) DEFAULT 0"),
        ("invoices", "footer_custom_text",    "TEXT"),
        ("invoice_items", "purchase_price",   "NUMERIC(12,2)"),
        ("invoice_items", "sale_price",       "NUMERIC(12,2)"),
        ("tenants", "default_footer_text",    "TEXT"),
        ("tenants", "phone",                  "VARCHAR"),
        ("tenants", "address",                "TEXT"),
        ("tenants", "tax_number",             "VARCHAR"),
    ]

    for table, col, col_type in migrations:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name=%s AND column_name=%s;
        """, (table, col))
        if not cur.fetchone():
            cur.execute(f'ALTER TABLE {table} ADD COLUMN "{col}" {col_type};')
            print(f"  ✓ {table}.{col} added")
        else:
            print(f"  · {table}.{col} already exists")

    cur.close()
    conn.close()
    print("\nMigration v2 complete.")

if __name__ == "__main__":
    run()
