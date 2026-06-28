"""
app/routers  –  Backward-compatibility shim
============================================
All routers have been moved to ``app.api``.
This module re-exports them so that any existing imports from
``app.routers`` continue to work without change.

New code should import directly from ``app.api``.
"""

from app.api import (  # noqa: F401
    admin,
    auth,
    batches,
    customers,
    invoices,
    parties,
    payments,
    products,
    suppliers,
    templates,
    reports,
    tenants,
)

__all__ = [
    "admin",
    "auth",
    "batches",
    "customers",
    "invoices",
    "parties",
    "payments",
    "products",
    "suppliers",
    "templates",
    "reports",
    "tenants",
]
