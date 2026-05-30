from decimal import Decimal
from typing import Optional, List

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.domain import (
    Invoice, InvoiceItem, InvoiceType, Party, PartyType,
    Payment, Product, StockBatch,
)

STATUS_PAID = "paid"
STATUS_PARTIAL = "partial"
STATUS_UNPAID = "unpaid"


class InvoiceRepository:
    def __init__(self, db: Session, tenant_id: int):
        self._db = db
        self._tid = tenant_id

    def get_by_id(self, invoice_id: int) -> Optional[Invoice]:
        return self._db.execute(
            select(Invoice)
            .options(
                selectinload(Invoice.items).joinedload(InvoiceItem.batch).joinedload(StockBatch.product),
                selectinload(Invoice.payments)
            )
            .where(Invoice.id == invoice_id, Invoice.tenant_id == self._tid)
        ).scalar_one_or_none()

    def list(self, party_id: Optional[int] = None, invoice_type: Optional[str] = None, skip: int = 0, limit: int = 100) -> List[Invoice]:
        q = (
            select(Invoice)
            .options(
                joinedload(Invoice.party),
                selectinload(Invoice.items).joinedload(InvoiceItem.batch).joinedload(StockBatch.product),
                selectinload(Invoice.payments),
            )
            .where(Invoice.tenant_id == self._tid)
        )
        if party_id is not None:
            q = q.where(Invoice.party_id == party_id)
        if invoice_type:
            # Accept either 'sale'/'sell' or 'purchase' values
            it = invoice_type.lower()
            if it in ('sale', 'sell'):
                q = q.where(Invoice.invoice_type == InvoiceType.SELL)
            elif it in ('purchase', 'buy'):
                q = q.where(Invoice.invoice_type == InvoiceType.PURCHASE)
            elif it in ('sale_return', 'sell_return'):
                q = q.where(Invoice.invoice_type == InvoiceType.SELL_RETURN)
            elif it in ('purchase_return',):
                q = q.where(Invoice.invoice_type == InvoiceType.PURCHASE_RETURN)

        q = q.order_by(Invoice.created_at.desc()).offset(skip).limit(limit)
        return self._db.execute(q).scalars().unique().all()

    def count(self, party_id: Optional[int] = None, invoice_type: Optional[str] = None) -> int:
        q = select(func.count(Invoice.id)).where(Invoice.tenant_id == self._tid)
        if party_id is not None:
            q = q.where(Invoice.party_id == party_id)
        if invoice_type:
            it = invoice_type.lower()
            if it in ('sale', 'sell'):
                q = q.where(Invoice.invoice_type == InvoiceType.SELL)
            elif it in ('purchase', 'buy'):
                q = q.where(Invoice.invoice_type == InvoiceType.PURCHASE)
            elif it in ('sale_return', 'sell_return'):
                q = q.where(Invoice.invoice_type == InvoiceType.SELL_RETURN)
            elif it in ('purchase_return',):
                q = q.where(Invoice.invoice_type == InvoiceType.PURCHASE_RETURN)
        return self._db.execute(q).scalar_one()

    def bulk_payment_sums(self, invoice_ids: List[int]) -> dict:
        if not invoice_ids:
            return {}
        rows = self._db.execute(
            select(Payment.invoice_id, func.coalesce(func.sum(Payment.amount), 0))
            .join(Invoice, Payment.invoice_id == Invoice.id)
            .where(Payment.invoice_id.in_(invoice_ids), Invoice.tenant_id == self._tid)
            .group_by(Payment.invoice_id)
        ).all()
        return {inv_id: amt for inv_id, amt in rows}

    def bulk_party_names(self, party_ids) -> dict:
        if not party_ids:
            return {}
        rows = self._db.execute(
            select(Party.id, Party.name).where(Party.id.in_(party_ids))
        ).all()
        return {pid: name for pid, name in rows}


    def get_paid_amount(self, invoice_id: int) -> Decimal:
        return Decimal(str(
            self._db.execute(
                select(func.coalesce(func.sum(Payment.amount), 0))
                .join(Invoice, Payment.invoice_id == Invoice.id)
                .where(Payment.invoice_id == invoice_id, Invoice.tenant_id == self._tid)
            ).scalar_one()
        ))

    def add(self, invoice: Invoice) -> None:
        self._db.add(invoice)

    def delete(self, invoice: Invoice) -> None:
        self._db.delete(invoice)

    def commit(self) -> None:
        self._db.commit()

    def flush(self) -> None:
        self._db.flush()

    def refresh(self, obj) -> None:
        self._db.refresh(obj)

    def rollback(self) -> None:
        self._db.rollback()


