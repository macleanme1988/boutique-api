from fastapi.testclient import TestClient

from app import database, main, seed
from app.main import app


def test_health_reports_database_reachable(client):
    assert client.get("/health").json() == {"status": "ok", "database": "reachable"}


def test_get_db_yields_a_session_and_closes_it(monkeypatch):
    closed = []

    class FakeSession:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(database, "SessionLocal", FakeSession)
    generator = database.get_db()
    session = next(generator)
    assert isinstance(session, FakeSession) and closed == []
    generator.close()  # triggers the finally block
    assert closed == [True]


def test_openapi_documents_every_required_endpoint(client):
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "Boutique Web API"
    paths = spec["paths"]
    expected = {
        "/products": {"get", "post"},
        "/products/{product_id}": {"get", "put", "delete"},
        "/categories": {"get", "post"},
        "/categories/{category_id}": {"get", "put", "delete"},
        "/orders": {"get", "post"},
        "/orders/{order_id}": {"get", "put", "delete"},
        "/search": {"get"},
        "/products/{product_id}/stock": {"post"},
        "/products/low-stock": {"get"},
    }
    for path, methods in expected.items():
        assert methods <= set(paths[path]), f"{path} is missing {methods - set(paths[path])}"


def test_swagger_ui_and_redoc_are_served(client):
    assert "swagger-ui" in client.get("/docs").text.lower()
    assert client.get("/redoc").status_code == 200


def test_lifespan_creates_tables(engine, monkeypatch):
    monkeypatch.setattr(main, "engine", engine)
    with TestClient(app) as test_client:  # runs startup
        assert test_client.get("/openapi.json").status_code == 200


def test_seed_loads_demo_data_once(engine, session_factory, monkeypatch, capsys):
    monkeypatch.setattr(seed, "engine", engine)
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    seed.seed()
    assert "Seeded 3 categories and 8 products" in capsys.readouterr().out
    seed.seed()
    assert "already has data" in capsys.readouterr().out
