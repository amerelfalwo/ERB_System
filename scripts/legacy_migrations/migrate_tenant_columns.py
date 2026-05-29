"""
Migration: Add missing columns to tenants table.
Run from /mnt/work/ERB/ERB_Backend:
    .venv/bin/python migrate_tenant_columns.py
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from app.core.config import settings
import psycopg2
from urllib.parse import urlparse

def run():
    url = urlparse(settings.DATABASE_URL)
    conn = psycopg2.connect(
        dbname=url.path.lstrip('/'),
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port or 5432,
    )
    conn.autocommit = True
    cur = conn.cursor()

    columns = [
        ("default_footer_text", "TEXT"),
        ("phone",               "VARCHAR"),
        ("address",             "TEXT"),
        ("tax_number",          "VARCHAR"),
    ]

    for col, col_type in columns:
        # Check if column already exists
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'tenants' AND column_name = %s;
        """, (col,))
        exists = cur.fetchone()
        if not exists:
            cur.execute(f'ALTER TABLE tenants ADD COLUMN "{col}" {col_type};')
            print(f"  ✓ Added column: {col}")
        else:
            print(f"  ✓ Column already exists: {col}")

    cur.close()
    conn.close()
    print("\nMigration complete.")

if __name__ == "__main__":
    run()
