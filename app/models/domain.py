import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import relationship

from . import Base

class PartyType(enum.Enum):
    CLIENT = "client"
    SUPPLIER = "supplier"

class InvoiceType(enum.Enum):
    PURCHASE = "purchase"
    SALE = "sale"
    SALE_RETURN = "sale_return"
    PURCHASE_RETURN = "purchase_return"

class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String, nullable=False)
    logo_url = Column(String)
    primary_color = Column(String)
    default_footer_text = Column(Text, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    tax_number = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True)
    products = relationship("Product", back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True)
    parties = relationship("Party", back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True)
    invoices = relationship("Invoice", back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True)
    batches = relationship("StockBatch", back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True)
    templates = relationship("PrintTemplate", back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True)


class Party(Base):
    __tablename__ = "parties"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, index=True)
    party_type = Column(Enum(PartyType, native_enum=False))
    phone = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    tenant = relationship("Tenant", back_populates="parties")
    invoices = relationship("Invoice", back_populates="party")
    payments = relationship("Payment", back_populates="party")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, index=True)
    last_purchase_price = Column(Numeric(12, 2), default=0)
    tenant = relationship("Tenant", back_populates="products")
    batches = relationship("StockBatch", back_populates="product")

class StockBatch(Base):
    __tablename__ = "stock_batches"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    purchase_price = Column(Numeric(12, 2))
    current_selling_price = Column(Numeric(12, 2))
    initial_quantity = Column(Numeric(12, 3))
    remaining_quantity = Column(Numeric(12, 3))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    tenant = relationship("Tenant", back_populates="batches")
    product = relationship("Product", back_populates="batches")

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    party_id = Column(Integer, ForeignKey("parties.id"))
    invoice_type = Column(Enum(InvoiceType, native_enum=False))
    total_amount = Column(Numeric(12, 2))
    delivery_fee = Column(Numeric(12, 2), default=0)
    footer_custom_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    tenant = relationship("Tenant", back_populates="invoices")
    party = relationship("Party", back_populates="invoices")
    items = relationship("InvoiceItem", back_populates="invoice")
    payments = relationship("Payment", back_populates="invoice")

class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"))
    batch_id = Column(Integer, ForeignKey("stock_batches.id"))
    quantity = Column(Numeric(12, 3))
    unit_price = Column(Numeric(12, 2))  # Keep for backwards compat or as general price
    purchase_price = Column(Numeric(12, 2), nullable=True)
    sale_price = Column(Numeric(12, 2), nullable=True)
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
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String)
    html_content = Column(Text)
    settings = Column(JSON)
    tenant = relationship("Tenant", back_populates="templates")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    username = Column(String, unique=True, index=True)
    full_name = Column(String, nullable=True)
    hashed_password = Column(String)
    role = Column(String, default="admin", server_default="admin")
    tenant = relationship("Tenant", back_populates="users")