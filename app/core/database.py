import logging
import time

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

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
# ---------------------------------------------------------------------------
connect_args: dict = {
    "connect_timeout": 10,
    "keepalives": 1,
    "keepalives_idle": 15,
    "keepalives_interval": 5,
    "keepalives_count": 5,
}
if db_url.host and db_url.host not in {"localhost", "127.0.0.1"}:
    connect_args["sslmode"] = "require"

# ---------------------------------------------------------------------------
# 3. Engine — QueuePool with pool_pre_ping & pool_recycle to maintain warm SSL connections
#    use_native_hstore=False prevents psycopg2 from executing startup hstore catalog queries
#    that trigger unexpected SSL termination on Supabase PgBouncer (Port 6543).
# ---------------------------------------------------------------------------
engine = create_engine(
    _raw_url,
    use_native_hstore=False,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_recycle=300,
    pool_timeout=15,
    pool_pre_ping=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# 4. get_db — yields a session, with pool_pre_ping handling connection verification.
#    Short 0.2s non-blocking retries prevent threadpool worker exhaustion.
# ---------------------------------------------------------------------------
_MAX_RETRIES = 3


def get_db():
    retries = 0
    db = None
    while True:
        try:
            db = SessionLocal()
            break
        except Exception as exc:
            if db:
                try:
                    db.close()
                except Exception:
                    pass
                db = None
            retries += 1
            if retries >= _MAX_RETRIES:
                logger.error("Database connection failed after %d retries: %s", _MAX_RETRIES, exc)
                raise
            logger.warning(
                "Database session creation attempt %d/%d failed (%s). Retrying in 0.2s...",
                retries, _MAX_RETRIES, exc.__class__.__name__,
            )
            time.sleep(0.2 * retries)
    try:
        yield db
    finally:
        if db:
            db.close()