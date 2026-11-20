"""Tests for the OpenTelemetry instrumentation: spans, metrics, logs, correlation and privacy."""
import logging

import pytest
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import StatusCode

from app import metrics as app_metrics
from app import telemetry as tel
from app.tracing import operation


# ------------------------------------------------------------------------ helpers
def spans_named(telemetry, name):
    return [s for s in telemetry.spans.get_finished_spans() if s.name == name]


def server_span(telemetry, name):
    (span,) = [s for s in spans_named(telemetry, name) if s.kind == trace.SpanKind.SERVER]
    return span


def hex_trace(span):
    return format(span.context.trace_id, "032x")


def metric_value(telemetry, name, **attributes):
    """Sum of a metric's data points whose attributes include `attributes` (count for histograms)."""
    total = 0
    data = telemetry.reader.get_metrics_data()
    for resource_metrics in data.resource_metrics if data else []:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name != name:
                    continue
                for point in metric.data.data_points:
                    if all(point.attributes.get(k) == v for k, v in attributes.items()):
                        total += getattr(point, "count", None) if hasattr(point, "count") else point.value
    return total


# ------------------------------------------------------- auto-instrumentation + header
def test_http_server_span_and_trace_id_header(client, telemetry, make_category):
    response = client.get("/categories")
    span = server_span(telemetry, "GET /categories")
    assert span.attributes["http.method"] == "GET"
    assert span.attributes["http.route"] == "/categories"
    assert span.attributes["http.status_code"] == 200
    assert response.headers["x-trace-id"] == hex_trace(span)


def test_every_request_gets_a_distinct_trace_id(client):
    ids = {client.get("/categories").headers["x-trace-id"] for _ in range(3)}
    assert len(ids) == 3


def test_health_is_not_traced_and_has_no_trace_header(client, telemetry):
    response = client.get("/health")
    assert response.status_code == 200
    assert "x-trace-id" not in response.headers
    assert telemetry.spans.get_finished_spans() == ()


def test_no_per_asgi_message_spans(client, telemetry):
    client.get("/categories")
    assert not [s for s in telemetry.spans.get_finished_spans() if "http send" in s.name or "http receive" in s.name]


# ------------------------------------------------------------------- manual spans
@pytest.mark.parametrize(
    ("area", "expected_span"),
    [("categories", "categories.create"), ("products", "products.create"), ("search", "search.query"),
     ("orders", "orders.create")],
)
def test_each_area_emits_its_business_span_under_the_http_span(client, telemetry, make_product, area, expected_span):
    product = make_product(sku="S-1", name="Silk Scarf", stock_quantity=5)
    telemetry.spans.clear()
    if area == "categories":
        client.post("/categories", json={"name": "Hats"})
    elif area == "products":
        client.post("/products", json={"sku": "N-1", "name": "N", "price": "5.00", "category_id": product["category_id"]})
    elif area == "search":
        client.get("/search", params={"q": "silk"})
    else:
        client.post("/orders", json={"customer_name": "A", "customer_email": "a@example.com",
                                     "items": [{"product_id": product["id"], "quantity": 1}]})
    (span,) = spans_named(telemetry, expected_span)
    http = [s for s in telemetry.spans.get_finished_spans() if s.kind == trace.SpanKind.SERVER][0]
    assert span.parent.span_id == http.context.span_id
    assert span.context.trace_id == http.context.trace_id
    assert span.attributes["boutique.outcome"] == "ok"


def test_every_operation_has_a_span(client, telemetry, make_product, place_order):
    product = make_product(stock_quantity=10)
    category_id = product["category_id"]
    put_product = {"sku": "DRS-001", "name": "N", "price": "9.00", "category_id": category_id}
    order = place_order([{"product_id": product["id"], "quantity": 1}]).json()
    order_put = {"customer_name": "A", "customer_email": "a@example.com", "status": "confirmed"}
    telemetry.spans.clear()
    client.get("/categories")
    client.get(f"/categories/{category_id}")
    client.put(f"/categories/{category_id}", json={"name": "Renamed"})
    client.get("/products")
    client.get(f"/products/{product['id']}")
    client.put(f"/products/{product['id']}", json=put_product)
    client.post(f"/products/{product['id']}/stock", json={"change": 2, "reason": "r"})
    client.get(f"/products/{product['id']}/stock-movements")
    client.get("/products/low-stock")
    client.get("/orders")
    client.get(f"/orders/{order['id']}")
    client.put(f"/orders/{order['id']}", json={**order_put, "status": "cancelled"})
    client.delete(f"/orders/{order['id']}")
    names = {s.name for s in telemetry.spans.get_finished_spans()}
    assert {
        "categories.list", "categories.get", "categories.update", "products.list", "products.get",
        "products.update", "inventory.adjust_stock", "inventory.stock_movements", "inventory.low_stock_report",
        "orders.list", "orders.get", "orders.update", "orders.restock", "orders.delete",
    } <= names
    client.delete(f"/products/{product['id']}")
    client.delete(f"/categories/{category_id}")
    assert {"products.delete", "categories.delete"} <= {s.name for s in telemetry.spans.get_finished_spans()}


