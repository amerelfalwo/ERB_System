from app.models.domain import StockBatch
from app.schemas.invoice import InvoiceCreatePurchase, InvoiceCreateSale, InvoiceItemCreatePurchase, InvoiceItemCreateSale
from app.services.inventory import create_purchase_invoice, create_sale_invoice


def test_fifo_allocation(db, party_supplier, party_client, product, dec):
    purchase = InvoiceCreatePurchase(
        party_id=party_supplier.id,
        items=[
            InvoiceItemCreatePurchase(
                product_id=product.id,
                quantity=dec("10"),
                purchase_price=dec("5.00"),
                selling_price=dec("8.00"),
            ),
            InvoiceItemCreatePurchase(
                product_id=product.id,
                quantity=dec("5"),
                purchase_price=dec("6.00"),
                selling_price=dec("9.00"),
            ),
        ],
    )
    create_purchase_invoice(db, purchase)

    sale = InvoiceCreateSale(
        party_id=party_client.id,
        items=[InvoiceItemCreateSale(product_id=product.id, quantity=dec("12"))],
    )
    create_sale_invoice(db, sale)

    batches = db.query(StockBatch).order_by(StockBatch.created_at.asc(), StockBatch.id.asc()).all()
    assert batches[0].remaining_quantity == dec("0")
    assert batches[1].remaining_quantity == dec("3")
