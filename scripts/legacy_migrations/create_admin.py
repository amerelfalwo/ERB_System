import sys
import os

# Add backend directory to sys.path to allow imports
sys.path.append("/mnt/work/ERB/ERB_Backend")

from app.core.database import SessionLocal
from app.models.domain import User
from app.core.security import get_password_hash

def create_admin_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "admin").first()
        if not user:
            print("Creating admin user...")
            new_user = User(
                username="admin",
                hashed_password=get_password_hash("password")
            )
            db.add(new_user)
            db.commit()
            print("Admin user created (username: admin, password: password)")
        else:
            print("Admin user already exists")
    finally:
        db.close()

if __name__ == "__main__":
    create_admin_user()
