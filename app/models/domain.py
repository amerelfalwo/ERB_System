import enum
from datetime import datetime, timezone
from sqlalchemy import func

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Index, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import relationship

from . import Base

class PartyType(enum.Enum):
    CLIENT = "client"
    SUPPLIER = "supplier"

class InvoiceType(enum.Enum):
    PURCHASE = "purchase"
    SELL = "sell"
    SELL_RETURN = "sell_return"
    PURCHASE_RETURN = "purchase_return"

class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String, nullable=False, index=True)
    logo_url = Column(Text)
    primary_color = Column(String)
    default_footer_text = Column(Text, nullable=True)
    phone = Column(String, nullable=True, index=True)
    address = Column(Text, nullable=True)
    tax_number = Column(String, nullable=True)
    store_name = Column(String, nullable=True)
    website = Column(String, nullable=True)
    print_notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    is_approved = Column(Boolean, default=False, server_default="false", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now())
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True)
    products = relationship("Product", back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True)
    parties = relationship("Party", back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True)
    invoices = relationship("Invoice", back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True)
    batches = relationship("StockBatch", back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True)
    templates = relationship("PrintTemplate", back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True)


class Party(Base):
    __tablename__ = "parties"
    __table_args__ = (
        Index("idx_tenant_party_type", "tenant_id", "party_type"),
    )
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    # tenant_id may be optional in tests or single-tenant setups
    name = Column(String, index=True)
    party_type = Column(Enum(PartyType, native_enum=False), index=True)
    phone = Column(String, nullable=True, index=True)
    address = Column(Text, nullable=True)
    initial_balance = Column(Numeric(12, 2), default=0, nullable=True)
    notes = Column(Text, nullable=True)
    credit_limit = Column(Numeric(12, 2), default=0.00, nullable=True)
    tenant = relationship("Tenant", back_populates="parties")
    invoices = relationship("Invoice", back_populates="party")
    payments = relationship("Payment", back_populates="party")

class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("idx_tenant_product_name", "tenant_id", "name"),
    )
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String, index=True)
    last_purchase_price = Column(Numeric(12, 2), default=0)
    purchase_price = Column(Numeric(12, 2), default=0)
    average_cost = Column(Numeric(12, 2), default=0)
    sell_price = Column(Numeric(12, 2), default=0)
    min_stock = Column(Numeric(12, 3), default=5)
    tenant = relationship("Tenant", back_populates="products")
    batches = relationship("StockBatch", back_populates="product", passive_deletes=True)

class StockBatch(Base):
    __tablename__ = "stock_batches"
    __table_args__ = (
        Index("idx_tenant_product_id", "tenant_id", "product_id"),
    )
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    party_id = Column(Integer, ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True)
    purchase_price = Column(Numeric(12, 2))
    current_selling_price = Column(Numeric(12, 2))
    initial_quantity = Column(Numeric(12, 3))
    remaining_quantity = Column(Numeric(12, 3))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    tenant = relationship("Tenant", back_populates="batches")
    product = relationship("Product", back_populates="batches")
    party = relationship("Party")

class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("idx_tenant_invoice_type", "tenant_id", "invoice_type"),
        Index("idx_tenant_party_id", "tenant_id", "party_id"),
    )
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    party_id = Column(Integer, ForeignKey("parties.id", ondelete="RESTRICT"), index=True)
    invoice_type = Column(Enum(InvoiceType, native_enum=False), index=True)
    total_amount = Column(Numeric(12, 2))
    subtotal = Column(Numeric(12, 2), default=0)
    total_discount = Column(Numeric(12, 2), default=0)
    discount_amount = Column(Numeric(12, 2), default=0)
    total_tax = Column(Numeric(12, 2), default=0)
    delivery_fee = Column(Numeric(12, 2), default=0)
    reference_number = Column(String, nullable=True, index=True)
    issue_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    due_date = Column(DateTime, nullable=True, index=True)
    notes = Column(Text, nullable=True)
    footer_custom_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    tenant = relationship("Tenant", back_populates="invoices")
    party = relationship("Party", back_populates="invoices")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan", passive_deletes=True)
    payments = relationship("Payment", back_populates="invoice", cascade="all, delete-orphan", passive_deletes=True)

class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    batch_id = Column(Integer, ForeignKey("stock_batches.id", ondelete="RESTRICT"), index=True)
    original_invoice_item_id = Column(Integer, ForeignKey("invoice_items.id", ondelete="SET NULL"), nullable=True, index=True)
    quantity = Column(Numeric(12, 3))
    unit_price = Column(Numeric(12, 2))  # Keep for backwards compat or as general price
    purchase_price = Column(Numeric(12, 2), nullable=True)
    sell_price = Column(Numeric(12, 2), nullable=True)
    discount = Column(Numeric(12, 2), default=0)
    tax = Column(Numeric(12, 2), default=0)
    invoice = relationship("Invoice", back_populates="items")
    batch = relationship("StockBatch")

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=True, index=True)
    party_id = Column(Integer, ForeignKey("parties.id", ondelete="RESTRICT"), index=True)
    amount = Column(Numeric(12, 2))
    payment_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    invoice = relationship("Invoice", back_populates="payments")
    party = relationship("Party", back_populates="payments")

class PrintTemplate(Base):
    __tablename__ = "print_templates"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
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

class Expense(Base):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(String, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    expense_date = Column(DateTime, nullable=False, index=True)
    category = Column(String, nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now())
    tenant = relationship("Tenant")
    creator = relationship("User")