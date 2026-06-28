"""
fix_tenant_stock_inline.py
===========================
نفس منطق fix_tenant_stock.py لكن يُشغَّل مباشرة من Python
بدون subprocess أو uv wrapper.

الاستخدام:
  cd /mnt/work/ERB/ERB_Backend
  python3 fix_tenant_stock_inline.py 4          # تشخيص فقط
  python3 fix_tenant_stock_inline.py 4 --apply  # إصلاح فعلي
"""

import sys, os, pathlib
from decimal import Decimal

# ── load .env manually ────────────────────────────────────────────────────
env_path = pathlib.Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("❌ DATABASE_URL غير موجودة في .env")
    sys.exit(1)

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session, joinedload, selectinload

# add app to path
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from app.models.domain import (
    Invoice, InvoiceItem, InvoiceType,
    Payment, Party, Product, StockBatch, Tenant
)

engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

# ── args ──────────────────────────────────────────────────────────────────
if len(sys.argv) < 2:
    print("Usage: python3 fix_tenant_stock_inline.py <tenant_id> [--apply]")
    sys.exit(1)

TENANT_ID = int(sys.argv[1])
APPLY = "--apply" in sys.argv
SEP = "─" * 70


def fmt(v) -> str:
    return f"{float(v):,.3f}" if v is not None else "None"


print(f"\n{'═'*70}")
print(f"  🔍 تشخيص Tenant #{TENANT_ID}  |  وضع: {'✏️  تطبيق إصلاح' if APPLY else '👁️  قراءة فقط'}")
print(f"{'═'*70}\n")

fix_count = 0

