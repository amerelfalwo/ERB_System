from decimal import Decimal
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import get_db
from app.main import app as fastapi_app
from app.models import Base
from app.models.domain import Party, PartyType, Product


def _engine():
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture()
def db():
    engine = _engine()
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def override_get_db(db):
    def _override():
        yield db

    fastapi_app.dependency_overrides[get_db] = _override
    yield
    fastapi_app.dependency_overrides.clear()


@pytest.fixture()
def party_supplier(db):
    party = Party(name="Supplier A", party_type=PartyType.SUPPLIER)
    db.add(party)
    db.commit()
    db.refresh(party)
    return party


@pytest.fixture()
def party_client(db):
    party = Party(name="Client A", party_type=PartyType.CLIENT)
    db.add(party)
    db.commit()
    db.refresh(party)
    return party


@pytest.fixture()
def product(db):
    product = Product(name="Widget")
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@pytest.fixture()
def dec():
    return Decimal
