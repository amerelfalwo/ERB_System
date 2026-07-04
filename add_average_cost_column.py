import sys
import os

# Add the app directory to the sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE products ADD COLUMN average_cost NUMERIC(12, 2) DEFAULT 0;"))
        conn.commit()
        print("average_cost column added successfully to products table.")
    except Exception as e:
        print(f"Error adding average_cost (or it might already exist): {e}")

print("Done.")
