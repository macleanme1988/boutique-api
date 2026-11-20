"""Custom business metrics (the HTTP and database metrics come from auto-instrumentation).

Instruments are created at import time against the global meter. Until `setup_telemetry` installs a real
MeterProvider they are no-ops, so importing this module is always safe.
"""
from __future__ import annotations

from collections.abc import Iterable

from opentelemetry import metrics
from opentelemetry.instrumentation.utils import suppress_instrumentation
from opentelemetry.metrics import Observation
from sqlalchemy import func, select

from app.models import Product

meter = metrics.get_meter("boutique.api", "1.0.0")

orders_created = meter.create_counter(
    "boutique.orders.created", unit="{order}", description="Orders successfully placed"
)
order_value = meter.create_histogram(
    "boutique.orders.value",
    unit="{currency}",
    description="Total value of each placed order",
    explicit_bucket_boundaries_advisory=[25, 50, 100, 200, 400, 800, 1600],
)
orders_rejected = meter.create_counter(
    "boutique.orders.rejected", unit="{order}", description="Orders refused, by reason"
)
order_status_changes = meter.create_counter(
    "boutique.orders.status_changes", unit="{change}", description="Order lifecycle transitions"
)
stock_adjustments = meter.create_counter(
    "boutique.stock.adjustments", unit="{adjustment}", description="Manual stock adjustments, by direction"
)
catalogue_changes = meter.create_counter(
    "boutique.catalogue.changes", unit="{change}", description="Create/update/delete of products and categories"
)
search_queries = meter.create_counter(
    "boutique.search.queries", unit="{query}", description="Search requests"
)
search_results = meter.create_histogram(
    "boutique.search.results",
    unit="{product}",
    description="Products returned per search",
    explicit_bucket_boundaries_advisory=[0, 1, 2, 5, 10, 20, 50],
)


class _InventorySource:
    """Where the observable gauges read stock levels from; set by `setup_telemetry`."""

    session_factory = None


inventory_source = _InventorySource()


def _read_inventory(query) -> Iterable[Observation]:
    factory = inventory_source.session_factory
    if factory is None:
        return []
    # Reading the database from the metrics thread must not create orphan SQL spans.
    with suppress_instrumentation(), factory() as db:
        return [Observation(db.scalar(query) or 0)]


_ACTIVE = Product.is_active.is_(True)
_LOW_STOCK_QUERY = select(func.count()).select_from(Product).where(_ACTIVE, Product.stock_quantity <= Product.low_stock_threshold)
_UNITS_QUERY = select(func.coalesce(func.sum(Product.stock_quantity), 0)).where(_ACTIVE)
_PRODUCTS_QUERY = select(func.count()).select_from(Product).where(_ACTIVE)

low_stock_gauge = meter.create_observable_gauge(
    "boutique.inventory.low_stock_products",
    callbacks=[lambda _: _read_inventory(_LOW_STOCK_QUERY)],
    unit="{product}",
    description="Active products at or below their reorder level",
)
units_gauge = meter.create_observable_gauge(
    "boutique.inventory.units_in_stock",
    callbacks=[lambda _: _read_inventory(_UNITS_QUERY)],
    unit="{unit}",
    description="Total units in stock across active products",
)
products_gauge = meter.create_observable_gauge(
    "boutique.inventory.active_products",
    callbacks=[lambda _: _read_inventory(_PRODUCTS_QUERY)],
    unit="{product}",
    description="Number of active products in the catalogue",
)