class BatchRepository:
    def __init__(self, db: Session, tenant_id: int):
        self._db = db
        self._tid = tenant_id

    def get_by_id(self, batch_id: int) -> Optional[StockBatch]:
        return self._db.execute(
            select(StockBatch).where(StockBatch.id == batch_id, StockBatch.tenant_id == self._tid)
        ).scalar_one_or_none()

    def get_fifo_batches(self, product_id: int, party_id: Optional[int] = None) -> List[StockBatch]:
        q = select(StockBatch).where(
            StockBatch.product_id == product_id,
            StockBatch.tenant_id == self._tid,
            StockBatch.remaining_quantity > 0,
        )
        if party_id is not None:
            q = q.where(StockBatch.party_id == party_id)
        return self._db.execute(
            q.order_by(StockBatch.created_at.asc(), StockBatch.id.asc())
        ).scalars().all()

    def get_highest_selling_price(self, product_id: int) -> Optional[Decimal]:
        price = self._db.execute(
            select(StockBatch.current_selling_price).where(
                StockBatch.product_id == product_id,
                StockBatch.tenant_id == self._tid,
                StockBatch.remaining_quantity > 0,
            ).order_by(StockBatch.current_selling_price.desc()).limit(1)
        ).scalar_one_or_none()
        if price is None:
            price = self._db.execute(
                select(StockBatch.current_selling_price).where(
                    StockBatch.product_id == product_id,
                    StockBatch.tenant_id == self._tid,
                ).order_by(StockBatch.current_selling_price.desc()).limit(1)
            ).scalar_one_or_none()
        return price

    def add(self, batch: StockBatch) -> None:
        self._db.add(batch)

    def delete(self, batch: StockBatch) -> None:
        self._db.delete(batch)

    def flush(self) -> None:
        self._db.flush()


