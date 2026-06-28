"""
fix_tenant_stock.py
====================
سكريبت تشخيص وإصلاح شامل لبيانات تينانت محدد.

المشاكل التي يعالجها:
  1. remaining_quantity في stock_batches أقل أو أكثر مما يجب
     (يُعيد حسابها من invoice_items الفعلية)
  2. total_amount في الفواتير لا يتطابق مع مجموع أسطر البنود
  3. مرتجعات مرتبطة بـ original_invoice_item_id لكن لم تُنقص المخزون
  4. عرض تقرير مالي مختصر (رصيد، إجمالي مدفوع، إجمالي مرتجعات)

الاستخدام:
  uv run python fix_tenant_stock.py --tenant-id 4
  uv run python fix_tenant_stock.py --tenant-id 4 --apply   ← لتطبيق الإصلاح فعلياً
"""

import argparse
import sys
from decimal import Decimal

from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import Session, joinedload, selectinload

# ── نفس الإعدادات الموجودة في التطبيق ─────────────────────────────────────
import os, pathlib

# حمّل .env يدوياً دون استيراد التطبيق كله
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

engine = create_engine(DATABASE_URL, echo=False)

# استورد النماذج بعد ما اتأكدنا من الـ env
from app.models.domain import (
    Invoice, InvoiceItem, InvoiceType,
    Payment, Party, Product, StockBatch, Tenant
)

# ───────────────────────────────────────────────────────────────────────────

SEPARATOR = "─" * 70

def fmt(v) -> str:
    return f"{float(v):,.2f}" if v is not None else "None"


