"""Boutique Web API: application entry point."""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.routers import categories, orders, products, search

DESCRIPTION = """
RESTful API for a boutique shop: product catalogue, orders, inventory and search.

* **Categories / Products**: full CRUD. Products carry a SKU, price and stock level.
* **Orders**: placing an order checks and reserves stock in one transaction. Cancelling returns it.
* **Inventory**: stock adjustments, low-stock report and a movement history per product.
* **Search**: `GET /search?q=` across product name, description, SKU and category name.

Errors use `{"detail": "..."}` with 404 (not found), 409 (conflict, e.g. duplicate SKU or
insufficient stock) and 422 (validation).
"""

TAGS = [
    {"name": "Categories", "description": "Group products for browsing."},
    {"name": "Products", "description": "The catalogue."},
    {"name": "Inventory", "description": "Stock levels, adjustments and history."},
    {"name": "Orders", "description": "Place and manage customer orders."},
    {"name": "Search", "description": "Find products and categories by text."},
    {"name": "Health", "description": "Service and database status."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Boutique Web API",
    version="1.0.0",
    description=DESCRIPTION,
    openapi_tags=TAGS,
    lifespan=lifespan,
)

app.include_router(categories.router)
# The inventory router must come first: its fixed path "/products/low-stock" would otherwise
# be captured by "/products/{product_id}" in the products router.
app.include_router(products.inventory_router)
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(search.router)


@app.get("/health", tags=["Health"], summary="Liveness and database check")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
