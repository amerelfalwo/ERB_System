import pytest
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
                sell_price=dec("10.00"),
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


def test_payment_over_allocation(db, party_supplier, product, dec):
    purchase = InvoiceCreatePurchase(
        party_id=party_supplier.id,
        items=[
            InvoiceItemCreatePurchase(
                product_id=product.id,
                quantity=dec("4"),
                purchase_price=dec("7.50"),
                sell_price=dec("10.00"),
            )
        ],
    )
    invoice = create_purchase_invoice(db, purchase)

    # Total invoice amount is 30.00.
    # Attempting to pay 35.00 should raise ValueError (invoice level over-allocation check).
    with pytest.raises(ValueError) as exc_info:
        create_payment(
            db,
            PaymentCreate(
                party_id=party_supplier.id,
                invoice_id=invoice.id,
                amount=dec("35.00"),
            ),
        )
    assert "Cannot pay more than the outstanding balance of the invoice" in str(exc_info.value)

    # Let's make a partial payment of 10.00 first (remaining balance becomes 20.00).
    create_payment(
        db,
        PaymentCreate(
            party_id=party_supplier.id,
            invoice_id=invoice.id,
            amount=dec("10.00"),
        ),
        tenant_id=1,
    )

    # Attempting to pay another 25.00 should raise ValueError.
    with pytest.raises(ValueError) as exc_info:
        create_payment(
            db,
            PaymentCreate(
                party_id=party_supplier.id,
                invoice_id=invoice.id,
                amount=dec("25.00"),
            ),
        )
    assert "Cannot pay more than the outstanding balance of the invoice" in str(exc_info.value)

    # Now let's test party-level payment over-allocation without an invoice_id.
    # The remaining outstanding balance of the party is 20.00 (since 30.00 invoice - 10.00 paid).
    # Attempting to pay 25.00 should raise ValueError.
    with pytest.raises(ValueError) as exc_info:
        create_payment(
            db,
            PaymentCreate(
                party_id=party_supplier.id,
                amount=dec("25.00"),
            ),
        )
    assert "Cannot pay more than the outstanding balance" in str(exc_info.value)
