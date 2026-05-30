import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import engine, SessionLocal
from app.repositories.base import InvoiceRepository, BatchRepository, PaymentRepository
from app.services.invoice_service import create_purchase_invoice_svc, delete_invoice_svc
from app.schemas.invoice import InvoiceCreatePurchase, InvoiceItemCreatePurchase
from decimal import Decimal
from app.models.domain import Party, Product, Tenant

def test():
    db = SessionLocal()
    tenant = db.query(Tenant).first()
    if not tenant:
        print("No tenant")
        return
    party = db.query(Party).filter_by(tenant_id=tenant.id).first()
    product = db.query(Product).filter_by(tenant_id=tenant.id).first()
    if not party or not product:
        print("No party or product")
        return

    inv_repo = InvoiceRepository(db, tenant.id)
    batch_repo = BatchRepository(db, tenant.id)
    
    data = InvoiceCreatePurchase(
        party_id=party.id,
        items=[InvoiceItemCreatePurchase(
            product_id=product.id,
            quantity=Decimal("10"),
            purchase_price=Decimal("100"),
            selling_price=Decimal("150")
        )],
        amount_paid=Decimal("0"),
        delivery_fee=Decimal("0")
    )
    
    try:
        inv = create_purchase_invoice_svc(db, inv_repo, batch_repo, data, tenant.id)
        print(f"Created invoice: {inv.id}")
        
        # Now try to delete it
        delete_invoice_svc(inv_repo, batch_repo, inv)
        print("Deleted successfully!")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    test()
