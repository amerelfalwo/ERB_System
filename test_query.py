import sys
from app.core.database import SessionLocal
from app.models.domain import User, Tenant, Product, Party
from sqlalchemy import select

def main():
    with SessionLocal() as db:
        users = db.execute(select(User)).scalars().all()
        print("Users:", [{"id": u.id, "email": u.email, "tenant_id": u.tenant_id} for u in users])
        
        tenants = db.execute(select(Tenant)).scalars().all()
        print("Tenants:", [{"id": t.id, "name": t.name} for t in tenants])
        
        products = db.execute(select(Product)).scalars().all()
        print("Products:", [{"id": p.id, "name": p.name, "tenant_id": p.tenant_id} for p in products])
        
        parties = db.execute(select(Party)).scalars().all()
        print("Parties:", [{"id": p.id, "name": p.name, "tenant_id": p.tenant_id} for p in parties])

if __name__ == "__main__":
    main()
