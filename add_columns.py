import sys
import os

# Add the app directory to the sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE tenants ADD COLUMN created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;"))
        conn.commit()
        print("created_at column added successfully.")
    except Exception as e:
        print(f"Error adding created_at (or it might already exist): {e}")

    try:
        conn.execute(text("ALTER TABLE tenants ADD COLUMN address TEXT;"))
        conn.commit()
        print("address column added successfully.")
    except Exception as e:
        print(f"Error adding address (or it might already exist): {e}")

print("Done trying to add remaining missing columns.")
