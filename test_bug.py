import sys
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.domain import Tenant, User, Party, PartyType, Product, Invoice, InvoiceItem, StockBatch, InvoiceType
from app.schemas.invoice import InvoiceCreatePurchase, InvoiceItemCreatePurchase
from app.services.invoice_service import create_purchase_invoice_svc
from app.repositories.base import InvoiceRepository, BatchRepository
from app.services.reports import inventory_report

engine = create_engine("sqlite:///./erb.db")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

# Setup test data
tenant = db.query(Tenant).first()
if not tenant:
    tenant = Tenant(company_name="Test")
    db.add(tenant)
    db.commit()

party = db.query(Party).filter_by(tenant_id=tenant.id, party_type=PartyType.SUPPLIER).first()
if not party:
    party = Party(name="Supplier 1", party_type=PartyType.SUPPLIER, tenant_id=tenant.id)
    db.add(party)
    db.commit()

# Create a new product (like the frontend does)
product = Product(name="Test New Product", tenant_id=tenant.id, purchase_price=0, sell_price=0)
db.add(product)
db.commit()

# Create purchase invoice
data = InvoiceCreatePurchase(
    party_id=party.id,
    delivery_fee=0,
    amount_paid=0,
    footer_custom_text=None,
    items=[
        InvoiceItemCreatePurchase(
            product_id=product.id,
            quantity=10,
            purchase_price=5,
            sell_price=10
        )
    ]
)

invoice_repo = InvoiceRepository(db, tenant.id)
batch_repo = BatchRepository(db, tenant.id)

invoice = create_purchase_invoice_svc(invoice_repo, batch_repo, data, tenant.id)
print("Invoice ID:", invoice.id)

# Check inventory
report = inventory_report(db, tenant.id)
for item in report.products:
    if item.product_id == product.id:
        print("Inventory product found:", item.product_name)
        for b in item.batches:
            print("  Batch:", b.batch_id, "Qty:", b.remaining_quantity)
