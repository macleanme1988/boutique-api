# Boutique Web API

A RESTful API for a boutique shop: product catalogue, orders, inventory and search.
**Python 3.13 · FastAPI · SQLAlchemy 2 · PostgreSQL 16 (separate container) · OpenAPI 3.1 / Swagger UI**

## Quick start (Docker)

```bash
docker compose up --build            # API on :8000, PostgreSQL in its own container
docker compose exec api python -m app.seed    # optional: 3 categories, 8 products
```

* Swagger UI: <http://localhost:8000/docs> · ReDoc: <http://localhost:8000/redoc> · Spec: <http://localhost:8000/openapi.json>
* The database container has no published port, so only the API can reach it. Passwords come from `.env` (copy `.env.example`).

## Observability (OpenTelemetry → Collector → Prometheus / Tempo / Loki → Grafana)

`docker compose up --build -d` also starts the full telemetry stack:

| Service | URL | Role |
|---|---|---|
| Grafana | <http://localhost:3000> | Dashboard **Boutique API: Unified Observability**, Explore (no login, demo only) |
| Prometheus | <http://localhost:9090> | Metrics (scrapes the Collector) |
| Tempo | <http://localhost:3200> | Traces (queried through Grafana) |
| Loki | <http://localhost:3100> | Logs (queried through Grafana) |

* App instrumentation: `app/telemetry.py` (SDK, exporters, FastAPI + SQLAlchemy auto-instrumentation), `app/tracing.py` (manual spans), `app/metrics.py` (business metrics).
* Pipeline configuration: `observability/` (Collector, Prometheus, Tempo, Loki, Grafana provisioning and dashboard JSON).
* Every response carries an `X-Trace-Id` header; log lines contain `trace_id=` and `span_id=`, which is what links logs and traces.
* Customer names, e-mails and addresses are never put in telemetry (`customer_email` in URLs is redacted).
* Switch off with `OTEL_ENABLED=false`.
* Generate demo traffic: `docker compose --profile tools run --rm traffic`.
* **Step-by-step evidence capture: [`docs/OBSERVABILITY_EVIDENCE_GUIDE.md`](docs/OBSERVABILITY_EVIDENCE_GUIDE.md)**

## Run locally without Docker

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://boutique:boutique@localhost:5432/boutique   # any reachable PostgreSQL
python -m app.seed
uvicorn app.main:app --reload
```

## Endpoints

| Resource | Endpoints |
|---|---|
| **Categories** | `GET/POST /categories` · `GET/PUT/DELETE /categories/{id}` |
| **Products** | `GET/POST /products` · `GET/PUT/DELETE /products/{id}` |
| **Orders** | `GET/POST /orders` · `GET/PUT/DELETE /orders/{id}` |
| **Search** | `GET /search?q=` (+ `category_id`, `min_price`, `max_price`, `in_stock`, `skip`, `limit`) |
| **Inventory** | `POST /products/{id}/stock` · `GET /products/{id}/stock-movements` · `GET /products/low-stock` |
| **Health** | `GET /health` |

Errors are `{"detail": "..."}` with **404** (not found), **409** (conflict) or **422** (validation).

## Business rules worth knowing

* **Placing an order** validates every line, locks the product rows (`SELECT ... FOR UPDATE`, in id order to avoid deadlocks), checks stock, freezes each unit price, computes the total and reduces stock, all in one transaction. If any line fails, nothing is reserved.
* **Status lifecycle:** `pending → confirmed → shipped → delivered`; `cancelled` is allowed from `pending` or `confirmed`. Delivered and cancelled orders are final. Cancelling returns the stock.
* **`DELETE /orders/{id}`** is allowed only for pending or cancelled orders (a pending one is restocked first). Order history of fulfilled orders is kept.
* **`DELETE /products/{id}`** is refused (409) if the product appears in an order; set `is_active=false` instead. Inactive products disappear from search and cannot be ordered.
* **`PUT`** is a full replacement of the editable fields. Stock is deliberately *not* editable through `PUT /products`; every stock change goes through `/stock` or an order, so the `inventory_movements` table is a complete audit trail.
* **Search** is case-insensitive over name, description and SKU (name matches first), also matches category names, and treats `%` and `_` as literal characters.
* Money is `NUMERIC(10,2)` / `Decimal`, never float. Database `CHECK` constraints back up the API validation (price > 0, stock >= 0, quantity > 0).

## Tests and coverage

```bash
pytest --cov --cov-report=term-missing --cov-report=html:docs/coverage-html     # fast, in-memory SQLite
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/boutique_test pytest   # same 59 tests on PostgreSQL
```

59 tests, **100 % line and branch coverage**. Eight lines are excluded with `# pragma: no cover`: the two
`except IntegrityError` handlers that only fire if a row is added concurrently at the exact moment of a delete (not
reproducible in a unit test), and the `if __name__ == "__main__"` guard in `app/seed.py`. Overselling under concurrent
orders is tested separately in `scripts/live_api_test.py` against PostgreSQL.

End-to-end checks against a running server:

```bash
python scripts/live_api_test.py http://localhost:8000      # 27 checks incl. 10 concurrent orders for 3 units
python scripts/run_http_files.py http://localhost:8000     # runs every request in http/*.http
python scripts/swagger_screenshots.py                      # regenerates the Swagger screenshots
```
Both scripts create data (and the `.http` run deletes some), so run them once on a freshly seeded database:
`TRUNCATE inventory_movements, order_items, orders, products, categories RESTART IDENTITY CASCADE;` then `python -m app.seed`.

## `.http` collection

`http/*.http` (categories, products, inventory, orders, search), written for the VS Code *REST Client* extension.
Each request title states the status it should return (`-> 409`). Seed data gives ids 1-3 (categories) and 1-8 (products).

## Evidence pack (`docs/`)

| Evidence | File |
|---|---|
| OpenAPI specification | `docs/openapi.json` |
| Swagger UI screenshots | `docs/screenshots/01…06-*.png` (overview, executed POST /orders, search, low-stock, request docs, schemas) |
| Database schema diagram | `docs/database-schema.png` (source: `docs/schema.mmd`) |
| Successful API test results | `docs/api-test-results.md` (27/27, live PostgreSQL) · `docs/http-files-run.md` (40/40) |
| Unit test results | `docs/test-results-unit.txt` (SQLite) · `docs/test-results-postgres.txt` (PostgreSQL) · `docs/junit.xml` |
| Coverage report | `docs/coverage-html/index.html` · `docs/coverage.xml` · `docs/screenshots/07-coverage-report.png` |

## Known limitations (deliberate, for a first version)

* **No authentication or authorisation.** Anyone who can reach the API can change prices and orders. Add OAuth2/JWT before exposing it.
* **Tables are created at startup (`create_all`)**, not through migrations. Use Alembic before changing the schema on a database that holds real data.
* Orders have a single currency and no payment, tax or shipping-cost logic.
* List endpoints use `skip`/`limit` and do not return a total count (search does).
