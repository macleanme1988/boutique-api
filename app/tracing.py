"""Helpers for the manual (business-level) spans and the application loggers.

Auto-instrumentation gives us the HTTP server span and the SQL spans. The spans created here sit
between them and describe what the *business* is doing: "orders.create", "search.query" and so on.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException
from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

tracer = trace.get_tracer("boutique.api")

products_log = logging.getLogger("boutique.products")
categories_log = logging.getLogger("boutique.categories")
inventory_log = logging.getLogger("boutique.inventory")
orders_log = logging.getLogger("boutique.orders")
search_log = logging.getLogger("boutique.search")


@contextmanager
def operation(name: str, attributes: dict | None = None) -> Iterator[Span]:
    """Run a block inside a span called `name`.

    * Every span gets `boutique.outcome` = "ok" | "rejected" | "error", so Tempo/Grafana can filter on it.
    * An HTTPException is a *business* rejection (404/409/422): it is recorded as an event and the span stays
      un-errored unless the status is 5xx, mirroring how the HTTP server span treats 4xx.
    * Any other exception is a real failure: it is recorded on the span and the span is marked ERROR.
    """
    clean = {key: value for key, value in (attributes or {}).items() if value is not None}
    with tracer.start_as_current_span(
        name, attributes=clean, record_exception=False, set_status_on_exception=False
    ) as span:
        try:
            yield span
        except HTTPException as exc:
            span.set_attribute("boutique.outcome", "rejected")
            span.set_attribute("boutique.http_status", exc.status_code)
            span.add_event("request rejected", {"status": exc.status_code, "detail": str(exc.detail)})
            if exc.status_code >= 500:
                span.set_status(Status(StatusCode.ERROR, str(exc.detail)))
            raise
        except Exception as exc:
            span.set_attribute("boutique.outcome", "error")
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        else:
            span.set_attribute("boutique.outcome", "ok")
