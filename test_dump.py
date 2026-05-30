import sys
import os
import json
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.domain import Product, StockBatch, InvoiceItem

engine = create_engine("sqlite:////mnt/work/ERB/ERB_Backend/erb_dev.db")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

products = db.query(Product).limit(5).all()
out = []
for p in products:
    batches = db.query(StockBatch).filter(StockBatch.product_id == p.id).all()
    out.append({
        "id": p.id,
        "name": p.name,
        "p_purchase": float(p.purchase_price or 0),
        "p_sell": float(p.sell_price or 0),
        "batches": [{
            "id": b.id,
            "purchase_price": float(b.purchase_price or 0),
            "current_selling_price": float(b.current_selling_price or 0),
            "rem_qty": float(b.remaining_quantity or 0)
        } for b in batches]
    })

with open("test_out.json", "w") as f:
    json.dump(out, f, indent=2)
