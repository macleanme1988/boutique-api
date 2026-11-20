"""Search endpoint: GET /search?q="""
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.metrics import search_queries, search_results
from app.models import Category, Product
from app.tracing import operation
from app.tracing import search_log as log

router = APIRouter(prefix="/search", tags=["Search"])
DB = Annotated[Session, Depends(get_db)]


def _like_pattern(text: str) -> str:
    """Escape LIKE wildcards so a user typing '%' or '_' searches for the literal character."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get(
    "",
    response_model=schemas.SearchResults,
    summary="Search active products and categories",
    description=(
        "Case-insensitive match on product name, description and SKU, and on category name. "
        "Products whose *name* matches are listed first. Optional filters narrow the product results."
    ),
)
def search(
    db: DB,
    q: Annotated[str, Query(min_length=1, max_length=100, description="Search text", examples=["linen"])],
    category_id: int | None = None,
    min_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    in_stock: Annotated[bool | None, Query(description="true = only items with stock")] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    text = q.strip()
    attributes = {
        "search.query": text,
        "search.category_id": category_id,
        "search.min_price": float(min_price) if min_price is not None else None,
        "search.max_price": float(max_price) if max_price is not None else None,
        "search.in_stock": in_stock,
    }
    with operation("search.query", attributes) as span:
        pattern = _like_pattern(text)
        match = or_(
            Product.name.ilike(pattern, escape="\\"),
            Product.description.ilike(pattern, escape="\\"),
            Product.sku.ilike(pattern, escape="\\"),
        )
        conditions = [Product.is_active.is_(True), match]
        if category_id is not None:
            conditions.append(Product.category_id == category_id)
        if min_price is not None:
            conditions.append(Product.price >= min_price)
        if max_price is not None:
            conditions.append(Product.price <= max_price)
        if in_stock is True:
            conditions.append(Product.stock_quantity > 0)
        elif in_stock is False:
            conditions.append(Product.stock_quantity == 0)

        total = db.scalar(select(func.count()).select_from(Product).where(*conditions))
        name_first = case((Product.name.ilike(pattern, escape="\\"), 0), else_=1)
        products = db.scalars(
            select(Product).where(*conditions).order_by(name_first, Product.name).offset(skip).limit(limit)
        ).all()
        categories = db.scalars(
            select(Category).where(Category.name.ilike(pattern, escape="\\")).order_by(Category.name).limit(limit)
        ).all()

        span.set_attributes(
            {"search.total_matches": total, "search.returned": len(products), "search.categories_matched": len(categories)}
        )
        search_queries.add(1, {"has_results": total > 0})
        search_results.record(total)
        log.info("Search q='%s' matched %d product(s) and %d category(ies)", text, total, len(categories))
        return schemas.SearchResults(query=text, total_products=total, products=products, categories=categories)
