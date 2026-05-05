from decimal import Decimal

from dotenv import load_dotenv

print("Loading env...")
load_dotenv()

from app.core.database import SessionLocal, engine
from app.models import Base
from app.models.domain import Invoice, InvoiceItem, InvoiceType, Party, PartyType, Payment, Product, StockBatch


def main():
    print("Connecting to DB...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print("Inserting data...")
        supplier = Party(name="TechMakers Mansoura", party_type=PartyType.SUPPLIER)
        client = Party(name="Smart Vision Center", party_type=PartyType.CLIENT)
        db.add_all([supplier, client])
        db.flush()

        jetson = Product(name="Jetson Nano Orin")
        camera = Product(name="4K Depth Camera")
        motor = Product(name="Smart Locker Servo Motor")
        db.add_all([jetson, camera, motor])
        db.flush()

        batch_jetson = StockBatch(
            product_id=jetson.id,
            purchase_price=Decimal("350.00"),
            current_selling_price=Decimal("450.00"),
            initial_quantity=Decimal("20"),
            remaining_quantity=Decimal("20"),
        )
        batch_camera = StockBatch(
            product_id=camera.id,
            purchase_price=Decimal("120.00"),
            current_selling_price=Decimal("180.00"),
            initial_quantity=Decimal("30"),
            remaining_quantity=Decimal("30"),
        )
        batch_motor = StockBatch(
            product_id=motor.id,
            purchase_price=Decimal("25.00"),
            current_selling_price=Decimal("45.00"),
            initial_quantity=Decimal("100"),
            remaining_quantity=Decimal("100"),
        )
        db.add_all([batch_jetson, batch_camera, batch_motor])
        db.flush()

        purchase_invoice = Invoice(
            party_id=supplier.id,
            invoice_type=InvoiceType.PURCHASE,
            total_amount=Decimal("0"),
        )
        db.add(purchase_invoice)
        db.flush()

        purchase_items = [
            InvoiceItem(
                invoice_id=purchase_invoice.id,
                batch_id=batch_jetson.id,
                quantity=Decimal("20"),
                unit_price=batch_jetson.purchase_price,
            ),
            InvoiceItem(
                invoice_id=purchase_invoice.id,
                batch_id=batch_camera.id,
                quantity=Decimal("30"),
                unit_price=batch_camera.purchase_price,
            ),
            InvoiceItem(
                invoice_id=purchase_invoice.id,
                batch_id=batch_motor.id,
                quantity=Decimal("100"),
                unit_price=batch_motor.purchase_price,
            ),
        ]
        for item in purchase_items:
            db.add(item)
        purchase_total = sum(item.quantity * item.unit_price for item in purchase_items)
        purchase_invoice.total_amount = purchase_total

        sale_invoice = Invoice(
            party_id=client.id,
            invoice_type=InvoiceType.SALE,
            total_amount=Decimal("0"),
        )
        db.add(sale_invoice)
        db.flush()

        batch_jetson.remaining_quantity -= Decimal("5")
        batch_camera.remaining_quantity -= Decimal("8")
        batch_motor.remaining_quantity -= Decimal("20")

        sale_items = [
            InvoiceItem(
                invoice_id=sale_invoice.id,
                batch_id=batch_jetson.id,
                quantity=Decimal("5"),
                unit_price=batch_jetson.current_selling_price,
            ),
            InvoiceItem(
                invoice_id=sale_invoice.id,
                batch_id=batch_camera.id,
                quantity=Decimal("8"),
                unit_price=batch_camera.current_selling_price,
            ),
            InvoiceItem(
                invoice_id=sale_invoice.id,
                batch_id=batch_motor.id,
                quantity=Decimal("20"),
                unit_price=batch_motor.current_selling_price,
            ),
        ]
        for item in sale_items:
            db.add(item)
        sale_total = sum(item.quantity * item.unit_price for item in sale_items)
        sale_invoice.total_amount = sale_total

        payment = Payment(
            party_id=client.id,
            invoice_id=sale_invoice.id,
            amount=Decimal("500.00"),
        )
        db.add(payment)

        db.commit()
        print("Done")
    finally:
        db.close()


if __name__ == "__main__":
    main()
