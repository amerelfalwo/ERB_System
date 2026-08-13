import time
import asyncio
import logging
from decimal import Decimal
from sqlalchemy import event
from sqlalchemy.engine import Engine
from app.core.database import SessionLocal
from app.services.reports import unified_dashboard_report
from app.services.invoice_service import create_purchase_invoice_svc
from app.repositories.base import InvoiceRepository, BatchRepository
from app.schemas.invoice import InvoiceCreatePurchase, InvoiceItemCreatePurchase
from app.models.domain import Tenant, Party, Product
from app.core.cache import get_cache, set_cache, delete_cache

logging.basicConfig(level=logging.INFO)

query_count = 0

@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    global query_count
    query_count += 1

async def run_benchmark_async():
    global query_count
    with SessionLocal() as db:
        try:
            tenant = db.query(Tenant).first()
            if not tenant:
                print("No tenant found for benchmark.")
                return

            print(f"--- BENCHMARK FOR TENANT ID {tenant.id} ---")
            cache_key = "dashboard:2026-01-01:2026-12-31"

            # Clear cache before test
            await delete_cache(tenant.id, cache_key)
            
            # 1. First Call: Cache Miss (Query DB & Populate Redis)
            query_count = 0
            t0 = time.perf_counter()
            cached_data = await get_cache(tenant.id, cache_key)
            if cached_data is None:
                res = unified_dashboard_report(db, tenant.id, "2026-01-01", "2026-12-31")
                res_dict = res.model_dump() if hasattr(res, "model_dump") else res
                await set_cache(tenant.id, cache_key, res_dict, ttl=300)
            t1 = time.perf_counter()
            print(f"[1st Call - Cache MISS (DB Engine)] Queries: {query_count} | Latency: {(t1 - t0)*1000:.2f} ms")
            db.commit()

            # 2. Second Call: Cache HIT (Redis sub-millisecond response)
            query_count = 0
            t0 = time.perf_counter()
            cached_data = await get_cache(tenant.id, cache_key)
            t1 = time.perf_counter()
            print(f"[2nd Call - Cache HIT (Redis Cache)] Queries: {query_count} | Latency: {(t1 - t0)*1000:.2f} ms")

            # 3. Multi-item Purchase Invoice Benchmark
            party = db.query(Party).filter_by(tenant_id=tenant.id).first()
            products = db.query(Product).filter_by(tenant_id=tenant.id).limit(5).all()
            if party and len(products) >= 2:
                inv_repo = InvoiceRepository(db, tenant.id)
                batch_repo = BatchRepository(db, tenant.id)
                
                items = [
                    InvoiceItemCreatePurchase(
                        product_id=p.id,
                        quantity=Decimal("5"),
                        purchase_price=Decimal("10.00"),
                        sell_price=Decimal("15.00")
                    )
                    for p in products
                ]
                purch_data = InvoiceCreatePurchase(party_id=party.id, items=items)
                
                query_count = 0
                t0 = time.perf_counter()
                inv = create_purchase_invoice_svc(db, inv_repo, batch_repo, purch_data, tenant.id)
                t1 = time.perf_counter()
                print(f"[Purchase Invoice Create (5 items)] Queries: {query_count} | Latency: {(t1 - t0)*1000:.2f} ms")
                db.rollback()
        except Exception as e:
            db.rollback()
            raise e

def run_benchmark():
    asyncio.run(run_benchmark_async())

if __name__ == "__main__":
    run_benchmark()
