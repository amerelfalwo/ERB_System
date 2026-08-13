from app.schemas.invoice import InvoiceCreatePurchase, InvoiceCreateSale, InvoiceItemCreatePurchase, InvoiceItemCreateSale
from app.services.inventory import create_purchase_invoice, create_sale_invoice
from app.services.reports import profit_report


def test_profit_report(db, party_supplier, party_client, product, dec):
    purchase = InvoiceCreatePurchase(
        party_id=party_supplier.id,
        items=[
            InvoiceItemCreatePurchase(
                product_id=product.id,
                quantity=dec("10"),
                purchase_price=dec("5.00"),
                sell_price=dec("8.00"),
            )
        ],
    )
    create_purchase_invoice(db, purchase)

    sale = InvoiceCreateSale(
        party_id=party_client.id,
        items=[InvoiceItemCreateSale(product_id=product.id, quantity=dec("4"))],
    )
    create_sale_invoice(db, sale)

    report = profit_report(db)
    total_profit = report.total_profit
    assert total_profit == dec("12.00")
    assert len(report.items) == 1
