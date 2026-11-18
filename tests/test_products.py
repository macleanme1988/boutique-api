def test_create_product_sets_fields_and_logs_opening_stock(client, make_category):
    category = make_category()
    response = client.post(
        "/products",
        json={"sku": "DRS-001", "name": "Linen Dress", "price": "89.90", "stock_quantity": 25, "category_id": category["id"]},
    )
    assert response.status_code == 201
    product = response.json()
    assert product["price"] == "89.90"
    assert product["stock_quantity"] == 25
    assert product["is_active"] is True
    assert product["is_low_stock"] is False

    history = client.get(f"/products/{product['id']}/stock-movements").json()
    assert [(m["change"], m["reason"]) for m in history] == [(25, "Opening stock")]


def test_create_product_with_zero_stock_logs_nothing(client, make_product):
    product = make_product(stock_quantity=0)
    assert client.get(f"/products/{product['id']}/stock-movements").json() == []


def test_create_product_unknown_category_is_422(client):
    response = client.post(
        "/products", json={"sku": "X-1", "name": "X", "price": "1.00", "category_id": 999}
    )
    assert response.status_code == 422
    assert "Category 999 does not exist" in response.json()["detail"]


def test_duplicate_sku_is_conflict(client, make_product, make_category):
    category = make_category(name="Shared")
    make_product(sku="DRS-001", category_id=category["id"])
    response = client.post(
        "/products", json={"sku": "DRS-001", "name": "Other", "price": "5.00", "category_id": category["id"]}
    )
    assert response.status_code == 409
    assert "DRS-001" in response.json()["detail"]


def test_product_validation(client, make_category):
    category = make_category()
    base = {"sku": "S", "name": "N", "price": "10.00", "category_id": category["id"]}
    assert client.post("/products", json={**base, "price": "0"}).status_code == 422
    assert client.post("/products", json={**base, "price": "-3"}).status_code == 422
    assert client.post("/products", json={**base, "price": "10.123"}).status_code == 422
    assert client.post("/products", json={**base, "stock_quantity": -1}).status_code == 422
    assert client.post("/products", json={**base, "name": ""}).status_code == 422


def test_get_product_and_404(client, make_product):
    product = make_product()
    assert client.get(f"/products/{product['id']}").json()["sku"] == "DRS-001"
    response = client.get("/products/999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Product 999 not found"


def test_list_products_filters(client, make_category, make_product):
    dresses = make_category(name="Dresses")
    tops = make_category(name="Tops")
    make_product(sku="D1", name="Dress", category_id=dresses["id"])
    hidden = make_product(sku="T1", name="Top", category_id=tops["id"])
    client.put(
        f"/products/{hidden['id']}",
        json={"sku": "T1", "name": "Top", "price": "10.00", "category_id": tops["id"], "is_active": False},
    )

    assert len(client.get("/products").json()) == 2
    assert [p["sku"] for p in client.get("/products", params={"category_id": dresses["id"]}).json()] == ["D1"]
    assert [p["sku"] for p in client.get("/products", params={"is_active": False}).json()] == ["T1"]
    assert [p["sku"] for p in client.get("/products", params={"is_active": True}).json()] == ["D1"]
    assert len(client.get("/products", params={"skip": 1, "limit": 5}).json()) == 1


def test_update_product_replaces_catalogue_fields_but_not_stock(client, make_product, make_category):
    product = make_product(stock_quantity=10)
    new_category = make_category(name="Sale")
    response = client.put(
        f"/products/{product['id']}",
        json={
            "sku": "DRS-001",
            "name": "Renamed",
            "description": "New",
            "price": "59.00",
            "category_id": new_category["id"],
            "low_stock_threshold": 2,
            "is_active": True,
            "stock_quantity": 9999,  # ignored: stock only changes via /stock
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed" and body["price"] == "59.00" and body["category_id"] == new_category["id"]
    assert body["stock_quantity"] == 10


def test_update_product_errors(client, make_product, make_category):
    first = make_product(sku="A-1")
    second = make_product(sku="B-1")
    payload = {"sku": "A-1", "name": "N", "price": "5.00", "category_id": second["category_id"]}
    assert client.put("/products/999", json=payload).status_code == 404
    assert client.put(f"/products/{second['id']}", json=payload).status_code == 409  # SKU taken by first
    assert client.put(f"/products/{first['id']}", json={**payload, "category_id": 999}).status_code == 422
    # keeping its own SKU is fine
    assert client.put(f"/products/{first['id']}", json={**payload, "category_id": first["category_id"]}).status_code == 200


def test_delete_product_removes_it_and_its_history(client, make_product):
    product = make_product()
    assert client.delete(f"/products/{product['id']}").status_code == 204
    assert client.get(f"/products/{product['id']}").status_code == 404


def test_delete_missing_product_404(client):
    assert client.delete("/products/999").status_code == 404


def test_delete_product_used_in_order_is_conflict(client, make_product, place_order):
    product = make_product(stock_quantity=5)
    assert place_order([{"product_id": product["id"], "quantity": 1}]).status_code == 201
    response = client.delete(f"/products/{product['id']}")
    assert response.status_code == 409
    assert "deactivate" in response.json()["detail"]


# --------------------------------------------------------------------- inventory
def test_restock_and_remove_stock_are_logged(client, make_product):
    product = make_product(stock_quantity=10)
    added = client.post(f"/products/{product['id']}/stock", json={"change": 15, "reason": "Supplier delivery"})
    assert added.status_code == 200 and added.json()["stock_quantity"] == 25
    removed = client.post(f"/products/{product['id']}/stock", json={"change": -5, "reason": "Damaged"})
    assert removed.json()["stock_quantity"] == 20

    history = client.get(f"/products/{product['id']}/stock-movements").json()
    assert [(m["change"], m["reason"]) for m in history] == [
        (-5, "Damaged"),
        (15, "Supplier delivery"),
        (10, "Opening stock"),
    ]


def test_cannot_remove_more_stock_than_exists(client, make_product):
    product = make_product(stock_quantity=3)
    response = client.post(f"/products/{product['id']}/stock", json={"change": -4, "reason": "Oops"})
    assert response.status_code == 409
    assert "only 3 in stock" in response.json()["detail"]
    assert client.get(f"/products/{product['id']}").json()["stock_quantity"] == 3


def test_stock_adjustment_validation_and_404(client, make_product):
    product = make_product()
    assert client.post(f"/products/{product['id']}/stock", json={"change": 0, "reason": "x"}).status_code == 422
    assert client.post(f"/products/{product['id']}/stock", json={"change": 1, "reason": ""}).status_code == 422
    assert client.post("/products/999/stock", json={"change": 1, "reason": "x"}).status_code == 404
    assert client.get("/products/999/stock-movements").status_code == 404


def test_low_stock_report(client, make_product):
    make_product(sku="OK-1", stock_quantity=50)
    make_product(sku="LOW-1", stock_quantity=2)
    make_product(sku="OUT-1", stock_quantity=0)
    make_product(sku="CUSTOM-1", stock_quantity=8, low_stock_threshold=10)
    inactive = make_product(sku="OFF-1", stock_quantity=0)
    client.put(
        f"/products/{inactive['id']}",
        json={"sku": "OFF-1", "name": "Off", "price": "1.00", "category_id": inactive["category_id"], "is_active": False},
    )
    report = client.get("/products/low-stock").json()
    assert [p["sku"] for p in report] == ["OUT-1", "LOW-1", "CUSTOM-1"]
    assert all(p["is_low_stock"] for p in report)
