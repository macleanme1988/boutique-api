"""Generate realistic traffic against the Boutique API so the dashboards have something to show.

    docker compose --profile tools run --rm traffic          # inside Docker (uses http://api:8000)
    python scripts/generate_traffic.py                       # from your laptop (uses http://localhost:8000)

Options (environment variables):  API_URL, DURATION (seconds, default 90), PAUSE (seconds between requests, default 0.15)

Uses only the Python standard library. At the end it places ONE order that is refused (not enough stock) and
prints that request's trace id: the "sample request" for the trace-to-log demonstration.
"""
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
DURATION = float(os.environ.get("DURATION", "90"))
PAUSE = float(os.environ.get("PAUSE", "0.15"))

CATALOGUE = {
    "Dresses": [("DRS-001", "Linen Wrap Dress", "89.90", 40), ("DRS-002", "Satin Evening Dress", "149.00", 25),
                ("DRS-003", "Kente Print Midi Dress", "120.00", 30)],
    "Tops": [("TOP-001", "Silk Camisole", "54.50", 60), ("TOP-002", "Cotton Peplum Blouse", "39.00", 4)],
    "Accessories": [("ACC-001", "Leather Belt", "35.00", 80), ("ACC-002", "Woven Straw Tote", "72.00", 30),
                    ("ACC-003", "Silk Scarf", "28.00", 0)],
}
SEARCH_TERMS = ["dress", "silk", "leather", "kente", "tote", "belt", "linen", "scarf", "blouse", "zzzz-no-match"]
CUSTOMERS = [("Ama Mensah", "ama@example.com"), ("Kofi Boateng", "kofi@example.com"), ("Esi Owusu", "esi@example.com")]


def call(method, path, body=None):
    """Send one request; return (status_code, parsed_json_or_None, trace_id_header)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None), resp.headers.get("X-Trace-Id")
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        return err.code, parsed, err.headers.get("X-Trace-Id")


def wait_for_api():
    for _ in range(60):
        try:
            if call("GET", "/health")[0] == 200:
                return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(2)
    sys.exit(f"The API at {API} did not become ready.")


def ensure_catalogue():
    """Create the demo catalogue if the shop is empty; return the list of products."""
    status, products, _ = call("GET", "/products?limit=100")
    if status == 200 and products:
        return products
    print("Catalogue is empty: creating demo categories and products ...")
    for category_name, items in CATALOGUE.items():
        _, category, _ = call("POST", "/categories", {"name": category_name, "description": f"{category_name} for every season"})
        for sku, name, price, stock in items:
            call("POST", "/products", {"sku": sku, "name": name, "price": price, "category_id": category["id"],
                                       "stock_quantity": stock})
    return call("GET", "/products?limit=100")[1]


def one_request(products, counts):
    """Pick a random realistic action. Weights favour browsing, with a steady trickle of orders and errors."""
    in_stock = [p for p in products if p["stock_quantity"] > 0 and p["is_active"]]
    action = random.choices(
        ["browse", "view", "search", "order", "order_too_many", "unknown_product", "missing", "restock", "categories"],
        weights=[20, 14, 18, 16, 5, 3, 4, 5, 6],
    )[0]
    if action == "browse":
        result = call("GET", "/products?limit=20")
    elif action == "view":
        result = call("GET", f"/products/{random.choice(products)['id']}")
    elif action == "search":
        result = call("GET", "/search?q=" + urllib.parse.quote(random.choice(SEARCH_TERMS)))
    elif action == "order" and in_stock:
        name, email = random.choice(CUSTOMERS)
        lines = [{"product_id": p["id"], "quantity": random.randint(1, 2)} for p in random.sample(in_stock, k=min(len(in_stock), random.randint(1, 3)))]
        result = call("POST", "/orders", {"customer_name": name, "customer_email": email, "shipping_address": "12 Market Road, Bolgatanga", "items": lines})
    elif action == "order_too_many":
        name, email = random.choice(CUSTOMERS)
        result = call("POST", "/orders", {"customer_name": name, "customer_email": email,
                                          "items": [{"product_id": random.choice(products)["id"], "quantity": 900}]})
    elif action == "unknown_product":
        name, email = random.choice(CUSTOMERS)
        result = call("POST", "/orders", {"customer_name": name, "customer_email": email, "items": [{"product_id": 999999, "quantity": 1}]})
    elif action == "missing":
        result = call("GET", "/products/999999")
    elif action == "restock":
        result = call("POST", f"/products/{random.choice(products)['id']}/stock", {"change": random.randint(5, 20), "reason": "Supplier delivery"})
    elif action == "categories":
        result = call("GET", "/categories")
    else:
        result = call("GET", "/products?limit=5")
    counts[result[0]] = counts.get(result[0], 0) + 1


def main():
    wait_for_api()
    products = ensure_catalogue()
    print(f"Sending traffic to {API} for {DURATION:.0f}s ...")
    counts, end, last_refresh = {}, time.time() + DURATION, time.time()
    while time.time() < end:
        one_request(products, counts)
        if time.time() - last_refresh > 10:  # keep stock levels fresh
            products, last_refresh = call("GET", "/products?limit=100")[1] or products, time.time()
        time.sleep(PAUSE)
    print("Responses by status code:", dict(sorted(counts.items())))

    # The sample request for the trace-to-log demo: a refused order (409), easy to spot in every tool.
    target = max(products, key=lambda p: p["stock_quantity"])
    status, body, trace_id = call("POST", "/orders", {"customer_name": "Sample Customer", "customer_email": "sample@example.com",
                                                      "items": [{"product_id": target["id"], "quantity": 999}]})
    print()
    print("=" * 70)
    print("SAMPLE REQUEST FOR THE TRACE-TO-LOG DEMO")
    print(f"  POST /orders  ->  HTTP {status}  ({body['detail'] if body else ''})")
    print(f"  trace id: {trace_id}")
    print("=" * 70)


if __name__ == "__main__":
    main()
