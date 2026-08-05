"""
app/api  –  HTTP layer (formerly app/routers)

Each sub-module owns one domain's FastAPI APIRouter.
Import the routers from here and include them in app/main.py.
"""

from .admin import router as admin
from .auth import router as auth
from .batches import router as batches
from .customers import router as customers
from .invoices import router as invoices
from .parties import router as parties
from .payments import router as payments
from .products import router as products
from .suppliers import router as suppliers
from .templates import router as templates
from .reports import router as reports
from .tenants import router as tenants
from .expenses import router as expenses

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
    "expenses",
]