class PartyRepository:
    def __init__(self, db: Session, tenant_id: int):
        self._db = db
        self._tid = tenant_id

    def get_by_id(self, party_id: int) -> Optional[Party]:
        return self._db.execute(
            select(Party).where(Party.id == party_id, Party.tenant_id == self._tid)
        ).scalar_one_or_none()

    def list(self, skip: int = 0, limit: int = 100) -> List[Party]:
        return self._db.execute(
            select(Party).where(Party.tenant_id == self._tid)
            .offset(skip).limit(limit)
        ).scalars().all()

    def get_all_for_select(self) -> List[dict]:
        rows = self._db.execute(
            select(Party.id, Party.name)
            .where(Party.tenant_id == self._tid)
        ).all()
        return [{"id": r.id, "name": r.name} for r in rows]

    def invoice_count(self, party_id: int) -> int:
        return self._db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.party_id == party_id, Invoice.tenant_id == self._tid
            )
        ).scalar_one()

    def payment_count(self, party_id: int) -> int:
        return self._db.execute(
            select(func.count(Payment.id)).join(Party).where(Payment.party_id == party_id, Party.tenant_id == self._tid)
        ).scalar_one()

    def total_invoiced(self, party_id: int, invoice_type: InvoiceType) -> Decimal:
        return Decimal(str(self._db.execute(
            select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                Invoice.party_id == party_id,
                Invoice.invoice_type == invoice_type,
                Invoice.tenant_id == self._tid,
            )
        ).scalar_one()))

    def total_paid(self, party_id: int) -> Decimal:
        return Decimal(str(self._db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).join(Party).where(Payment.party_id == party_id, Party.tenant_id == self._tid)
        ).scalar_one()))

    def total_invoiced_excluding(self, party_id: int, invoice_type: InvoiceType, exclude_invoice_id: int) -> Decimal:
        return Decimal(str(self._db.execute(
            select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                Invoice.party_id == party_id,
                Invoice.invoice_type == invoice_type,
                Invoice.tenant_id == self._tid,
                Invoice.id != exclude_invoice_id,
            )
        ).scalar_one()))

    def total_invoiced_net_excluding(self, party_id: int, exclude_invoice_id: int) -> Decimal:
        sale_total = Decimal(str(self._db.execute(
            select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                Invoice.party_id == party_id,
                Invoice.invoice_type == InvoiceType.SELL,
                Invoice.tenant_id == self._tid,
                Invoice.id != exclude_invoice_id,
            )
        ).scalar_one()))
        return_total = Decimal(str(self._db.execute(
            select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                Invoice.party_id == party_id,
                Invoice.invoice_type == InvoiceType.SELL_RETURN,
                Invoice.tenant_id == self._tid,
                Invoice.id != exclude_invoice_id,
            )
        ).scalar_one()))
        return max(Decimal("0"), sale_total - return_total)

    def total_paid_excluding(self, party_id: int, exclude_invoice_id: int) -> Decimal:
        return Decimal(str(self._db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).join(Party).where(
                Payment.party_id == party_id,
                Payment.invoice_id != exclude_invoice_id,
                Party.tenant_id == self._tid,
            )
        ).scalar_one()))

    def add(self, party: Party) -> None:
        self._db.add(party)

    def delete(self, party: Party) -> None:
        self._db.delete(party)

    def commit(self) -> None:
        self._db.commit()

    def refresh(self, obj) -> None:
        self._db.refresh(obj)


class ProductRepository:
    def __init__(self, db: Session, tenant_id: int):
        self._db = db
        self._tid = tenant_id

    def get_by_id(self, product_id: int) -> Optional[Product]:
        return self._db.execute(
            select(Product).where(Product.id == product_id, Product.tenant_id == self._tid)
        ).scalar_one_or_none()

    def list(self, skip: int = 0, limit: int = 100) -> List[Product]:
        return self._db.execute(
            select(Product).where(Product.tenant_id == self._tid)
            .offset(skip).limit(limit)
        ).scalars().all()

    def get_all_for_select(self) -> List[dict]:
        rows = self._db.execute(
            select(Product.id, Product.name)
            .where(Product.tenant_id == self._tid)
        ).all()
        return [{"id": r.id, "name": r.name} for r in rows]

    def count_by_ids(self, product_ids: List[int]) -> int:
        return len(self._db.execute(
            select(Product.id).where(
                Product.id.in_(product_ids),
                Product.tenant_id == self._tid,
            )
        ).scalars().all())

    def add(self, product: Product) -> None:
        self._db.add(product)

    def delete(self, product: Product) -> None:
        self._db.delete(product)

    def commit(self) -> None:
        self._db.commit()

    def refresh(self, obj) -> None:
        self._db.refresh(obj)


class PaymentRepository:
    def __init__(self, db: Session, tenant_id: int):
        self._db = db
        self._tid = tenant_id

    def get_by_id(self, payment_id: int) -> Optional[Payment]:
        return self._db.execute(
            select(Payment).join(Party).where(Payment.id == payment_id, Party.tenant_id == self._tid)
        ).scalar_one_or_none()

    def get_for_invoice(self, invoice_id: int, payment_id: int) -> Optional[Payment]:
        return self._db.execute(
            select(Payment).join(Party).where(Payment.id == payment_id, Payment.invoice_id == invoice_id, Party.tenant_id == self._tid)
        ).scalar_one_or_none()

    def add(self, payment: Payment) -> None:
        self._db.add(payment)

    def delete(self, payment: Payment) -> None:
        self._db.delete(payment)

    def commit(self) -> None:
        self._db.commit()

    def refresh(self, obj) -> None:
        self._db.refresh(obj)
