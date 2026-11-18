def test_create_and_get_category(client):
    created = client.post("/categories", json={"name": "Dresses", "description": "Summer"})
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Dresses" and body["id"] > 0

    fetched = client.get(f"/categories/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["description"] == "Summer"


def test_list_categories_sorted_and_paginated(client, make_category):
    for name in ("Tops", "Accessories", "Dresses"):
        make_category(name=name)
    names = [c["name"] for c in client.get("/categories").json()]
    assert names == ["Accessories", "Dresses", "Tops"]
    page = client.get("/categories", params={"skip": 1, "limit": 1}).json()
    assert [c["name"] for c in page] == ["Dresses"]


def test_duplicate_name_is_conflict_case_insensitive(client, make_category):
    make_category(name="Dresses")
    response = client.post("/categories", json={"name": "dresses"})
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_get_missing_category_404(client):
    response = client.get("/categories/999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Category 999 not found"


def test_update_category(client, make_category):
    category = make_category(name="Dresses")
    response = client.put(f"/categories/{category['id']}", json={"name": "Gowns", "description": None})
    assert response.status_code == 200
    assert response.json()["name"] == "Gowns"
    assert response.json()["description"] is None


def test_update_category_keeping_own_name_is_allowed(client, make_category):
    category = make_category(name="Dresses")
    response = client.put(f"/categories/{category['id']}", json={"name": "Dresses", "description": "New text"})
    assert response.status_code == 200


def test_update_category_to_taken_name_conflicts(client, make_category):
    make_category(name="Dresses")
    other = make_category(name="Tops")
    response = client.put(f"/categories/{other['id']}", json={"name": "Dresses"})
    assert response.status_code == 409


def test_update_missing_category_404(client):
    assert client.put("/categories/999", json={"name": "X"}).status_code == 404


def test_delete_empty_category(client, make_category):
    category = make_category()
    assert client.delete(f"/categories/{category['id']}").status_code == 204
    assert client.get(f"/categories/{category['id']}").status_code == 404


def test_delete_category_with_products_is_conflict(client, make_category, make_product):
    category = make_category(name="Dresses")
    make_product(category_id=category["id"])
    response = client.delete(f"/categories/{category['id']}")
    assert response.status_code == 409
    assert "still has 1 product" in response.json()["detail"]


def test_delete_missing_category_404(client):
    assert client.delete("/categories/999").status_code == 404


def test_category_validation(client):
    assert client.post("/categories", json={"name": ""}).status_code == 422
    assert client.post("/categories", json={}).status_code == 422
    assert client.get("/categories", params={"limit": 0}).status_code == 422
