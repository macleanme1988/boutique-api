# Observability evidence guide: take every screenshot yourself

Everything runs on your own laptop with Docker Desktop. Commands are for **PowerShell**.
Total time: about 30 minutes. Take screenshots with **Windows + Shift + S** (drag over the area, then paste into Word or save).

**What you are proving**

```
Boutique API --OTLP--> OpenTelemetry Collector --+--> Prometheus (metrics)
 (traces, metrics, logs)                         +--> Tempo      (traces)
                                                 +--> Loki       (logs)
                                    Grafana reads all three, and links a trace to its logs
```

---

## Part 0: Start the stack

1. Open **Docker Desktop** and wait until it says *Engine running*.
2. Open PowerShell in the project folder:
   ```powershell
   cd C:\Users\Supremo\boutique-api
   ```
3. Build and start everything (first time downloads about 1.5 GB, so be patient):
   ```powershell
   docker compose up --build -d
   ```
   `up` starts the services, `--build` rebuilds the API with the new instrumentation, `-d` runs them in the background.
4. Check that all containers are running (wait about 30 seconds first):
   ```powershell
   docker compose ps
   ```
   You should see `db`, `api`, `otel-collector`, `prometheus`, `tempo`, `loki` and `grafana` with status **Up** (db shows *healthy*).
   If one says *Exited*, run `docker compose logs <name>` (for example `docker compose logs loki`) and send me the last 20 lines.
5. Open <http://localhost:8000/health>. You should see `{"status":"ok","database":"reachable"}`.

### Generate traffic

```powershell
docker compose --profile tools run --rm traffic
```

This sends about 90 seconds of realistic shop traffic: browsing, searching, orders, restocks and deliberate errors (404, 409, 422).
**When it finishes it prints a box like this. Copy the trace id, because you need it in Part 6:**

```
SAMPLE REQUEST FOR THE TRACE-TO-LOG DEMO
  POST /orders  ->  HTTP 409  (Insufficient stock for ...)
  trace id: 34aa392aec153cbb2ecc224cbe734764
```

> Run the traffic command a second time if you want more data in the graphs. Each run prints a new trace id; use the latest one.

---

## Part 1: OpenTelemetry configuration files (evidence 1)

Take a screenshot of each file open in VS Code, Notepad, or printed in PowerShell:

| # | File | What the screenshot shows | PowerShell to display it |
|---|------|---------------------------|--------------------------|
| 1a | `app\telemetry.py` | SDK setup: TracerProvider, MeterProvider, LoggerProvider, OTLP exporters, FastAPI and SQLAlchemy auto-instrumentation | `Get-Content app\telemetry.py` |
| 1b | `app\tracing.py` and one router, e.g. `app\routers\orders.py` | Manual spans (`orders.create`, `orders.check_stock` ...) | `Get-Content app\tracing.py` |
| 1c | `observability\otel-collector-config.yaml` | Receivers, processors, spanmetrics, exporters, pipelines | `Get-Content observability\otel-collector-config.yaml` |
| 1d | `observability\prometheus.yml`, `tempo.yaml`, `loki-config.yaml` | Backend configuration | `Get-Content observability\prometheus.yml` |
| 1e | `observability\grafana\provisioning\datasources\datasources.yaml` | The trace-to-log link settings (`tracesToLogsV2`, `derivedFields`) | `Get-Content observability\grafana\provisioning\datasources\datasources.yaml` |
| 1f | `docker-compose.yml` | The whole pipeline wired together (the `OTEL_*` variables on `api`) | `Get-Content docker-compose.yml` |

Tip: opening the files in VS Code gives cleaner screenshots than PowerShell.

---

## Part 2: Prometheus metrics screenshots (evidence 2)

Open <http://localhost:9090>.

**Screenshot 2a: targets are healthy**
1. Top menu: **Status -> Target health** (older wording: *Targets*).
2. Screenshot showing `boutique-telemetry`, `otel-collector`, `prometheus` all **UP**.

**Screenshot 2b to 2e: run each query**
Click **Graph** (or **Query**), paste the query in the box, press **Execute**, then open the **Graph** tab and take the screenshot.

| # | What it proves | Paste this query |
|---|----------------|------------------|
| 2b | Request rate per route (auto-instrumentation) | `sum by (http_method, http_target) (rate(http_server_duration_milliseconds_count[1m]))` |
| 2c | Latency p95 per route | `histogram_quantile(0.95, sum by (le, http_target) (rate(http_server_duration_milliseconds_bucket[1m])))` |
| 2d | Custom business metric: orders refused, by reason | `sum by (reason) (boutique_orders_rejected_total)` |
| 2e | Metrics created from traces (spanmetrics) for the manual spans | `sum by (span_name) (traces_span_metrics_calls_total{span_name=~"orders.*"})` |

(If a graph looks empty, widen the time range at the top to **15m** and re-run the traffic command.)

Optional 2f: type `boutique_` in the query box. The autocomplete list shows every custom metric.

---

## Part 3: Grafana dashboard screenshots (evidence 3)

Open <http://localhost:3000>. There is no login (demo setup). The dashboard **Boutique API: Unified Observability** is the home page. If you do not see it: **Dashboards -> Boutique -> Boutique API: Unified Observability**.

1. Set the time range (top right) to **Last 15 minutes** and refresh to **10s**.
2. If graphs are thin, run the traffic command again and wait 20 seconds.
3. **Screenshot 3a**: the top of the dashboard (the six tiles and *HTTP traffic* graphs).
4. Scroll down. **Screenshot 3b**: *Business operations* (orders, order value, search, stock, manual spans).
5. Scroll down. **Screenshot 3c**: *Logs (Loki)* panels.
6. Scroll down. **Screenshot 3d**: *Traces (Tempo)* tables.

