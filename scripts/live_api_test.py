"""End-to-end check against a RUNNING server (real HTTP + real database).

    python scripts/live_api_test.py [base_url] [output.md]

Walks one realistic shop scenario, asserts every response, and writes a Markdown report.
"""
import json
import sys
import threading
from datetime import datetime, timezone

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUT = sys.argv[2] if len(sys.argv) > 2 else "docs/api-test-results.md"

client = httpx.Client(base_url=BASE, timeout=15)
rows: list[tuple[str, str, int, int, bool]] = []
log: list[str] = []


def call(step, method, path, expect, **kwargs):
    response = client.request(method, path, **kwargs)
    ok = response.status_code == expect
    rows.append((step, f"{method} {path}", expect, response.status_code, ok))
    body = response.text
    try:
        body = json.dumps(response.json(), indent=2)[:900]
    except ValueError:
        pass
    log.append(f"### {len(rows)}. {step}\n`{method} {path}` → **{response.status_code}** (expected {expect})\n```json\n{body or '(empty body)'}\n```\n")
    assert ok, f"{step}: expected {expect}, got {response.status_code}: {response.text}"
    return response.json() if response.content else None


call("Service and database are healthy", "GET", "/health", 200)
cat = call("Create category", "POST", "/categories", 201, json={"name": "Live Test Knitwear", "description": "Created by the live test"})
call("Duplicate category rejected", "POST", "/categories", 409, json={"name": "live test knitwear"})
prod = call("Create product", "POST", "/products", 201,
            json={"sku": "LIVE-001", "name": "Merino Cardigan", "description": "Soft merino wool", "price": "95.50",
                  "stock_quantity": 5, "category_id": cat["id"]})
call("Duplicate SKU rejected", "POST", "/products", 409,
     json={"sku": "LIVE-001", "name": "Dup", "price": "1.00", "category_id": cat["id"]})
call("Invalid price rejected by validation", "POST", "/products", 422,
     json={"sku": "LIVE-002", "name": "Bad", "price": "-5", "category_id": cat["id"]})
call("Read product", "GET", f"/products/{prod['id']}", 200)
updated = call("Update product price", "PUT", f"/products/{prod['id']}", 200,
               json={"sku": "LIVE-001", "name": "Merino Cardigan", "description": "Soft merino wool", "price": "99.00",
                     "category_id": cat["id"], "low_stock_threshold": 2, "is_active": True})
assert updated["price"] == "99.00"
call("List products by category", "GET", "/products", 200, params={"category_id": cat["id"]})

found = call("Search finds the product", "GET", "/search", 200, params={"q": "merino"})
assert [p["sku"] for p in found["products"]] == ["LIVE-001"]
call("Search with no q is rejected", "GET", "/search", 422)

order = call("Place order (reserves stock)", "POST", "/orders", 201,
             json={"customer_name": "Ama Mensah", "customer_email": "ama@example.com",
                   "shipping_address": "12 Market Road, Bolgatanga", "items": [{"product_id": prod["id"], "quantity": 2}]})
assert order["total_amount"] == "198.00" and order["status"] == "pending"
assert call("Stock reduced by the order", "GET", f"/products/{prod['id']}", 200)["stock_quantity"] == 3
call("Order for more than available is refused", "POST", "/orders", 409,
     json={"customer_name": "Kofi", "customer_email": "kofi@example.com", "items": [{"product_id": prod["id"], "quantity": 99}]})
call("Cannot skip order states", "PUT", f"/orders/{order['id']}", 409,
     json={"customer_name": "Ama Mensah", "customer_email": "ama@example.com", "status": "delivered"})
call("Confirm order", "PUT", f"/orders/{order['id']}", 200,
     json={"customer_name": "Ama Mensah", "customer_email": "ama@example.com", "status": "confirmed"})
call("Cannot delete a confirmed order", "DELETE", f"/orders/{order['id']}", 409)
call("Cancel order", "PUT", f"/orders/{order['id']}", 200,
     json={"customer_name": "Ama Mensah", "customer_email": "ama@example.com", "status": "cancelled"})
assert call("Cancelling returned the stock", "GET", f"/products/{prod['id']}", 200)["stock_quantity"] == 5

call("Restock +20", "POST", f"/products/{prod['id']}/stock", 200, json={"change": 20, "reason": "Supplier delivery"})
call("Over-removal refused", "POST", f"/products/{prod['id']}/stock", 409, json={"change": -100, "reason": "Typo"})
history = call("Stock history", "GET", f"/products/{prod['id']}/stock-movements", 200)
assert [m["change"] for m in history] == [20, 2, -2, 5]
call("Low-stock report", "GET", "/products/low-stock", 200)

# Concurrency: 10 shoppers race for the last 3 units. Row locking must stop any overselling.
call("Set up scarce stock", "POST", f"/products/{prod['id']}/stock", 200, json={"change": -22, "reason": "Leave exactly 3"})
results: list[int] = []


def shopper(i):
    r = httpx.post(f"{BASE}/orders", timeout=20, json={"customer_name": f"Racer {i}", "customer_email": f"r{i}@example.com",
                   "items": [{"product_id": prod["id"], "quantity": 1}]})
    results.append(r.status_code)


threads = [threading.Thread(target=shopper, args=(i,)) for i in range(10)]
[t.start() for t in threads]
[t.join() for t in threads]
accepted, refused = results.count(201), results.count(409)
final_stock = client.get(f"/products/{prod['id']}").json()["stock_quantity"]
race_ok = accepted == 3 and refused == 7 and final_stock == 0
rows.append(("10 concurrent orders for 3 units", "POST /orders x10", 3, accepted, race_ok))
log.append(f"### Concurrency check\n10 simultaneous orders for 3 units → **{accepted} accepted, {refused} refused**, final stock **{final_stock}**.\n")
assert race_ok, f"overselling! accepted={accepted} refused={refused} stock={final_stock}"

call("Deleting a product that has orders is blocked", "DELETE", f"/products/{prod['id']}", 409)
call("Unknown order is 404", "GET", "/orders/999999", 404)

passed = sum(1 for r in rows if r[4])
stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
report = [f"# Live API test results\n\nServer: `{BASE}` · Database: PostgreSQL · Run: {stamp}\n",
          f"**{passed}/{len(rows)} checks passed**\n",
          "| # | Check | Request | Expected | Actual | Result |\n|---|---|---|---|---|---|"]
for i, (step, req, exp, act, ok) in enumerate(rows, 1):
    report.append(f"| {i} | {step} | `{req}` | {exp} | {act} | {'PASS' if ok else 'FAIL'} |")
report.append("\n## Request and response log\n")
report.extend(log)
open(OUT, "w").write("\n".join(report))
print(f"{passed}/{len(rows)} checks passed -> {OUT}")
