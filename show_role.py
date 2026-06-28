import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app.core.database import SessionLocal
from app.models.domain import User

def show_role():
    db = SessionLocal()
    user = db.query(User).filter(User.username == "amer003100@gmail.com").first()
    if user:
        print(f"Role for {user.username} is: {user.role}")
    else:
        print("User not found")
    db.close()

if __name__ == "__main__":
    show_role()
