"""Run both mocks: python -m mock [--crm-port 8701] [--sheet-port 8702] [--fail-429 N]"""
import argparse
import time

from .servers import MockServer, seed_contacts

p = argparse.ArgumentParser()
p.add_argument("--crm-port", type=int, default=8701)
p.add_argument("--sheet-port", type=int, default=8702)
p.add_argument("--fail-429", type=int, default=0, help="CRM answers 429 to the first N requests")
a = p.parse_args()
recs = seed_contacts()
recs[6] = {"id": 6, "first_name": "Bad", "last_name": "Date", "email": "bad@example.com", "status": "A",
           "created": "31/12/2026", "updated_at": "2026-06-09T10:00:00.000000Z"}  # demo: lands in 'failed'
crm = MockServer("crm", a.crm_port, a.fail_429, recs).start()
sheet = MockServer("sheet", a.sheet_port).start()
print(f"crm   (source) {crm.url}/contacts  token: demo-crm-token")
print(f"sheet (target) {sheet.url}/rows      key:   demo-sheet-key")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
