import os

files_to_delete = [
    "add_column.py",
    "add_column2.py",
    "check_batches.py",
    "check_db.py",
    "check_invoices.py",
    "debug.py",
    "fix_db.py",
    "fix_db2.py",
    "fix_zero_prices.py",
    "migrate_parties.py",
    "migrate_stockbatch_party.py",
    "price_audit.txt",
    "scratch_test_delete.py",
    "test_db.py",
    "test_delete.py",
    "test_dump.py",
    "test_prices.py",
    "test_products.py",
    "test_summary.py",
    "app/routers/customers.py",
    "app/routers/suppliers.py",
]

for f in files_to_delete:
    if os.path.exists(f):
        try:
            os.remove(f)
            print(f"Deleted {f}")
        except Exception as e:
            print(f"Failed to delete {f}: {e}")
    else:
        print(f"File {f} not found")

try:
    if os.path.exists("app/routers") and not os.listdir("app/routers"):
        os.rmdir("app/routers")
        print("Deleted empty directory app/routers")
except Exception as e:
    pass

print("Cleanup complete.")
