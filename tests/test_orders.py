def stock(client, product_id):
    return client.get(f"/products/{product_id}").json()["stock_quantity"]


def update_payload(order, **changes):
    base = {
        "customer_name": order["customer_name"],
        "customer_email": order["customer_email"],
        "shipping_address": order["shipping_address"],
        "status": order["status"],
    }
    return {**base, **changes}


def test_place_order_computes_total_and_reserves_stock(client, make_product, place_order):
    dress = make_product(sku="D1", name="Dress", price="89.90", stock_quantity=10)
    belt = make_product(sku="B1", name="Belt", price="35.00", stock_quantity=4)
    response = place_order(
        [{"product_id": dress["id"], "quantity": 2}, {"product_id": belt["id"], "quantity": 1}],
        shipping_address="12 Market Road",
    )
    assert response.status_code == 201
    order = response.json()
    assert order["status"] == "pending"
    assert order["total_amount"] == "214.80"  # 2 x 89.90 + 35.00
    assert [(i["product_name"], i["quantity"], i["line_total"]) for i in order["items"]] == [
        ("Dress", 2, "179.80"),
        ("Belt", 1, "35.00"),
    ]
    assert stock(client, dress["id"]) == 8
    assert stock(client, belt["id"]) == 3
    movement = client.get(f"/products/{dress['id']}/stock-movements").json()[0]
    assert movement["change"] == -2 and movement["order_id"] == order["id"]


def test_duplicate_lines_are_merged(client, make_product, place_order):
    product = make_product(stock_quantity=10, price="10.00")
    order = place_order(
        [{"product_id": product["id"], "quantity": 2}, {"product_id": product["id"], "quantity": 3}]
    ).json()
    assert len(order["items"]) == 1 and order["items"][0]["quantity"] == 5
    assert order["total_amount"] == "50.00"
    assert stock(client, product["id"]) == 5


def test_price_is_frozen_at_order_time(client, make_product, place_order):
    product = make_product(price="20.00", stock_quantity=5)
    order = place_order([{"product_id": product["id"], "quantity": 1}]).json()
    client.put(
        f"/products/{product['id']}",
        json={"sku": product["sku"], "name": product["name"], "price": "99.00", "category_id": product["category_id"]},
    )
    assert client.get(f"/orders/{order['id']}").json()["items"][0]["unit_price"] == "20.00"


def test_insufficient_stock_rejects_whole_order(client, make_product, place_order):
    plenty = make_product(sku="P1", stock_quantity=10)
    scarce = make_product(sku="S1", name="Scarce", stock_quantity=1)
    response = place_order(
        [{"product_id": plenty["id"], "quantity": 2}, {"product_id": scarce["id"], "quantity": 5}]
    )
    assert response.status_code == 409
    assert "requested 5, available 1" in response.json()["detail"]
    assert stock(client, plenty["id"]) == 10  # nothing was reserved
    assert client.get("/orders").json() == []


def test_unknown_or_inactive_product_rejected(client, make_product, place_order):
    product = make_product()
    unknown = place_order([{"product_id": 999, "quantity": 1}])
    assert unknown.status_code == 422 and "[999]" in unknown.json()["detail"]

    client.put(
        f"/products/{product['id']}",
        json={"sku": product["sku"], "name": product["name"], "price": "5.00", "category_id": product["category_id"], "is_active": False},
    )
    inactive = place_order([{"product_id": product["id"], "quantity": 1}])
    assert inactive.status_code == 409 and "not available" in inactive.json()["detail"]


def test_order_validation(client, make_product, place_order):
    product = make_product()
    assert place_order([]).status_code == 422
    assert place_order([{"product_id": product["id"], "quantity": 0}]).status_code == 422
    assert place_order([{"product_id": product["id"], "quantity": 1}], customer_email="not-an-email").status_code == 422
    assert client.post("/orders", json={"customer_name": "A"}).status_code == 422


