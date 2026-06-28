import sys
import os

# Add the app directory to the sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.models.domain import Tenant
from sqlalchemy.exc import SQLAlchemyError

def test_tenant_query():
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        print(f"Tenant found: {tenant.company_name if tenant else 'None'}")
    except SQLAlchemyError as e:
        print(f"SQLAlchemyError: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    test_tenant_query()
