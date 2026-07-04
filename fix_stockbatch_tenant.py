import os, sys, pathlib
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

env_path = pathlib.Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

DATABASE_URL = os.environ.get("DATABASE_URL", "")
engine = create_engine(DATABASE_URL, echo=False)

from app.models.domain import StockBatch, Product

with Session(engine) as db:
    batches = db.execute(
        select(StockBatch).where(StockBatch.tenant_id.is_(None))
    ).scalars().all()
    
    print(f"Found {len(batches)} batches without tenant_id.")
    
    count = 0
    for batch in batches:
        product = db.get(Product, batch.product_id)
        if product and product.tenant_id:
            batch.tenant_id = product.tenant_id
            count += 1
            
    db.commit()
    print(f"Updated {count} batches with tenant_id.")
