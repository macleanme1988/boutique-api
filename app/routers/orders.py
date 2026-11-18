"""Order endpoints: GET/POST/PUT/DELETE /orders.

Placing an order reserves stock atomically; cancelling or deleting a pending order returns it.
"""
from collections import defaultdict
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import schemas
from app.database import get_db
from app.models import InventoryMovement, Order, OrderItem, OrderStatus, Product

router = APIRouter(prefix="/orders", tags=["Orders"])
DB = Annotated[Session, Depends(get_db)]

NOT_FOUND = {404: {"model": schemas.ErrorResponse, "description": "Order not found"}}

# Allowed status transitions. Delivered and cancelled orders are final.
TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.pending: {OrderStatus.confirmed, OrderStatus.cancelled},
    OrderStatus.confirmed: {OrderStatus.shipped, OrderStatus.cancelled},
    OrderStatus.shipped: {OrderStatus.delivered},
    OrderStatus.delivered: set(),
    OrderStatus.cancelled: set(),
}


def _get_or_404(db: Session, order_id: int) -> Order:
    order = db.scalar(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items).selectinload(OrderItem.product))
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Order {order_id} not found")
    return order


def _restock(db: Session, order: Order, reason: str) -> None:
    """Return every line of an order to stock and log it."""
    for item in sorted(order.items, key=lambda i: i.product_id):
        product = db.scalar(select(Product).where(Product.id == item.product_id).with_for_update())
        product.stock_quantity += item.quantity
        db.add(
            InventoryMovement(product_id=product.id, change=item.quantity, reason=reason, order_id=order.id)
        )


@router.get("", response_model=list[schemas.OrderOut], summary="List orders")
def list_orders(
    db: DB,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    customer_email: str | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    query = select(Order).options(selectinload(Order.items).selectinload(OrderItem.product)).order_by(Order.id)
    if status_filter is not None:
        query = query.where(Order.status == status_filter)
    if customer_email is not None:
        query = query.where(Order.customer_email == customer_email)
    return db.scalars(query.offset(skip).limit(limit)).all()


@router.post(
    "",
    response_model=schemas.OrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Place an order (reserves stock)",
    responses={
        409: {"model": schemas.ErrorResponse, "description": "Insufficient stock or product unavailable"},
        422: {"model": schemas.ErrorResponse, "description": "Unknown product_id"},
    },
)
def create_order(payload: schemas.OrderCreate, db: DB):
    # Merge duplicate lines, then lock products in id order (prevents deadlocks between orders).
    wanted: dict[int, int] = defaultdict(int)
    for line in payload.items:
        wanted[line.product_id] += line.quantity

    products = {
        p.id: p
        for p in db.scalars(select(Product).where(Product.id.in_(wanted)).order_by(Product.id).with_for_update())
    }
    missing = sorted(set(wanted) - set(products))
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown product id(s): {missing}")

    for product_id, quantity in wanted.items():
        product = products[product_id]
        if not product.is_active:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Product {product_id} ('{product.name}') is not available")
        if product.stock_quantity < quantity:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Insufficient stock for product {product_id} ('{product.name}'): "
                f"requested {quantity}, available {product.stock_quantity}",
            )

    order = Order(
        customer_name=payload.customer_name,
        customer_email=str(payload.customer_email),
        shipping_address=payload.shipping_address,
        status=OrderStatus.pending,
    )
    total = Decimal("0.00")
    for product_id, quantity in wanted.items():
        product = products[product_id]
        order.items.append(OrderItem(product_id=product_id, quantity=quantity, unit_price=product.price))
        total += product.price * quantity
    order.total_amount = total
    db.add(order)
    db.flush()  # assigns order.id for the stock log

    for product_id, quantity in wanted.items():
        products[product_id].stock_quantity -= quantity
        db.add(InventoryMovement(product_id=product_id, change=-quantity, reason="Order placed", order_id=order.id))
    db.commit()
    return _get_or_404(db, order.id)


@router.get("/{order_id}", response_model=schemas.OrderOut, summary="Get an order", responses=NOT_FOUND)
def get_order(order_id: int, db: DB):
    return _get_or_404(db, order_id)


@router.put(
    "/{order_id}",
    response_model=schemas.OrderOut,
    summary="Update customer details and/or move the order to a new status",
    responses={
        **NOT_FOUND,
        409: {"model": schemas.ErrorResponse, "description": "Order is final or the status change is not allowed"},
    },
)
def update_order(order_id: int, payload: schemas.OrderUpdate, db: DB):
    order = _get_or_404(db, order_id)
    if not TRANSITIONS[order.status]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Order {order_id} is {order.status.value} and cannot be changed")
    if payload.status != order.status and payload.status not in TRANSITIONS[order.status]:
        allowed = ", ".join(sorted(s.value for s in TRANSITIONS[order.status]))
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot move order from {order.status.value} to {payload.status.value}; allowed: {allowed}",
        )
    if payload.status == OrderStatus.cancelled:
        _restock(db, order, "Order cancelled")
    order.customer_name = payload.customer_name
    order.customer_email = str(payload.customer_email)
    order.shipping_address = payload.shipping_address
    order.status = payload.status
    db.commit()
    return _get_or_404(db, order_id)


@router.delete(
    "/{order_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a pending or cancelled order",
    responses={
        **NOT_FOUND,
        409: {"model": schemas.ErrorResponse, "description": "Only pending or cancelled orders can be deleted"},
    },
)
def delete_order(order_id: int, db: DB):
    order = _get_or_404(db, order_id)
    if order.status not in (OrderStatus.pending, OrderStatus.cancelled):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Order {order_id} is {order.status.value}; cancel it first or keep it for the records",
        )
    if order.status == OrderStatus.pending:
        _restock(db, order, "Pending order deleted")
    # Keep the audit trail but detach it from the order that is going away.
    db.flush()  # sessions do not autoflush: make sure the restock rows above are visible to the query
    for movement in db.scalars(select(InventoryMovement).where(InventoryMovement.order_id == order_id)):
        movement.order_id = None
    db.delete(order)
    db.commit()
