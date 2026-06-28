import sys
import os

# Add the app directory to the sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.models.domain import User
from app.core.security import get_password_hash

def reset_password():
    db = SessionLocal()
    try:
        users = db.query(User).all()
        for user in users:
            if user.username == "amer003100@gmail.com":
                user.role = "super_admin"
                user.hashed_password = get_password_hash("123456")
            else:
                user.role = "admin" # Set other users back to normal admin
        db.commit()
        print("Set amer003100@gmail.com to super_admin and all other users to admin.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    reset_password()