Tip: press **F11** for full-screen browser, or zoom out with **Ctrl and minus** so a whole section fits in one screenshot. This dashboard shows all three signals (metrics, logs, traces) on one page, which is what "integrating all telemetry signals" means.

---

## Part 4: Tempo trace screenshots (evidence 4)

Tempo plays the role of Jaeger in this stack. Everything is in Grafana.

1. Left menu: **Explore** (compass icon).
2. Top-left data source drop-down: choose **Tempo**.
3. Choose the **TraceQL** tab and paste:
   ```
   { resource.service.name = "boutique-api" && span.boutique.outcome = "rejected" }
   ```
   Click **Run query** (top right). **Screenshot 4a**: the list of matching traces.
4. Click a **Trace ID** in the results. A *waterfall* opens on the right.
   **Screenshot 4b**: the waterfall. You should see:
   `POST /orders` (auto) -> `orders.create` (manual) -> `orders.check_stock` (manual) -> `SELECT boutique` (database, auto).
5. Click the `orders.create` bar. The details panel shows attributes such as `boutique.outcome = rejected` and `boutique.http_status = 409`.
   **Screenshot 4c**: the span attributes.
6. Make a *successful order trace*: run this query, open one result:
   ```
   { resource.service.name = "boutique-api" && name = "orders.persist" }
   ```
   **Screenshot 4d**: waterfall with `orders.create` -> `orders.check_stock` -> `orders.persist` and the `INSERT` database spans.

Optional: tab **Service Graph** shows the API and its database as a node graph.

---

## Part 5: Loki log screenshots (evidence 5)

1. **Explore**, choose the **Loki** data source.
2. Click **Code** (right of "Builder") so you can type a query.
3. **Screenshot 5a**, all application logs. Paste and click **Run query**:
   ```
   {service_name="boutique-api"}
   ```
4. **Screenshot 5b**, only warnings and errors:
   ```
   {service_name="boutique-api"} | detected_level=~"warn|error"
   ```
5. **Screenshot 5c**, click one log line to expand it. You see the labels and metadata, including `trace_id` and `span_id`, plus the **TraceID** link ("Open trace in Tempo"). This is the log side of the correlation.
6. **Screenshot 5d**, logs from one area only (for example orders):
   ```
   {service_name="boutique-api"} | scope_name="boutique.orders"
   ```

---

## Part 6: Trace-to-log correlation for one sample request (evidence 6)

This is the key demonstration. Use the **trace id printed by the traffic script** (Part 0).

### 6A. Show the request itself (optional but impressive)

Reproduce a refused order by hand and see the trace id in the response headers:

```powershell
$body = '{"customer_name":"Demo","customer_email":"demo@example.com","items":[{"product_id":1,"quantity":999}]}'
Invoke-WebRequest -Method Post -Uri http://localhost:8000/orders -ContentType "application/json" -Body $body -SkipHttpErrorCheck |
  Select-Object StatusCode, @{n="TraceId";e={$_.Headers["X-Trace-Id"]}}
```

You get `StatusCode 409` and a `TraceId`. **Screenshot 6a**. Every response from the API carries an `X-Trace-Id` header, so a customer or support engineer can quote it.

### 6B. Trace -> Logs

1. **Explore -> Tempo -> TraceQL**. Paste just the trace id (32 letters/numbers) and **Run query**.
2. Open the trace. Click the `orders.create` span. In the span details look for the **Logs for this span** button (a small document icon next to the span name).
3. Click it. Grafana opens a split view: the trace on the left and the **Loki logs of that same trace** on the right.
   **Screenshot 6b**: trace and logs side by side. The log line reads like:
   `Order rejected reason=insufficient_stock detail=Insufficient stock for product 1 (...) trace_id=<same id> span_id=<id>`

If the button is missing in your Grafana version, do it manually. It proves exactly the same thing:
in **Explore -> Loki** run

```
{service_name="boutique-api"} |= "PASTE-THE-TRACE-ID-HERE"
```

### 6C. Logs -> Trace

1. In the Loki results, click the log line to expand it.
2. Next to **TraceID** click **Open trace in Tempo**. The trace opens.
   **Screenshot 6c**: the expanded log line (with trace_id) and then the trace it opened.

### 6D. One-slide summary (optional)

Place 6a, 6b and 6c next to each other and add this caption:

> One refused order (HTTP 409) is visible as a trace in Tempo, as a warning log in Loki, and as a counted `boutique_orders_rejected_total{reason="insufficient_stock"}` increment in Prometheus, all tied together by the same trace id.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `docker compose` says the port is already in use | Something else uses 3000, 8000 or 9090. Stop it, or run `docker compose down` and start again. |
| Grafana dashboard is empty | Run the traffic command, set time range to *Last 15 minutes*, wait 20 seconds. |
| Prometheus target `boutique-telemetry` is DOWN | `docker compose logs otel-collector --tail 30` and send me the output. |
| Tempo or Loki panel says "no data" for a few seconds | Tempo and Loki need about 15 seconds after start to become *ready*. Wait and refresh. |
| `Invoke-WebRequest` complains about `-SkipHttpErrorCheck` | You are on Windows PowerShell 5. Use the traffic script's trace id instead, or install PowerShell 7. |
| Start from a clean slate | `docker compose down -v` (deletes stored telemetry and the database), then Part 0 again. |

## Stop everything when finished

```powershell
docker compose down
```
(Add `-v` only if you also want to delete the stored data.)
