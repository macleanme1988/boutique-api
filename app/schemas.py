"""Pydantic schemas: request validation and response shapes (shown in Swagger UI)."""
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field

from app.models import OrderStatus

Money = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2, examples=["49.90"])]


class ErrorResponse(BaseModel):
    detail: str = Field(examples=["Human-readable explanation of the problem"])


# --------------------------------------------------------------------- categories
class CategoryBase(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["Dresses"])
    description: str | None = Field(default=None, examples=["Summer and evening dresses"])


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(CategoryBase):
    pass


class CategoryOut(CategoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


# ---------------------------------------------------------------------- products
class ProductBase(BaseModel):
    sku: str = Field(min_length=1, max_length=50, examples=["DRS-001"])
    name: str = Field(min_length=1, max_length=200, examples=["Linen Wrap Dress"])
    description: str | None = Field(default=None, examples=["Breathable linen, knee length"])
    price: Money
    category_id: int = Field(examples=[1])
    low_stock_threshold: int = Field(default=5, ge=0)
    is_active: bool = True


class ProductCreate(ProductBase):
    stock_quantity: int = Field(default=0, ge=0, description="Opening stock level", examples=[25])


class ProductUpdate(ProductBase):
    """Full replacement of catalogue fields. Stock is changed via `POST /products/{id}/stock`."""


class ProductOut(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stock_quantity: int
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_low_stock(self) -> bool:
        return self.stock_quantity <= self.low_stock_threshold


class StockAdjustment(BaseModel):
    change: int = Field(description="Positive to add stock, negative to remove it", examples=[10])
    reason: str = Field(min_length=1, max_length=200, examples=["Supplier delivery"])


class InventoryMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    change: int
    reason: str
    order_id: int | None
    created_at: datetime


# ------------------------------------------------------------------------ orders
class OrderItemIn(BaseModel):
    product_id: int = Field(examples=[1])
    quantity: int = Field(gt=0, le=1000, examples=[2])


class OrderCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=200, examples=["Ama Mensah"])
    customer_email: EmailStr = Field(examples=["ama@example.com"])
    shipping_address: str | None = Field(default=None, examples=["12 Market Road, Bolgatanga"])
    items: list[OrderItemIn] = Field(min_length=1)


class OrderUpdate(BaseModel):
    """Items cannot be edited after an order is placed; cancel and re-order instead."""

    customer_name: str = Field(min_length=1, max_length=200)
    customer_email: EmailStr
    shipping_address: str | None = None
    status: OrderStatus


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    product_name: str
    quantity: int
    unit_price: Decimal = Field(examples=["89.90"], description="Price per unit when the order was placed")
    line_total: Decimal = Field(examples=["179.80"], description="unit_price x quantity")


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_name: str
    customer_email: EmailStr
    shipping_address: str | None
    status: OrderStatus
    total_amount: Decimal = Field(examples=["179.80"], description="Sum of all line totals")
    items: list[OrderItemOut]
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------------ search
class SearchResults(BaseModel):
    query: str
    total_products: int = Field(description="Matches before limit/offset are applied")
    products: list[ProductOut]
    categories: list[CategoryOut]
