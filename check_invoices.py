import os, psycopg2
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()
cur.execute("SELECT invoice_type, COUNT(*) FROM invoices GROUP BY invoice_type;")
print("Invoices types and counts:")
print(cur.fetchall())
cur.close()
conn.close()
