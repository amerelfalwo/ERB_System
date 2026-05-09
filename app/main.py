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
from .routers import auth, batches, invoices, parties, payments, products, templates, reports, tenants

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
LOGOS_DIR = STATIC_DIR / "logos"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
LOGOS_DIR.mkdir(parents=True, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE invoices ALTER COLUMN invoice_type TYPE VARCHAR(30);"))
            conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS delivery_fee NUMERIC(10, 2);"))
            conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS footer_custom_text TEXT;"))
            conn.execute(text("ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS purchase_price NUMERIC(10, 2);"))
            conn.execute(text("ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS sale_price NUMERIC(10, 2);"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR;"))
            conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS purchase_price NUMERIC(10, 2) DEFAULT 0;"))
            conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS sell_price NUMERIC(10, 2) DEFAULT 0;"))
            print("Successfully migrated database columns")
    except Exception as e:
        print("Migration error:", e)
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
register_exception_handlers(app)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Welcome to ERB"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


app.include_router(auth, prefix="/auth")
app.include_router(parties, dependencies=[Depends(get_current_user)])
app.include_router(products, dependencies=[Depends(get_current_user)])
app.include_router(batches, dependencies=[Depends(get_current_user)])
app.include_router(invoices, dependencies=[Depends(get_current_user)])
app.include_router(payments, dependencies=[Depends(get_current_user)])
app.include_router(templates, dependencies=[Depends(get_current_user)])
app.include_router(reports, dependencies=[Depends(get_current_user)])
app.include_router(tenants, dependencies=[Depends(get_current_user)])
