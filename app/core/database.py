import logging
import time

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models import Base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Normalise the connection URL for SQLAlchemy 2.x
# ---------------------------------------------------------------------------
_raw_url = settings.DATABASE_URL.strip()
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif _raw_url.startswith("postgresql://"):
    _raw_url = _raw_url.replace("postgresql://", "postgresql+psycopg2://", 1)

db_url = make_url(_raw_url)

# ---------------------------------------------------------------------------
# 2. Build connect_args for the Supabase pooler
#    • No `options` — PgBouncer/Supavisor rejects unknown startup params.
#    • `sslmode=require` for remote hosts.
# ---------------------------------------------------------------------------
connect_args: dict = {
    "connect_timeout": 10,
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 5,
}
if db_url.host and db_url.host not in {"localhost", "127.0.0.1"}:
    connect_args["sslmode"] = "require"

# ---------------------------------------------------------------------------
# 3. Engine — NullPool because Supabase Supavisor already pools server-side.
#    Client-side pooling on top causes double-pooling & ECIRCUITBREAKER errors.
# ---------------------------------------------------------------------------
engine = create_engine(
    _raw_url,
    poolclass=NullPool,
    pool_pre_ping=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# 4. get_db — yields a session, with retry on transient connection errors
#    so that an ECIRCUITBREAKER doesn't crash the whole request immediately.
# ---------------------------------------------------------------------------
_MAX_RETRIES = 3
_RETRY_DELAY = 2  # seconds, doubles each retry


def get_db():
    retries = 0
    while True:
        try:
            db = SessionLocal()
            # Force a lightweight round-trip to verify the connection is alive
            db.execute(text("SELECT 1"))
            break
        except Exception as exc:
            retries += 1
            if retries > _MAX_RETRIES:
                logger.error("Database connection failed after %d retries: %s", _MAX_RETRIES, exc)
                raise
            wait = _RETRY_DELAY * (2 ** (retries - 1))
            logger.warning(
                "Database connection attempt %d/%d failed (%s). Retrying in %ds...",
                retries, _MAX_RETRIES, exc.__class__.__name__, wait,
            )
            time.sleep(wait)
    try:
        yield db
    finally:
        db.close()