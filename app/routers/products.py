"""Product endpoints: GET/POST/PUT/DELETE /products, plus inventory management."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.metrics import catalogue_changes, stock_adjustments
from app.models import Category, InventoryMovement, OrderItem, Product
from app.tracing import inventory_log, operation
from app.tracing import products_log as log

router = APIRouter(prefix="/products", tags=["Products"])
inventory_router = APIRouter(prefix="/products", tags=["Inventory"])
DB = Annotated[Session, Depends(get_db)]

NOT_FOUND = {404: {"model": schemas.ErrorResponse, "description": "Product not found"}}
CONFLICT = {409: {"model": schemas.ErrorResponse, "description": "Conflict with existing data"}}
BAD_CATEGORY = {422: {"model": schemas.ErrorResponse, "description": "Unknown category_id"}}


def _get_or_404(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        log.warning("Product %s not found", product_id)
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Product {product_id} not found")
    return product


def _check_category(db: Session, category_id: int) -> None:
    if db.get(Category, category_id) is None:
        log.warning("Unknown category_id=%s", category_id)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Category {category_id} does not exist")


def _ensure_sku_free(db: Session, sku: str, exclude_id: int | None = None) -> None:
    query = select(Product.id).where(Product.sku == sku)
    if exclude_id is not None:
        query = query.where(Product.id != exclude_id)
    if db.scalar(query) is not None:
        log.warning("SKU '%s' is already in use", sku)
        raise HTTPException(status.HTTP_409_CONFLICT, f"SKU '{sku}' is already in use")


# ----------------------------------------------------------------- catalogue CRUD
@router.get("", response_model=list[schemas.ProductOut], summary="List products")
def list_products(
    db: DB,
    category_id: int | None = None,
    is_active: bool | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    attributes = {"category.id": category_id, "product.is_active": is_active, "page.skip": skip, "page.limit": limit}
    with operation("products.list", attributes) as span:
        query = select(Product).order_by(Product.id)
        if category_id is not None:
            query = query.where(Product.category_id == category_id)
        if is_active is not None:
            query = query.where(Product.is_active == is_active)
        products = db.scalars(query.offset(skip).limit(limit)).all()
        span.set_attribute("products.count", len(products))
        log.info("Listed %d products", len(products))
        return products


@router.post(
    "",
    response_model=schemas.ProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product",
    responses={**CONFLICT, **BAD_CATEGORY},
)
def create_product(payload: schemas.ProductCreate, db: DB):
    with operation("products.create", {"product.sku": payload.sku, "category.id": payload.category_id}) as span:
        _check_category(db, payload.category_id)
        _ensure_sku_free(db, payload.sku)
        product = Product(**payload.model_dump())
        db.add(product)
        db.flush()
        if product.stock_quantity:
            db.add(InventoryMovement(product_id=product.id, change=product.stock_quantity, reason="Opening stock"))
        db.commit()
        span.set_attribute("product.id", product.id)
        catalogue_changes.add(1, {"resource": "product", "action": "create"})
        log.info("Product created id=%s sku=%s stock=%s", product.id, product.sku, product.stock_quantity)
        return product


# NOTE: main.py includes inventory_router before router so "low-stock" is not parsed as an id.
@inventory_router.get(
    "/low-stock", response_model=list[schemas.ProductOut], summary="Products at or below their reorder level"
)
def low_stock_products(db: DB):
    with operation("inventory.low_stock_report") as span:
        query = (
            select(Product)
            .where(Product.is_active.is_(True), Product.stock_quantity <= Product.low_stock_threshold)
            .order_by(Product.stock_quantity, Product.id)
        )
        products = db.scalars(query).all()
        span.set_attribute("products.count", len(products))
        inventory_log.info("Low-stock report: %d product(s) need reordering", len(products))
        return products


@router.get("/{product_id}", response_model=schemas.ProductOut, summary="Get a product", responses=NOT_FOUND)
def get_product(product_id: int, db: DB):
    with operation("products.get", {"product.id": product_id}):
        return _get_or_404(db, product_id)


@router.put(
    "/{product_id}",
    response_model=schemas.ProductOut,
    summary="Replace a product's catalogue fields",
    responses={**NOT_FOUND, **CONFLICT, **BAD_CATEGORY},
)
def update_product(product_id: int, payload: schemas.ProductUpdate, db: DB):
    with operation("products.update", {"product.id": product_id, "product.sku": payload.sku}):
        product = _get_or_404(db, product_id)
        _check_category(db, payload.category_id)
        _ensure_sku_free(db, payload.sku, exclude_id=product_id)
        for field, value in payload.model_dump().items():
            setattr(product, field, value)
        db.commit()
        catalogue_changes.add(1, {"resource": "product", "action": "update"})
        log.info("Product updated id=%s sku=%s active=%s", product_id, product.sku, product.is_active)
        return product


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a product",
    responses={
        **NOT_FOUND,
        409: {
            "model": schemas.ErrorResponse,
            "description": "Product appears in orders; set is_active=false instead",
        },
    },
)
def delete_product(product_id: int, db: DB):
    with operation("products.delete", {"product.id": product_id}):
        product = _get_or_404(db, product_id)
        ordered = db.scalar(select(func.count()).select_from(OrderItem).where(OrderItem.product_id == product_id))
        if ordered:
            log.warning("Cannot delete product %s: appears in %d order line(s)", product_id, ordered)
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Product {product_id} appears in {ordered} order line(s); deactivate it (is_active=false) instead",
            )
        try:
            for movement in db.scalars(select(InventoryMovement).where(InventoryMovement.product_id == product_id)):
                db.delete(movement)
            db.delete(product)
            db.commit()
        except IntegrityError:  # pragma: no cover - an order was placed concurrently
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Product is in use") from None
        catalogue_changes.add(1, {"resource": "product", "action": "delete"})
        log.info("Product deleted id=%s", product_id)


# ----------------------------------------------------------------------- inventory
@inventory_router.post(
    "/{product_id}/stock",
    response_model=schemas.ProductOut,
    summary="Adjust stock (restock, shrinkage, correction)",
    responses={
        **NOT_FOUND,
        409: {"model": schemas.ErrorResponse, "description": "Adjustment would make stock negative"},
    },
)
def adjust_stock(product_id: int, payload: schemas.StockAdjustment, db: DB):
    with operation("inventory.adjust_stock", {"product.id": product_id, "stock.change": payload.change}) as span:
        if payload.change == 0:
            inventory_log.warning("Rejected zero stock adjustment for product %s", product_id)
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "change must not be zero")
        product = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
        if product is None:
            inventory_log.warning("Stock adjustment for unknown product %s", product_id)
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Product {product_id} not found")
        new_level = product.stock_quantity + payload.change
        if new_level < 0:
            inventory_log.warning(
                "Rejected stock removal for product %s: remove=%d in_stock=%d", product_id, -payload.change, product.stock_quantity
            )
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Cannot remove {-payload.change}: only {product.stock_quantity} in stock",
            )
        product.stock_quantity = new_level
        db.add(InventoryMovement(product_id=product_id, change=payload.change, reason=payload.reason))
        db.commit()
        span.set_attribute("stock.new_level", new_level)
        stock_adjustments.add(1, {"direction": "in" if payload.change > 0 else "out"})
        inventory_log.info(
            "Stock adjusted product=%s change=%+d new_level=%d reason='%s'", product_id, payload.change, new_level, payload.reason
        )
        return product


@inventory_router.get(
    "/{product_id}/stock-movements",
    response_model=list[schemas.InventoryMovementOut],
    summary="Stock history for a product (newest first)",
    responses=NOT_FOUND,
)
def stock_movements(product_id: int, db: DB):
    with operation("inventory.stock_movements", {"product.id": product_id}) as span:
        _get_or_404(db, product_id)
        query = (
            select(InventoryMovement)
            .where(InventoryMovement.product_id == product_id)
            .order_by(InventoryMovement.id.desc())
        )
        movements = db.scalars(query).all()
        span.set_attribute("movements.count", len(movements))
        return movements