def test_order_creation_has_child_spans_and_useful_attributes(client, telemetry, make_product, place_order):
    product = make_product(price="40.00", stock_quantity=10)
    telemetry.spans.clear()
    order = place_order([{"product_id": product["id"], "quantity": 2}]).json()
    (create,) = spans_named(telemetry, "orders.create")
    (check,) = spans_named(telemetry, "orders.check_stock")
    (persist,) = spans_named(telemetry, "orders.persist")
    assert check.parent.span_id == create.context.span_id == persist.parent.span_id
    assert create.attributes["order.id"] == order["id"]
    assert create.attributes["order.total"] == 80.0
    assert create.attributes["order.status"] == "pending"
    assert persist.attributes["order.id"] == order["id"]


def test_rejected_order_marks_span_rejected_but_not_error(client, telemetry, make_product, place_order):
    product = make_product(stock_quantity=1)
    telemetry.spans.clear()
    response = place_order([{"product_id": product["id"], "quantity": 5}])
    assert response.status_code == 409
    (create,) = spans_named(telemetry, "orders.create")
    assert create.attributes["boutique.outcome"] == "rejected"
    assert create.attributes["boutique.http_status"] == 409
    assert create.status.status_code == StatusCode.UNSET
    (event,) = [e for e in create.events if e.name == "request rejected"]
    assert "Insufficient stock" in event.attributes["detail"]
    # The trace id handed back to the caller is the id of the trace that holds this evidence.
    assert response.headers["x-trace-id"] == hex_trace(create)


def test_operation_helper_error_paths(telemetry):
    with pytest.raises(ValueError), operation("test.boom"):
        raise ValueError("kaboom")
    with pytest.raises(HTTPException), operation("test.server_error"):
        raise HTTPException(500, "database down")
    with pytest.raises(HTTPException), operation("test.client_error"):
        raise HTTPException(404, "nope")
    with operation("test.none_attributes_are_dropped", {"keep": 1, "drop": None}):
        pass

    boom, server_error, client_error, dropped = (
        spans_named(telemetry, n)[0]
        for n in ("test.boom", "test.server_error", "test.client_error", "test.none_attributes_are_dropped")
    )
    assert boom.status.status_code == StatusCode.ERROR and boom.attributes["boutique.outcome"] == "error"
    assert any(e.name == "exception" for e in boom.events)
    assert server_error.status.status_code == StatusCode.ERROR
    assert client_error.status.status_code == StatusCode.UNSET
    assert "drop" not in dropped.attributes and dropped.attributes["keep"] == 1


# ---------------------------------------------------------------- database spans
def test_sql_statements_become_child_spans(engine, session_factory, client, telemetry, make_category):
    tel.instrument_engines(engine)
    try:
        telemetry.spans.clear()
        client.get("/categories")
        selects = [s for s in telemetry.spans.get_finished_spans() if s.kind == trace.SpanKind.CLIENT]
        assert selects, "expected at least one SQL span"
        parent = spans_named(telemetry, "categories.list")[0]
        assert any(s.parent.span_id == parent.context.span_id and s.attributes["db.system"] == "sqlite" for s in selects)
    finally:
        SQLAlchemyInstrumentor().uninstrument()


