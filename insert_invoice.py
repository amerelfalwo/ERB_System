import os
import sys
from decimal import Decimal
from datetime import datetime

# Add the project root to the python path so we can import app modules
sys.path.insert(0, "/mnt/work/ERB/ERB_Backend")

from app.core.database import SessionLocal
from app.models.domain import Tenant, Party, PartyType, Product
from app.schemas.invoice import InvoiceCreatePurchase, InvoiceItemCreatePurchase
from app.services.invoice_service import create_purchase_invoice_svc
from app.repositories.invoice import InvoiceRepository
from app.repositories.batch import BatchRepository

def main():
    db = SessionLocal()
    try:
        # Get or create a tenant
        tenant = db.query(Tenant).first()
        if not tenant:
            tenant = Tenant(company_name="Test Company")
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
        
        tenant_id = tenant.id

        # Get or create a supplier
        supplier_name = "Default Supplier"
        supplier = db.query(Party).filter(Party.tenant_id == tenant_id, Party.name == supplier_name, Party.party_type == PartyType.SUPPLIER).first()
        if not supplier:
            supplier = Party(tenant_id=tenant_id, name=supplier_name, party_type=PartyType.SUPPLIER)
            db.add(supplier)
            db.commit()
            db.refresh(supplier)
        
        items_data = [
            {"total": Decimal("385.00"), "qty": Decimal("1"), "name": "Clamp KSK 26"},
            {"total": Decimal("1660.00"), "qty": Decimal("10"), "name": "gloves skin tec pro Blue M"},
            {"total": Decimal("43.00"), "qty": Decimal("1"), "name": "Gas Torch"},
            {"total": Decimal("78.00"), "qty": Decimal("1"), "name": "Tor Vm Celluloid strips"},
            {"total": Decimal("45.00"), "qty": Decimal("1"), "name": "Cover contra Silicone"},
            {"total": Decimal("35.00"), "qty": Decimal("2"), "name": "Suture prolene 3/0 piece"},
            {"total": Decimal("240.00"), "qty": Decimal("1"), "name": "Sterilization Roll 7.5 cm"},
            {"total": Decimal("122.00"), "qty": Decimal("1"), "name": "Polishing Nylon Brush"},
            {"total": Decimal("690.00"), "qty": Decimal("1"), "name": "Cavex Temp Cement"},
            {"total": Decimal("960.00"), "qty": Decimal("2"), "name": "Tor Vm Polishing Discs 80pcs"},
            {"total": Decimal("160.00"), "qty": Decimal("20"), "name": "Easy Smile Wire NITTI"},
            {"total": Decimal("1235.00"), "qty": Decimal("1"), "name": "Tetric N-Ceram 2 Refill 3.5 Gr A1"},
            {"total": Decimal("1475.00"), "qty": Decimal("1"), "name": "Tetric N-Ceram 2 Refill 3.5 Gr Bleach XL"},
        ]

        invoice_items = []
        for item in items_data:
            # Find or create product
            product = db.query(Product).filter(Product.tenant_id == tenant_id, Product.name == item["name"]).first()
            if not product:
                product = Product(tenant_id=tenant_id, name=item["name"])
                db.add(product)
                db.commit()
                db.refresh(product)
            
            unit_price = item["total"] / item["qty"]
            
            invoice_items.append(InvoiceItemCreatePurchase(
                product_id=product.id,
                quantity=item["qty"],
                purchase_price=unit_price,
                sell_price=unit_price * Decimal("1.2"), # Placeholder sell price
                discount=Decimal("0"),
                tax=Decimal("0")
            ))
        
        invoice_data = InvoiceCreatePurchase(
            party_id=supplier.id,
            items=invoice_items,
            amount_paid=Decimal("0"),
            delivery_fee=Decimal("0"),
            total_discount=Decimal("0"),
            total_tax=Decimal("0"),
            notes="Bulk import invoice"
        )
        
        invoice_repo = InvoiceRepository()
        batch_repo = BatchRepository()
        
        created_invoice = create_purchase_invoice_svc(db, invoice_repo, batch_repo, invoice_data, tenant_id)
        db.commit()
        print(f"Successfully created purchase invoice ID: {created_invoice.id}")
        
    except Exception as e:
        db.rollback()
        print(f"Error: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
