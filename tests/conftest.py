"""Test fixtures: each test gets a fresh in-memory SQLite database and a TestClient."""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def engine():
    """In-memory SQLite by default. Set TEST_DATABASE_URL to run the same suite on PostgreSQL."""
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        engine = create_engine(url)
        Base.metadata.drop_all(engine)
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield engine
    if url:
        Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---- small helpers so tests read like the API being exercised -------------------
@pytest.fixture()
def make_category(client):
    def _make(name="Dresses", description="Summer dresses"):
        response = client.post("/categories", json={"name": name, "description": description})
        assert response.status_code == 201, response.text
        return response.json()

    return _make


@pytest.fixture()
def make_product(client, make_category):
    def _make(sku="DRS-001", name="Linen Wrap Dress", price="89.90", stock_quantity=10, category_id=None, **extra):
        if category_id is None:
            category_id = make_category(name=f"Cat for {sku}")["id"]
        payload = {
            "sku": sku,
            "name": name,
            "price": price,
            "stock_quantity": stock_quantity,
            "category_id": category_id,
            **extra,
        }
        response = client.post("/products", json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    return _make


@pytest.fixture()
def place_order(client):
    def _place(items, **extra):
        payload = {"customer_name": "Ama Mensah", "customer_email": "ama@example.com", "items": items, **extra}
        return client.post("/orders", json=payload)

    return _place
