import sys
import os

# Add the app directory to the sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.models.domain import User

def check_user():
    db = SessionLocal()
    try:
        users = db.query(User).all()
        print("Users in database:")
        for u in users:
            print(f"- Username: {u.username}, Role: {u.role}, Tenant ID: {u.tenant_id}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    check_user()
