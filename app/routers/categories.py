"""Category endpoints: GET/POST/PUT/DELETE /categories."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.models import Category, Product

router = APIRouter(prefix="/categories", tags=["Categories"])
DB = Annotated[Session, Depends(get_db)]

NOT_FOUND = {404: {"model": schemas.ErrorResponse, "description": "Category not found"}}
CONFLICT = {409: {"model": schemas.ErrorResponse, "description": "Name already in use"}}


def _get_or_404(db: Session, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Category {category_id} not found")
    return category


def _ensure_name_free(db: Session, name: str, exclude_id: int | None = None) -> None:
    query = select(Category.id).where(func.lower(Category.name) == name.lower())
    if exclude_id is not None:
        query = query.where(Category.id != exclude_id)
    if db.scalar(query) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Category '{name}' already exists")


@router.get("", response_model=list[schemas.CategoryOut], summary="List categories")
def list_categories(
    db: DB,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    return db.scalars(select(Category).order_by(Category.name).offset(skip).limit(limit)).all()


@router.post(
    "",
    response_model=schemas.CategoryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a category",
    responses=CONFLICT,
)
def create_category(payload: schemas.CategoryCreate, db: DB):
    _ensure_name_free(db, payload.name)
    category = Category(**payload.model_dump())
    db.add(category)
    db.commit()
    return category


@router.get(
    "/{category_id}", response_model=schemas.CategoryOut, summary="Get a category", responses=NOT_FOUND
)
def get_category(category_id: int, db: DB):
    return _get_or_404(db, category_id)


@router.put(
    "/{category_id}",
    response_model=schemas.CategoryOut,
    summary="Replace a category",
    responses={**NOT_FOUND, **CONFLICT},
)
def update_category(category_id: int, payload: schemas.CategoryUpdate, db: DB):
    category = _get_or_404(db, category_id)
    _ensure_name_free(db, payload.name, exclude_id=category_id)
    category.name = payload.name
    category.description = payload.description
    db.commit()
    return category


@router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a category",
    responses={
        **NOT_FOUND,
        409: {"model": schemas.ErrorResponse, "description": "Category still has products"},
    },
)
def delete_category(category_id: int, db: DB):
    category = _get_or_404(db, category_id)
    in_use = db.scalar(select(func.count()).select_from(Product).where(Product.category_id == category_id))
    if in_use:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Category {category_id} still has {in_use} product(s); move or delete them first",
        )
    try:
        db.delete(category)
        db.commit()
    except IntegrityError:  # pragma: no cover - a product was added concurrently
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Category is in use") from None