# ------------------------------------------------------------------------ metrics
def test_business_metrics(client, telemetry, make_product, place_order):
    product = make_product(price="25.00", stock_quantity=10)
    before = {
        "created": metric_value(telemetry, "boutique.orders.created"),
        "value_n": metric_value(telemetry, "boutique.orders.value"),
        "rejected": metric_value(telemetry, "boutique.orders.rejected", reason="insufficient_stock"),
        "search": metric_value(telemetry, "boutique.search.queries", has_results=False),
        "stock_in": metric_value(telemetry, "boutique.stock.adjustments", direction="in"),
        "stock_out": metric_value(telemetry, "boutique.stock.adjustments", direction="out"),
        "created_cat": metric_value(telemetry, "boutique.catalogue.changes", resource="category", action="create"),
        "cancelled": metric_value(telemetry, "boutique.orders.status_changes", to_status="cancelled"),
    }
    order = place_order([{"product_id": product["id"], "quantity": 2}]).json()
    place_order([{"product_id": product["id"], "quantity": 999}])
    client.get("/search", params={"q": "no-such-thing"})
    client.post(f"/products/{product['id']}/stock", json={"change": 5, "reason": "r"})
    client.post(f"/products/{product['id']}/stock", json={"change": -1, "reason": "r"})
    client.post("/categories", json={"name": "Brand new"})
    client.put(f"/orders/{order['id']}", json={"customer_name": "A", "customer_email": "a@example.com", "status": "cancelled"})

    assert metric_value(telemetry, "boutique.orders.created") - before["created"] == 1
    assert metric_value(telemetry, "boutique.orders.value") - before["value_n"] == 1
    assert metric_value(telemetry, "boutique.orders.rejected", reason="insufficient_stock") - before["rejected"] == 1
    assert metric_value(telemetry, "boutique.search.queries", has_results=False) - before["search"] == 1
    assert metric_value(telemetry, "boutique.stock.adjustments", direction="in") - before["stock_in"] == 1
    assert metric_value(telemetry, "boutique.stock.adjustments", direction="out") - before["stock_out"] == 1
    assert metric_value(telemetry, "boutique.catalogue.changes", resource="category", action="create") - before["created_cat"] == 1
    assert metric_value(telemetry, "boutique.orders.status_changes", to_status="cancelled") - before["cancelled"] == 1


def test_http_server_duration_metric_is_recorded(client, telemetry):
    before = metric_value(telemetry, "http.server.duration")
    client.get("/categories")
    assert metric_value(telemetry, "http.server.duration") - before >= 1


def test_inventory_gauges_read_the_database(client, telemetry, session_factory, monkeypatch, make_product):
    monkeypatch.setattr(app_metrics.inventory_source, "session_factory", session_factory)
    make_product(sku="OK", stock_quantity=50)
    make_product(sku="LOW", stock_quantity=2)
    make_product(sku="OUT", stock_quantity=0)
    assert metric_value(telemetry, "boutique.inventory.low_stock_products") == 2
    assert metric_value(telemetry, "boutique.inventory.units_in_stock") == 52
    assert metric_value(telemetry, "boutique.inventory.active_products") == 3


def test_inventory_gauges_are_silent_without_a_database(telemetry, monkeypatch):
    monkeypatch.setattr(app_metrics.inventory_source, "session_factory", None)
    assert metric_value(telemetry, "boutique.inventory.low_stock_products") == 0


# ----------------------------------------------------------------------------- logs
def test_log_lines_carry_the_trace_id_for_correlation(client, telemetry, make_product, place_order):
    product = make_product(stock_quantity=3)
    telemetry.logs.clear()
    response = place_order([{"product_id": product["id"], "quantity": 3}])
    trace_id = response.headers["x-trace-id"]
    records = [r.log_record for r in telemetry.logs.get_finished_logs()]
    placed = [r for r in records if "Order placed" in r.body]
    assert placed, "expected an 'Order placed' log"
    for record in records:
        assert f"trace_id={trace_id}" in record.body  # text key that Loki/Grafana join on
        assert format(record.trace_id, "032x") == trace_id  # native OTLP trace field agrees
    assert {r.severity_text for r in records} == {"INFO", "WARN"}  # info for the order, warn for low stock
    assert any("Low stock after order" in r.body for r in records)


def test_rejection_is_logged_as_a_warning_with_its_trace_id(client, telemetry, make_product, place_order):
    product = make_product(stock_quantity=1)
    telemetry.logs.clear()
    response = place_order([{"product_id": product["id"], "quantity": 9}])
    (record,) = [r.log_record for r in telemetry.logs.get_finished_logs() if "rejected" in r.log_record.body]
    assert record.severity_text == "WARN"
    assert "reason=insufficient_stock" in record.body
    assert f"trace_id={response.headers['x-trace-id']}" in record.body


def test_trace_context_filter_outside_a_span():
    record = logging.LogRecord("boutique.x", logging.INFO, __file__, 1, "msg", None, None)
    assert tel.TraceContextFilter().filter(record) is True
    assert (record.trace_id, record.span_id) == ("-", "-")


