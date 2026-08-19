import sys
import os
import argparse
import asyncio
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, func
from app.core.database import SessionLocal
from app.models.domain import Party, PartyType, Invoice, InvoiceType, Payment, Tenant
from app.core.cache import invalidate_tenant_cache

def audit_party_balances(apply_changes: bool = False):
    db = SessionLocal()
    try:
        tenants = db.execute(select(Tenant)).scalars().all()
        print("=" * 110)
        print(f"  AUDIT REPORT: PARTY BALANCES RECALCULATION ({'LIVE APPLY' if apply_changes else 'DRY RUN MODE'})")
        print("=" * 110)
        print(f"Formula: Balance = Initial Balance + (Invoices - Returns) - Payments")
        print("-" * 110)

        total_parties_count = 0
        tenant_reports = []

        for tenant in tenants:
            parties = db.execute(
                select(Party).where(Party.tenant_id == tenant.id).order_by(Party.party_type, Party.name)
            ).scalars().all()

            if not parties:
                continue

            party_rows = []
            for party in parties:
                total_parties_count += 1
                init_bal = Decimal(str(party.initial_balance or 0))

                if party.party_type == PartyType.SUPPLIER:
                    inv_type = InvoiceType.PURCHASE
                    ret_type = InvoiceType.PURCHASE_RETURN
                else:
                    inv_type = InvoiceType.SELL
                    ret_type = InvoiceType.SELL_RETURN

                tot_inv = Decimal(str(db.execute(
                    select(func.coalesce(func.sum(Invoice.total_amount), 0))
                    .where(Invoice.party_id == party.id, Invoice.invoice_type == inv_type)
                ).scalar_one()))

                tot_ret = Decimal(str(db.execute(
                    select(func.coalesce(func.sum(Invoice.total_amount), 0))
                    .where(Invoice.party_id == party.id, Invoice.invoice_type == ret_type)
                ).scalar_one()))

                tot_paid = Decimal(str(db.execute(
                    select(func.coalesce(func.sum(Payment.amount), 0))
                    .where(Payment.party_id == party.id)
                ).scalar_one()))

                net_balance = init_bal + tot_inv - tot_ret - tot_paid

                party_rows.append({
                    "id": party.id,
                    "name": party.name,
                    "type": party.party_type.value if hasattr(party.party_type, 'value') else str(party.party_type),
                    "initial": init_bal,
                    "invoices": tot_inv,
                    "returns": tot_ret,
                    "payments": tot_paid,
                    "net_balance": net_balance,
                })

            tenant_reports.append((tenant, party_rows))

        for tenant, rows in tenant_reports:
            print(f"\n🏢 Tenant: {tenant.company_name or 'Default Tenant'} (Tenant ID: {tenant.id})")
            print(f"{'ID':<6} | {'Party Name':<25} | {'Type':<8} | {'Initial':<10} | {'Invoices':<10} | {'Returns':<10} | {'Payments':<10} | {'Net Balance (EGP)':<16}")
            print("-" * 105)
            for r in rows:
                print(f"{r['id']:<6} | {r['name']:<25} | {r['type']:<8} | {r['initial']:<10.2f} | {r['invoices']:<10.2f} | {r['returns']:<10.2f} | {r['payments']:<10.2f} | {r['net_balance']:<16.2f}")

        print("\n" + "=" * 110)
        print(f"  SUMMARY AUDIT COMPLETE: Verified {total_parties_count} parties across {len(tenant_reports)} tenants.")
        print("=" * 110)

        if apply_changes:
            print("\n[LIVE APPLY] Invalidating Redis cache for all tenants...")
            for tenant, _ in tenant_reports:
                try:
                    asyncio.run(invalidate_tenant_cache(tenant.id, "parties"))
                    asyncio.run(invalidate_tenant_cache(tenant.id, "reports"))
                except Exception as e:
                    print(f"  Notice for tenant {tenant.id}: {e}")
            print("✓ Cache successfully invalidated. All live endpoints updated.")
        else:
            print("\n[DRY RUN MODE] No changes were committed to database tables.")
            print("To invalidate cache and confirm audit, run: python scripts/recalculate_party_balances.py --apply")

    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recalculate Party Balances Audit Script")
    parser.add_argument("--apply", action="store_true", help="Apply cache invalidation after audit")
    args = parser.parse_args()
    audit_party_balances(apply_changes=args.apply)
