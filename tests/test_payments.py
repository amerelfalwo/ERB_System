from app.schemas.invoice import InvoiceCreatePurchase, InvoiceItemCreatePurchase
from app.schemas.payment import PaymentCreate
from app.services.inventory import create_purchase_invoice
from app.services.payments import create_payment, get_invoice_totals


def test_partial_and_full_payment(db, party_supplier, product, dec):
    purchase = InvoiceCreatePurchase(
        party_id=party_supplier.id,
        items=[
            InvoiceItemCreatePurchase(
                product_id=product.id,
                quantity=dec("4"),
                purchase_price=dec("7.50"),
                selling_price=dec("10.00"),
            )
        ],
    )
    invoice = create_purchase_invoice(db, purchase)

    create_payment(db, PaymentCreate(party_id=party_supplier.id, invoice_id=invoice.id, amount=dec("10.00")))
    totals = get_invoice_totals(db, invoice.id)
    assert totals["paid"] == dec("10.00")
    assert totals["balance"] == dec("20.00")
    assert totals["status"] == "partial"

    create_payment(db, PaymentCreate(party_id=party_supplier.id, invoice_id=invoice.id, amount=dec("20.00")))
    totals = get_invoice_totals(db, invoice.id)
    assert totals["balance"] == dec("0.00")
    assert totals["status"] == "paid"