def test_configure_logging_is_idempotent(monkeypatch):
    logger = logging.getLogger("boutique")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    tel.configure_logging()
    count = len(logger.handlers)
    tel.configure_logging()
    assert len(logger.handlers) == count
    assert logger.level == logging.DEBUG
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    tel.configure_logging()


def test_configure_logging_adds_one_console_handler_when_missing():
    logger = logging.getLogger("boutique")
    saved = list(logger.handlers)
    try:
        logger.handlers = [h for h in saved if not getattr(h, "_boutique_console", False)]
        tel.configure_logging()
        assert sum(getattr(h, "_boutique_console", False) for h in logger.handlers) == 1
    finally:
        logger.handlers = saved


# ------------------------------------------------------------------------- privacy
def test_no_customer_data_in_spans_or_logs(client, telemetry, make_product, place_order):
    product = make_product(stock_quantity=10)
    secrets = ("Ama Mensah", "ama@example.com", "12 Market Road")
    order = place_order(
        [{"product_id": product["id"], "quantity": 1}], shipping_address="12 Market Road"
    ).json()
    client.get("/orders", params={"customer_email": "ama@example.com"})
    client.put(
        f"/orders/{order['id']}",
        json={"customer_name": "Ama Mensah", "customer_email": "ama@example.com",
              "shipping_address": "12 Market Road", "status": "confirmed"},
    )
    exported = []
    for span in telemetry.spans.get_finished_spans():
        exported += [span.name, *map(str, span.attributes.values())]
        for event in span.events:
            exported += map(str, event.attributes.values())
    for record in (r.log_record for r in telemetry.logs.get_finished_logs()):
        exported += [str(record.body), *map(str, (record.attributes or {}).values())]
    blob = "\n".join(exported)
    for secret in secrets:
        assert secret not in blob, f"{secret!r} leaked into telemetry"
    assert "customer_email=REDACTED" in blob  # the filter URL is still visible, just redacted


def test_redact_span_leaves_clean_spans_untouched(client, telemetry):
    client.get("/categories")
    span = server_span(telemetry, "GET /categories")
    assert tel.redact_span(span) is span


# ----------------------------------------------------------------------- plumbing
def test_trace_header_middleware_ignores_non_http_scopes():
    import asyncio

    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    asyncio.run(tel.TraceIdHeaderMiddleware(inner)({"type": "lifespan"}, None, None))
    assert seen == ["lifespan"]


def test_clean_shutdown_flushes_telemetry(engine, monkeypatch):
    from fastapi.testclient import TestClient

    from app import main

    class Recorder:
        flushed = False

        def shutdown(self):
            self.flushed = True

    recorder = Recorder()
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "telemetry", recorder)
    with TestClient(main.app):
        assert recorder.flushed is False  # still running
    assert recorder.flushed is True  # lifespan shutdown flushed the exporters


def test_telemetry_handles_shutdown_stops_all_providers():
    handles = tel.TelemetryHandles(TracerProvider(), MeterProvider(), LoggerProvider())
    handles.shutdown()  # must not raise


def test_exporter_wrapper_delegates_flush_and_shutdown():
    calls = []

    class Inner:
        def export(self, spans):
            calls.append(("export", len(spans)))
            return "ok"

        def shutdown(self):
            calls.append("shutdown")

        def force_flush(self, timeout_millis=30000):
            calls.append("flush")
            return True

    wrapper = tel.RedactingSpanExporter(Inner())
    assert wrapper.export([]) == "ok"
    assert wrapper.force_flush() is True
    wrapper.shutdown()
    assert calls == [("export", 0), "flush", "shutdown"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("TRUE", True), ("1", True), ("yes", True), ("on", True), (" true ", True),
     ("false", False), ("0", False), ("", False), ("no", False)],
)
def test_telemetry_enabled_flag(monkeypatch, value, expected):
    monkeypatch.setenv("OTEL_ENABLED", value)
    assert tel.telemetry_enabled() is expected


def test_telemetry_is_off_by_default(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    assert tel.telemetry_enabled() is False
    assert tel.init_observability(FastAPI(), object(), None) is None


def test_init_observability_sets_everything_up_when_enabled(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "true")
    calls = []
    sentinel = object()
    monkeypatch.setattr(tel, "setup_telemetry", lambda app, session_factory: calls.append(("setup", session_factory)) or sentinel)
    monkeypatch.setattr(tel, "instrument_engines", lambda *engines: calls.append(("engines", engines)))
    engine, factory = object(), object()
    assert tel.init_observability(FastAPI(), engine, factory) is sentinel
    assert calls == [("setup", factory), ("engines", (engine,))]
