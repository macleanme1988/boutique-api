"""Capture Swagger UI evidence screenshots from the running API.

    python scripts/swagger_screenshots.py [base_url] [swagger_dist_dir] [out_dir]

swagger_dist_dir is only needed when the machine cannot reach cdn.jsdelivr.net: the
assets FastAPI normally loads from the CDN are then served from a local swagger-ui-dist copy.
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
DIST = Path(sys.argv[2]) if len(sys.argv) > 2 else None
OUT = Path(sys.argv[3] if len(sys.argv) > 3 else "docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


def try_it(page, op_id, body=None, params=None):
    block = page.locator(f"#{op_id}")
    block.locator(".opblock-summary").first.click()
    block.locator(".try-out__btn").click()
    if params:
        for name, value in params.items():
            block.locator(f"tr[data-param-name='{name}'] input").fill(value)
    if body is not None:
        block.locator("textarea.body-param__text").fill(json.dumps(body, indent=2))
    block.locator(".execute").click()
    block.locator(".live-responses-table").wait_for(timeout=15000)
    page.wait_for_timeout(600)
    return block


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_context(viewport={"width": 1400, "height": 900}, device_scale_factor=2).new_page()
    if DIST:
        page.route("**/swagger-ui-bundle.js", lambda r: r.fulfill(path=str(DIST / "swagger-ui-bundle.js"), content_type="application/javascript"))
        page.route("**/swagger-ui.css", lambda r: r.fulfill(path=str(DIST / "swagger-ui.css"), content_type="text/css"))
    page.route("**/fastapi.tiangolo.com/**", lambda r: r.abort())
    page.goto(f"{BASE}/docs")
    page.wait_for_selector(".opblock-summary", timeout=20000)

    page.screenshot(path=OUT / "01-swagger-overview.png", full_page=True)

    block = try_it(page, "operations-Orders-create_order_orders_post",
                   body={"customer_name": "Ama Mensah", "customer_email": "ama@example.com",
                         "shipping_address": "12 Market Road, Bolgatanga",
                         "items": [{"product_id": 1, "quantity": 2}]})
    block.screenshot(path=OUT / "02-post-orders-try-it-out.png")
    block.locator(".opblock-summary").first.click()

    block = try_it(page, "operations-Search-search_search_get", params={"q": "linen"})
    block.screenshot(path=OUT / "03-get-search-try-it-out.png")
    block.locator(".opblock-summary").first.click()

    block = try_it(page, "operations-Inventory-low_stock_products_products_low_stock_get")
    block.screenshot(path=OUT / "04-get-low-stock-try-it-out.png")
    block.locator(".opblock-summary").first.click()

    block = page.locator("#operations-Products-create_product_products_post")
    block.locator(".opblock-summary").first.click()
    page.wait_for_timeout(400)
    block.screenshot(path=OUT / "05-post-products-documentation.png")
    block.locator(".opblock-summary").first.click()

    models = page.locator("section.models")
    if "is-open" not in (models.get_attribute("class") or ""):  # open by default; guard other versions
        models.locator("h4 button").click()
    models.locator("article").first.wait_for(timeout=10000)
    for schema_name in ("OrderCreate", "ProductOut"):  # expand two schemas to show their fields
        models.locator("button.json-schema-2020-12-accordion", has_text=schema_name).first.click()
    page.wait_for_timeout(500)
    page.locator("section.models").screenshot(path=OUT / "06-schemas.png")
    browser.close()
print("saved:", *sorted(f.name for f in OUT.iterdir()), sep="\n  ")
