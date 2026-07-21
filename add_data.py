import sys
import os
from datetime import datetime, timezone
from decimal import Decimal

# Add current directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.models.domain import User, Tenant, Product, Party, Invoice, InvoiceItem, StockBatch, InvoiceType, PartyType
from sqlalchemy import select

def main():
    items = [
        {"total": "385.00", "qty": "1", "item": "Clamp KSK 26"},
        {"total": "1660.00", "qty": "10", "item": "gloves skin tec pro Blue M"},
        {"total": "43.00", "qty": "1", "item": "Gas Torch"},
        {"total": "78.00", "qty": "1", "item": "Tor Vm Celluloid strips"},
        {"total": "45.00", "qty": "1", "item": "Cover contra Silicone"},
        {"total": "35.00", "qty": "2", "item": "Suture prolene 3/0 piece"},
        {"total": "240.00", "qty": "1", "item": "Sterilization Roll 7.5 cm"},
        {"total": "122.00", "qty": "1", "item": "Polishing Nylon Brush"},
        {"total": "690.00", "qty": "1", "item": "Cavex Temp Cement"},
        {"total": "960.00", "qty": "2", "item": "Tor Vm Polishing Discs 80pcs"},
        {"total": "160.00", "qty": "20", "item": "Easy Smile Wire NITTI"},
        {"total": "1235.00", "qty": "1", "item": "Tetric N-Ceram 2 Refill 3.5 Gr A1"},
        {"total": "1475.00", "qty": "1", "item": "Tetric N-Ceram 2 Refill 3.5 Gr Bleach XL"},
    ]

    with SessionLocal() as db:
        # Find the user
        user = db.execute(select(User).where(User.username == "testuser@example.com")).scalars().first()
        if not user:
            print("User testuser@example.com not found!")
            user = db.execute(select(User)).scalars().first()
            if not user:
                print("No users found in database.")
                return
            print(f"Using alternative user: {user.username}")
            
        tenant_id = user.tenant_id
        
        # Get or create a supplier Party
        supplier = db.execute(
            select(Party).where(Party.tenant_id == tenant_id, Party.party_type == PartyType.SUPPLIER)
        ).scalars().first()
        
        if not supplier:
            supplier = Party(
                tenant_id=tenant_id,
                name="Dental Supplier Inc.",
                party_type=PartyType.SUPPLIER,
                phone="123456789",
                address="Supplier Address"
            )
            db.add(supplier)
            db.flush()
            print(f"Created supplier: {supplier.name}")
            
        # Create a purchase invoice
        invoice = Invoice(
            tenant_id=tenant_id,
            party_id=supplier.id,
            invoice_type=InvoiceType.PURCHASE,
            total_amount=0,
            subtotal=0,
            reference_number="PUR-DENTAL-001"
        )
        db.add(invoice)
        db.flush()
        
        grand_total = Decimal('0')
        
        for data in items:
            name = data["item"]
            qty = Decimal(data["qty"])
            total_price = Decimal(data["total"])
            unit_price = total_price / qty
            
            # Find or create product
            product = db.execute(
                select(Product).where(Product.tenant_id == tenant_id, Product.name == name)
            ).scalars().first()
            
            if not product:
                product = Product(
                    tenant_id=tenant_id, 
                    name=name, 
                    last_purchase_price=unit_price, 
                    purchase_price=unit_price,
                    average_cost=unit_price,
                    sell_price=unit_price * Decimal('1.5')  # arbitrary markup
                )
                db.add(product)
                db.flush()
                
            # Create stock batch for each product
            batch = StockBatch(
                tenant_id=tenant_id,
                product_id=product.id,
                party_id=supplier.id,
                purchase_price=unit_price,
                current_selling_price=product.sell_price,
                initial_quantity=qty,
                remaining_quantity=qty
            )
            db.add(batch)
            db.flush()
            
            # Create invoice item
            inv_item = InvoiceItem(
                invoice_id=invoice.id,
                batch_id=batch.id,
                quantity=qty,
                unit_price=unit_price,
                purchase_price=unit_price
            )
            db.add(inv_item)
            grand_total += total_price
            
        invoice.subtotal = grand_total
        invoice.total_amount = grand_total
        
        db.commit()
        print(f"Successfully created Purchase Invoice #{invoice.id} with total amount {invoice.total_amount}")

if __name__ == "__main__":
    main()
