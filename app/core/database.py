import logging

from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models import Base

logger = logging.getLogger(__name__)

# Normalize legacy 'postgres://' scheme → SQLAlchemy 2.x requires 'postgresql://'
_raw_url = settings.DATABASE_URL
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif _raw_url.startswith("postgresql://"):
    _raw_url = _raw_url.replace("postgresql://", "postgresql+psycopg2://", 1)

db_url = make_url(_raw_url)
connect_args: dict = {"connect_timeout": 10, "options": "-c statement_timeout=30000"}
if db_url.host and db_url.host not in {"localhost", "127.0.0.1"}:
    connect_args["sslmode"] = "require"

# NullPool — Supabase pooler (port 6543) already handles pooling server-side.
# Client-side pooling on top causes double-pooling and ECIRCUITBREAKER errors.
engine = create_engine(
    _raw_url,
    poolclass=NullPool,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()