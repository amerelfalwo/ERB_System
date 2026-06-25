from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.config import settings
from .core.database import engine
from .core.deps import get_current_user
from .core.exceptions import register_exception_handlers
from .models import Base
from .api import (
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

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
LOGOS_DIR = STATIC_DIR / "logos"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
LOGOS_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
    _logger = logging.getLogger(__name__)

    try:
        # Create all tables that don't yet exist
        Base.metadata.create_all(bind=engine)

        from sqlalchemy import text
        import traceback

        migrations = [
            "ALTER TABLE invoices ALTER COLUMN invoice_type TYPE VARCHAR(30);",
            "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS delivery_fee NUMERIC(10, 2);",
            "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS footer_custom_text TEXT;",
            "ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS purchase_price NUMERIC(10, 2);",
            "ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS sell_price NUMERIC(10, 2);",
            "ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS original_invoice_item_id INTEGER REFERENCES invoice_items(id);",
            "ALTER TABLE invoice_items ALTER COLUMN original_invoice_item_id DROP NOT NULL;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS purchase_price NUMERIC(10, 2) DEFAULT 0;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS sell_price NUMERIC(10, 2) DEFAULT 0;",
            "ALTER TABLE parties ADD COLUMN IF NOT EXISTS notes TEXT;",
            "ALTER TABLE parties ADD COLUMN IF NOT EXISTS credit_limit NUMERIC(12, 2) DEFAULT 0.00;",
            "ALTER TABLE stock_batches ADD COLUMN IF NOT EXISTS party_id INTEGER REFERENCES parties(id);",
            "ALTER TABLE stock_batches ADD CONSTRAINT stock_batches_party_id_fkey FOREIGN KEY (party_id) REFERENCES parties(id) ON DELETE SET NULL;",
            "ALTER TABLE invoices DROP CONSTRAINT IF EXISTS invoices_party_id_fkey;",
            "ALTER TABLE invoices ADD CONSTRAINT invoices_party_id_fkey FOREIGN KEY (party_id) REFERENCES parties(id) ON DELETE RESTRICT;",
            "ALTER TABLE stock_batches DROP CONSTRAINT IF EXISTS stock_batches_product_id_fkey;",
            "ALTER TABLE stock_batches ADD CONSTRAINT stock_batches_product_id_fkey FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT;",
            "ALTER TABLE invoice_items DROP CONSTRAINT IF EXISTS invoice_items_invoice_id_fkey;",
            "ALTER TABLE invoice_items ADD CONSTRAINT invoice_items_invoice_id_fkey FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE;",
            "ALTER TABLE invoice_items DROP CONSTRAINT IF EXISTS invoice_items_batch_id_fkey;",
            "ALTER TABLE invoice_items ADD CONSTRAINT invoice_items_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES stock_batches(id) ON DELETE RESTRICT;",
            "ALTER TABLE invoice_items DROP CONSTRAINT IF EXISTS invoice_items_original_invoice_item_id_fkey;",
            "ALTER TABLE invoice_items ADD CONSTRAINT invoice_items_original_invoice_item_id_fkey FOREIGN KEY (original_invoice_item_id) REFERENCES invoice_items(id) ON DELETE SET NULL;",
            "ALTER TABLE payments DROP CONSTRAINT IF EXISTS payments_invoice_id_fkey;",
            "ALTER TABLE payments ADD CONSTRAINT payments_invoice_id_fkey FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE;",
            "ALTER TABLE payments DROP CONSTRAINT IF EXISTS payments_party_id_fkey;",
            "ALTER TABLE payments ADD CONSTRAINT payments_party_id_fkey FOREIGN KEY (party_id) REFERENCES parties(id) ON DELETE RESTRICT;",
            "UPDATE stock_batches SET tenant_id = 1 WHERE tenant_id IS NULL;",
            "UPDATE products SET tenant_id = 1 WHERE tenant_id IS NULL;",
            "UPDATE parties SET tenant_id = 1 WHERE tenant_id IS NULL;",
            "UPDATE invoices SET tenant_id = 1 WHERE tenant_id IS NULL;"
        ]

        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file_path = log_dir / "migration_run.log"

        # Use direct connection port 5432 for DDL migrations in Supabase
        # as port 6543 (transaction pooler) can cause silent rollbacks or failures for ALTER TABLE.
        migration_db_url = str(engine.url)
        if "pooler.supabase.com" in migration_db_url and ":6543" in migration_db_url:
            migration_db_url = migration_db_url.replace(":6543", ":5432")

        from sqlalchemy import create_engine as _create_engine
        migration_engine = _create_engine(migration_db_url)

        with open(log_file_path, "w") as log_file:
            log_file.write("Starting migrations with direct connection...\n")
            for migration in migrations:
                try:
                    with migration_engine.begin() as conn:
                        conn.execute(text(migration))
                    log_file.write(f"SUCCESS: {migration}\n")
                except Exception as e:
                    log_file.write(f"FAILED: {migration}\nError: {e}\nTraceback:\n{traceback.format_exc()}\n\n")

        migration_engine.dispose()
        _logger.info("Database connected and migrations applied successfully.")

    except Exception as e:
        _logger.error("⚠️  Database connection failed: %s", e)
        _logger.error("   App will start but DB operations will fail.")
        _logger.error("   Fix DATABASE_URL in .env and restart.")

    yield


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)

register_exception_handlers(app)

# Mount static file directory for logos and other assets
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Welcome to ERB ERP API"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}




# ── Public routes ────────────────────────────────────────────────────────────
app.include_router(auth, prefix="/auth")

# ── Protected routes (JWT required) ─────────────────────────────────────────
_protected = {"dependencies": [Depends(get_current_user)]}

app.include_router(customers, **_protected)
app.include_router(suppliers, **_protected)
app.include_router(parties, **_protected)
app.include_router(products, **_protected)
app.include_router(batches, **_protected)
app.include_router(invoices, **_protected)
app.include_router(payments, **_protected)
app.include_router(templates, **_protected)
app.include_router(reports, **_protected)
app.include_router(tenants, **_protected)
