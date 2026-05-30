import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.api.products import list_products
from app.models.domain import User

engine = create_engine("sqlite:////mnt/work/ERB/ERB_Backend/erb_dev.db")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()
user = db.query(User).first()
if user:
    products = list_products(skip=0, limit=100, db=db, current_user=user)
    for p in products:
        print(f"Product {p.id}: {p.name} - Purchase: {p.purchase_price} - Sell: {p.sell_price}")
else:
    print("No user found")
