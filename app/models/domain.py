import enum
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import relationship

from . import Base

class PartyType(enum.Enum):
    CLIENT = "client"
    SUPPLIER = "supplier"

class InvoiceType(enum.Enum):
    PURCHASE = "purchase"
    SALE = "sale"

class Party(Base):
    __tablename__ = "parties"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    party_type = Column(Enum(PartyType, native_enum=False))
    invoices = relationship("Invoice", back_populates="party")
    payments = relationship("Payment", back_populates="party")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    batches = relationship("StockBatch", back_populates="product")

class StockBatch(Base):
    __tablename__ = "stock_batches"
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    purchase_price = Column(Numeric(12, 2))
    current_selling_price = Column(Numeric(12, 2))
    initial_quantity = Column(Numeric(12, 3))
    remaining_quantity = Column(Numeric(12, 3))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    product = relationship("Product", back_populates="batches")

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    party_id = Column(Integer, ForeignKey("parties.id"))
    invoice_type = Column(Enum(InvoiceType, native_enum=False))
    total_amount = Column(Numeric(12, 2))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    party = relationship("Party", back_populates="invoices")
    items = relationship("InvoiceItem", back_populates="invoice")
    payments = relationship("Payment", back_populates="invoice")

class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"))
    batch_id = Column(Integer, ForeignKey("stock_batches.id"))
    quantity = Column(Numeric(12, 3))
    unit_price = Column(Numeric(12, 2))
    invoice = relationship("Invoice", back_populates="items")
    batch = relationship("StockBatch")

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    party_id = Column(Integer, ForeignKey("parties.id"))
    amount = Column(Numeric(12, 2))
    payment_date = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    invoice = relationship("Invoice", back_populates="payments")
    party = relationship("Party", back_populates="payments")

class PrintTemplate(Base):
    __tablename__ = "print_templates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    html_content = Column(Text)
    settings = Column(JSON)