def run_diagnostics(db: Session, tenant_id: int, apply_fixes: bool):
    print(f"\n{'═'*70}")
    print(f"  🔍 تشخيص Tenant #{tenant_id}")
    print(f"{'═'*70}\n")

    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        print(f"❌ Tenant #{tenant_id} غير موجود")
        return
    print(f"  الشركة: {tenant.company_name}\n")

    fix_count = 0

    # ════════════════════════════════════════════════════════════════════════
    # 1. فحص remaining_quantity في stock_batches
    # ════════════════════════════════════════════════════════════════════════
    print(SEPARATOR)
    print("📦 1. فحص المخزون (StockBatch.remaining_quantity)")
    print(SEPARATOR)

    batches = db.execute(
        select(StockBatch)
        .join(Product, StockBatch.product_id == Product.id)
        .where(StockBatch.tenant_id == tenant_id)
        .options(joinedload(StockBatch.product))
        .order_by(StockBatch.id)
    ).unique().scalars().all()

    batch_issues = []
    for batch in batches:
        # الكمية المباعة من هذا الباتش في فواتير البيع (SELL)
        sold_qty = db.execute(
            select(func.coalesce(func.sum(InvoiceItem.quantity), 0))
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .where(
                InvoiceItem.batch_id == batch.id,
                Invoice.invoice_type == InvoiceType.SELL,
                Invoice.tenant_id == tenant_id,
            )
        ).scalar_one()

        # الكمية المُرجَّعة لهذا الباتش من مرتجعات البيع (SELL_RETURN)
        returned_qty = db.execute(
            select(func.coalesce(func.sum(InvoiceItem.quantity), 0))
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .where(
                InvoiceItem.batch_id == batch.id,
                Invoice.invoice_type == InvoiceType.SELL_RETURN,
                Invoice.tenant_id == tenant_id,
            )
        ).scalar_one()

        # الكمية المُرجَّعة للمورد من هذا الباتش (PURCHASE_RETURN)
        purchase_returned_qty = db.execute(
            select(func.coalesce(func.sum(InvoiceItem.quantity), 0))
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .where(
                InvoiceItem.batch_id == batch.id,
                Invoice.invoice_type == InvoiceType.PURCHASE_RETURN,
                Invoice.tenant_id == tenant_id,
            )
        ).scalar_one()

        initial = Decimal(str(batch.initial_quantity or 0))
        sold = Decimal(str(sold_qty))
        ret_sell = Decimal(str(returned_qty))
        ret_purch = Decimal(str(purchase_returned_qty))

        # الصحيح = initial - sold + sell_returns - purchase_returns
        correct_remaining = initial - sold + ret_sell - ret_purch
        actual_remaining = Decimal(str(batch.remaining_quantity or 0))
        diff = correct_remaining - actual_remaining

        if abs(diff) > Decimal("0.001"):
            product_name = batch.product.name if batch.product else f"#{batch.product_id}"
            batch_issues.append({
                "batch": batch,
                "product_name": product_name,
                "initial": initial,
                "sold": sold,
                "ret_sell": ret_sell,
                "ret_purch": ret_purch,
                "correct": correct_remaining,
                "actual": actual_remaining,
                "diff": diff,
            })
            print(
                f"  ⚠️  Batch #{batch.id} [{product_name}]\n"
                f"      initial={fmt(initial)}, sold={fmt(sold)}, "
                f"sell_ret={fmt(ret_sell)}, purch_ret={fmt(ret_purch)}\n"
                f"      الصحيح={fmt(correct_remaining)}  "
                f"الموجود={fmt(actual_remaining)}  "
                f"الفرق={fmt(diff)}"
            )

    if not batch_issues:
        print("  ✅ كل المخزون صحيح - لا توجد أخطاء\n")
    else:
        print(f"\n  ⚡ {len(batch_issues)} باتش به خطأ")
        if apply_fixes:
            for issue in batch_issues:
                issue["batch"].remaining_quantity = issue["correct"]
                print(f"  ✔ تم تصحيح Batch #{issue['batch'].id} [{issue['product_name']}] → {fmt(issue['correct'])}")
            fix_count += len(batch_issues)
        else:
            print("  ℹ️  شغّل مع --apply لتطبيق الإصلاح\n")

    # ════════════════════════════════════════════════════════════════════════
    # 2. فحص total_amount في الفواتير
    # ════════════════════════════════════════════════════════════════════════
    print(f"\n{SEPARATOR}")
    print("🧾 2. فحص مجاميع الفواتير (Invoice.total_amount)")
    print(SEPARATOR)

    invoices = db.execute(
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.tenant_id == tenant_id)
        .order_by(Invoice.id)
    ).unique().scalars().all()

    invoice_issues = []
    for inv in invoices:
        computed = sum(
            Decimal(str(item.quantity or 0)) * Decimal(str(item.unit_price or 0))
            for item in inv.items
        )
        stored = Decimal(str(inv.total_amount or 0))
        diff = computed - stored
        if abs(diff) > Decimal("0.01"):
            invoice_issues.append({
                "inv": inv,
                "computed": computed,
                "stored": stored,
                "diff": diff,
            })
            print(
                f"  ⚠️  Invoice #{inv.id} ({inv.invoice_type.value if inv.invoice_type else '?'})\n"
                f"      الفاتورة المحفوظة={fmt(stored)}  "
                f"المحسوبة={fmt(computed)}  فرق={fmt(diff)}"
            )

    if not invoice_issues:
        print("  ✅ كل مجاميع الفواتير صحيحة\n")
    else:
        print(f"\n  ⚡ {len(invoice_issues)} فاتورة بها خطأ")
        if apply_fixes:
            for issue in invoice_issues:
                issue["inv"].total_amount = issue["computed"]
                print(
                    f"  ✔ تم تصحيح Invoice #{issue['inv'].id} "
                    f"→ {fmt(issue['computed'])}"
                )
            fix_count += len(invoice_issues)
        else:
            print("  ℹ️  شغّل مع --apply لتطبيق الإصلاح\n")

    # ════════════════════════════════════════════════════════════════════════
    # 3. تقرير مالي للعملاء/الموردين
    # ════════════════════════════════════════════════════════════════════════
    print(f"\n{SEPARATOR}")
    print("💰 3. ملخص مالي للأطراف (Parties)")
    print(SEPARATOR)

    parties = db.execute(
        select(Party).where(Party.tenant_id == tenant_id).order_by(Party.id)
    ).scalars().all()

    for party in parties:
        total_sell = db.execute(
            select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                Invoice.party_id == party.id,
                Invoice.invoice_type == InvoiceType.SELL,
                Invoice.tenant_id == tenant_id,
            )
        ).scalar_one()
        total_sell_ret = db.execute(
            select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                Invoice.party_id == party.id,
                Invoice.invoice_type == InvoiceType.SELL_RETURN,
                Invoice.tenant_id == tenant_id,
            )
        ).scalar_one()
        total_purchase = db.execute(
            select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                Invoice.party_id == party.id,
                Invoice.invoice_type == InvoiceType.PURCHASE,
                Invoice.tenant_id == tenant_id,
            )
        ).scalar_one()
        total_purchase_ret = db.execute(
            select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                Invoice.party_id == party.id,
                Invoice.invoice_type == InvoiceType.PURCHASE_RETURN,
                Invoice.tenant_id == tenant_id,
            )
        ).scalar_one()
        total_paid = db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.party_id == party.id
            )
        ).scalar_one()

        initial = Decimal(str(party.initial_balance or 0))
        sell = Decimal(str(total_sell))
        sell_r = Decimal(str(total_sell_ret))
        purch = Decimal(str(total_purchase))
        purch_r = Decimal(str(total_purchase_ret))
        paid = Decimal(str(total_paid))

        if party.party_type and party.party_type.value == "client":
            balance = initial + sell - sell_r - paid
            ptype = "🧑 عميل"
        else:
            balance = initial + purch - purch_r - paid
            ptype = "🏭 مورد"

        print(
            f"  {ptype} #{party.id} {party.name}\n"
            f"    رصيد مبدئي={fmt(initial)} | بيع={fmt(sell)} | مرتجع={fmt(sell_r)}"
            f" | شراء={fmt(purch)} | مرتجع شراء={fmt(purch_r)}\n"
            f"    مدفوع={fmt(paid)} (شامل الدفعات السالبة) → الرصيد={fmt(balance)}\n"
        )

    # ════════════════════════════════════════════════════════════════════════
    # 4. commit أو rollback
    # ════════════════════════════════════════════════════════════════════════
    if apply_fixes:
        if fix_count > 0:
            db.commit()
            print(f"\n{'='*70}")
            print(f"  ✅ تم تطبيق {fix_count} إصلاح بنجاح وحفظها في قاعدة البيانات")
            print(f"{'='*70}\n")
        else:
            print("\n  ✅ لا توجد أخطاء، لم يتم تغيير أي شيء\n")
    else:
        db.rollback()
        print(f"\n{'='*70}")
        print("  🔍 وضع القراءة فقط — لم يتغير شيء في قاعدة البيانات")
        print("  شغّل مع --apply لتطبيق الإصلاحات")
        print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description="إصلاح بيانات Tenant")
    parser.add_argument("--tenant-id", type=int, required=True, help="رقم الـ Tenant")
    parser.add_argument(
        "--apply", action="store_true",
        help="طبّق الإصلاحات فعلاً (بدونها وضع قراءة فقط)"
    )
    args = parser.parse_args()

    with Session(engine) as db:
        run_diagnostics(db, args.tenant_id, args.apply)


if __name__ == "__main__":
    main()