def test_get_and_list_orders_with_filters(client, make_product, place_order):
    product = make_product(stock_quantity=20)
    line = [{"product_id": product["id"], "quantity": 1}]
    first = place_order(line).json()
    second = place_order(line, customer_email="kofi@example.com", customer_name="Kofi").json()
    client.put(f"/orders/{second['id']}", json=update_payload(second, status="confirmed"))

    assert client.get(f"/orders/{first['id']}").json()["customer_name"] == "Ama Mensah"
    assert client.get("/orders/999").status_code == 404
    assert len(client.get("/orders").json()) == 2
    assert [o["id"] for o in client.get("/orders", params={"status": "confirmed"}).json()] == [second["id"]]
    assert [o["id"] for o in client.get("/orders", params={"customer_email": "ama@example.com"}).json()] == [first["id"]]
    assert len(client.get("/orders", params={"skip": 1, "limit": 1}).json()) == 1
    assert client.get("/orders", params={"status": "bogus"}).status_code == 422


def test_status_lifecycle(client, make_product, place_order):
    product = make_product(stock_quantity=5)
    order = place_order([{"product_id": product["id"], "quantity": 1}]).json()
    for new_status in ("confirmed", "shipped", "delivered"):
        response = client.put(f"/orders/{order['id']}", json=update_payload(order, status=new_status))
        assert response.status_code == 200 and response.json()["status"] == new_status
    assert stock(client, product["id"]) == 4  # delivery does not touch stock


def test_invalid_transition_is_conflict(client, make_product, place_order):
    product = make_product()
    order = place_order([{"product_id": product["id"], "quantity": 1}]).json()
    response = client.put(f"/orders/{order['id']}", json=update_payload(order, status="shipped"))
    assert response.status_code == 409
    assert "allowed: cancelled, confirmed" in response.json()["detail"]


def test_update_customer_details_without_changing_status(client, make_product, place_order):
    product = make_product()
    order = place_order([{"product_id": product["id"], "quantity": 1}]).json()
    response = client.put(
        f"/orders/{order['id']}",
        json=update_payload(order, customer_name="Ama B.", shipping_address="New address"),
    )
    assert response.status_code == 200
    assert response.json()["customer_name"] == "Ama B." and response.json()["status"] == "pending"


def test_cancel_returns_stock_and_order_becomes_final(client, make_product, place_order):
    product = make_product(stock_quantity=5)
    order = place_order([{"product_id": product["id"], "quantity": 3}]).json()
    assert stock(client, product["id"]) == 2

    cancelled = client.put(f"/orders/{order['id']}", json=update_payload(order, status="cancelled"))
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert stock(client, product["id"]) == 5
    assert client.get(f"/products/{product['id']}/stock-movements").json()[0]["reason"] == "Order cancelled"

    again = client.put(f"/orders/{order['id']}", json=update_payload(order, status="pending"))
    assert again.status_code == 409 and "cannot be changed" in again.json()["detail"]
    assert stock(client, product["id"]) == 5  # not restocked twice


def test_update_missing_order_404(client):
    payload = {"customer_name": "A", "customer_email": "a@example.com", "status": "pending"}
    assert client.put("/orders/999", json=payload).status_code == 404


def test_delete_pending_order_restores_stock_and_keeps_history(client, make_product, place_order):
    product = make_product(stock_quantity=5)
    order = place_order([{"product_id": product["id"], "quantity": 2}]).json()
    assert client.delete(f"/orders/{order['id']}").status_code == 204
    assert client.get(f"/orders/{order['id']}").status_code == 404
    assert stock(client, product["id"]) == 5
    history = client.get(f"/products/{product['id']}/stock-movements").json()
    assert [m["change"] for m in history] == [2, -2, 5]
    assert all(m["order_id"] is None for m in history)


def test_delete_cancelled_order_does_not_restock_again(client, make_product, place_order):
    product = make_product(stock_quantity=5)
    order = place_order([{"product_id": product["id"], "quantity": 2}]).json()
    client.put(f"/orders/{order['id']}", json=update_payload(order, status="cancelled"))
    assert client.delete(f"/orders/{order['id']}").status_code == 204
    assert stock(client, product["id"]) == 5


def test_cannot_delete_confirmed_order(client, make_product, place_order):
    product = make_product()
    order = place_order([{"product_id": product["id"], "quantity": 1}]).json()
    client.put(f"/orders/{order['id']}", json=update_payload(order, status="confirmed"))
    response = client.delete(f"/orders/{order['id']}")
    assert response.status_code == 409 and "confirmed" in response.json()["detail"]


def test_delete_missing_order_404(client):
    assert client.delete("/orders/999").status_code == 404