with Session(engine) as db:
    tenant = db.get(Tenant, TENANT_ID)
    if not tenant:
        print(f"❌ Tenant #{TENANT_ID} غير موجود")
        sys.exit(1)

    print(f"  الشركة: {tenant.company_name}\n")

    # ══════════════════════════════════════════════════════════════════════
    # 1. Stock batches
    # ══════════════════════════════════════════════════════════════════════
    print(SEP)
    print("📦 1. فحص المخزون (StockBatch.remaining_quantity)")
    print(SEP)

    batches = db.execute(
        select(StockBatch)
        .where(StockBatch.tenant_id == TENANT_ID)
        .options(joinedload(StockBatch.product))
        .order_by(StockBatch.id)
    ).unique().scalars().all()

    batch_issues = []
    for batch in batches:
        sold_qty = db.execute(
            select(func.coalesce(func.sum(InvoiceItem.quantity), 0))
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .where(
                InvoiceItem.batch_id == batch.id,
                Invoice.invoice_type == InvoiceType.SELL,
                Invoice.tenant_id == TENANT_ID,
            )
        ).scalar_one()

        sell_ret_qty = db.execute(
            select(func.coalesce(func.sum(InvoiceItem.quantity), 0))
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .where(
                InvoiceItem.batch_id == batch.id,
                Invoice.invoice_type == InvoiceType.SELL_RETURN,
                Invoice.tenant_id == TENANT_ID,
            )
        ).scalar_one()

        purch_ret_qty = db.execute(
            select(func.coalesce(func.sum(InvoiceItem.quantity), 0))
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .where(
                InvoiceItem.batch_id == batch.id,
                Invoice.invoice_type == InvoiceType.PURCHASE_RETURN,
                Invoice.tenant_id == TENANT_ID,
            )
        ).scalar_one()

        initial = Decimal(str(batch.initial_quantity or 0))
        sold    = Decimal(str(sold_qty))
        ret_s   = Decimal(str(sell_ret_qty))
        ret_p   = Decimal(str(purch_ret_qty))

        correct  = initial - sold + ret_s - ret_p
        actual   = Decimal(str(batch.remaining_quantity or 0))
        diff     = correct - actual
        pname    = batch.product.name if batch.product else f"#prod{batch.product_id}"

        if abs(diff) > Decimal("0.001"):
            batch_issues.append((batch, pname, correct, actual, diff))
            status = "⚠️"
        else:
            status = "✅"

        print(
            f"  {status} Batch #{batch.id} [{pname}]  "
            f"init={fmt(initial)} sold={fmt(sold)} "
            f"ret_sell={fmt(ret_s)} ret_purch={fmt(ret_p)}  "
            f"→ صحيح={fmt(correct)}  موجود={fmt(actual)}  Δ={fmt(diff)}"
        )

    if batch_issues:
        print(f"\n  ⚡ {len(batch_issues)} باتش بها خطأ")
        if APPLY:
            for batch, pname, correct, actual, diff in batch_issues:
                batch.remaining_quantity = correct
                print(f"  ✔ صُحِّح Batch #{batch.id} [{pname}]: {fmt(actual)} → {fmt(correct)}")
            fix_count += len(batch_issues)
    else:
        print("  ✅ كل المخزون صحيح\n")

    # ══════════════════════════════════════════════════════════════════════
    # 2. Invoice totals
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{SEP}")
    print("🧾 2. فحص مجاميع الفواتير (Invoice.total_amount)")
    print(SEP)

    invoices = db.execute(
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.tenant_id == TENANT_ID)
        .order_by(Invoice.id)
    ).unique().scalars().all()

    inv_issues = []
    for inv in invoices:
        computed = sum(
            Decimal(str(item.quantity or 0)) * Decimal(str(item.unit_price or 0))
            for item in inv.items
        )
        stored = Decimal(str(inv.total_amount or 0))
        diff = computed - stored
        itype = inv.invoice_type.value if inv.invoice_type else "?"
        party_id = inv.party_id or "?"

        if abs(diff) > Decimal("0.01"):
            inv_issues.append((inv, computed, stored))
            print(
                f"  ⚠️  Invoice #{inv.id} ({itype}) party={party_id}  "
                f"محفوظ={fmt(stored)}  محسوب={fmt(computed)}  Δ={fmt(diff)}"
            )
        else:
            print(f"  ✅ Invoice #{inv.id} ({itype})  {fmt(stored)} ✓")

    if inv_issues:
        print(f"\n  ⚡ {len(inv_issues)} فاتورة بها خطأ")
        if APPLY:
            for inv, computed, stored in inv_issues:
                inv.total_amount = computed
                print(f"  ✔ صُحِّح Invoice #{inv.id}: {fmt(stored)} → {fmt(computed)}")
            fix_count += len(inv_issues)
    else:
        print("  ✅ كل مجاميع الفواتير صحيحة\n")

    # ══════════════════════════════════════════════════════════════════════
    # 3. Party financial summary
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{SEP}")
    print("💰 3. ملخص مالي للأطراف")
    print(SEP)

    parties = db.execute(
        select(Party).where(Party.tenant_id == TENANT_ID).order_by(Party.id)
    ).scalars().all()

    for p in parties:
        def qsum(itype):
            return Decimal(str(db.execute(
                select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                    Invoice.party_id == p.id,
                    Invoice.invoice_type == itype,
                    Invoice.tenant_id == TENANT_ID,
                )
            ).scalar_one()))

        sell      = qsum(InvoiceType.SELL)
        sell_r    = qsum(InvoiceType.SELL_RETURN)
        purch     = qsum(InvoiceType.PURCHASE)
        purch_r   = qsum(InvoiceType.PURCHASE_RETURN)
        paid      = Decimal(str(db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.party_id == p.id)
        ).scalar_one()))
        initial   = Decimal(str(p.initial_balance or 0))

        if p.party_type and p.party_type.value == "client":
            balance = initial + sell - sell_r - paid
            ptype = "🧑 عميل"
            detail = f"بيع={fmt(sell)}  مرتجع بيع={fmt(sell_r)}"
        else:
            balance = initial + purch - purch_r - paid
            ptype = "🏭 مورد"
            detail = f"شراء={fmt(purch)}  مرتجع شراء={fmt(purch_r)}"

        print(
            f"\n  {ptype} #{p.id} {p.name}\n"
            f"    {detail}  مدفوع(صافي)={fmt(paid)}\n"
            f"    رصيد مبدئي={fmt(initial)}  →  الرصيد الحالي = {fmt(balance)}"
        )

    # ══════════════════════════════════════════════════════════════════════
    # commit / rollback
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'═'*70}")
    if APPLY:
        if fix_count > 0:
            db.commit()
            print(f"  ✅ تم حفظ {fix_count} إصلاح في قاعدة البيانات بنجاح")
        else:
            print("  ✅ لا توجد أخطاء — لم يتغير شيء")
    else:
        db.rollback()
        print("  👁️  وضع قراءة فقط — لم يُحفظ أي تغيير")
        print("  ▶  شغّل مع  --apply  لتطبيق الإصلاحات فعلاً")
    print(f"{'═'*70}\n")
