import pytest


@pytest.fixture()
def shop(client, make_category, make_product):
    dresses = make_category(name="Dresses")
    accessories = make_category(name="Accessories")
    make_product(sku="DRS-001", name="Linen Wrap Dress", description="Breathable linen", price="89.90",
                 stock_quantity=10, category_id=dresses["id"])
    make_product(sku="DRS-002", name="Satin Dress", description="Evening wear, linen lining", price="149.00",
                 stock_quantity=0, category_id=dresses["id"])
    make_product(sku="ACC-001", name="Leather Belt", description="100% leather", price="35.00",
                 stock_quantity=5, category_id=accessories["id"])
    return {"dresses": dresses, "accessories": accessories}


def skus(response):
    return [p["sku"] for p in response.json()["products"]]


def test_search_matches_name_description_and_sku_case_insensitively(client, shop):
    assert skus(client.get("/search", params={"q": "LINEN"})) == ["DRS-001", "DRS-002"]  # name match first
    assert skus(client.get("/search", params={"q": "satin"})) == ["DRS-002"]
    assert skus(client.get("/search", params={"q": "acc-001"})) == ["ACC-001"]


def test_name_matches_rank_before_description_matches(client, shop):
    response = client.get("/search", params={"q": "linen"}).json()
    assert response["total_products"] == 2
    assert response["products"][0]["name"] == "Linen Wrap Dress"


def test_search_returns_matching_categories(client, shop):
    body = client.get("/search", params={"q": "dress"}).json()
    assert body["query"] == "dress"
    assert [c["name"] for c in body["categories"]] == ["Dresses"]
    assert len(body["products"]) == 2


def test_filters(client, shop):
    dresses = shop["dresses"]["id"]
    assert skus(client.get("/search", params={"q": "d", "category_id": dresses})) == ["DRS-001", "DRS-002"]
    assert skus(client.get("/search", params={"q": "linen", "min_price": "100"})) == ["DRS-002"]
    assert skus(client.get("/search", params={"q": "linen", "max_price": "100"})) == ["DRS-001"]
    assert skus(client.get("/search", params={"q": "linen", "in_stock": True})) == ["DRS-001"]
    assert skus(client.get("/search", params={"q": "linen", "in_stock": False})) == ["DRS-002"]


def test_pagination_reports_total(client, shop):
    body = client.get("/search", params={"q": "linen", "limit": 1, "skip": 1}).json()
    assert body["total_products"] == 2
    assert [p["sku"] for p in body["products"]] == ["DRS-002"]


def test_inactive_products_are_hidden(client, shop):
    product = client.get("/products", params={"category_id": shop["accessories"]["id"]}).json()[0]
    client.put(
        f"/products/{product['id']}",
        json={"sku": "ACC-001", "name": "Leather Belt", "price": "35.00",
              "category_id": product["category_id"], "is_active": False},
    )
    assert skus(client.get("/search", params={"q": "belt"})) == []


def test_wildcards_are_literal(client, shop):
    assert skus(client.get("/search", params={"q": "%"})) == ["ACC-001"]  # only "100% leather" contains a %
    assert skus(client.get("/search", params={"q": "_"})) == []
    assert skus(client.get("/search", params={"q": "\\"})) == []


def test_no_match_returns_empty_lists(client, shop):
    body = client.get("/search", params={"q": "zzz"}).json()
    assert body == {"query": "zzz", "total_products": 0, "products": [], "categories": []}


def test_q_is_required_and_validated(client):
    assert client.get("/search").status_code == 422
    assert client.get("/search", params={"q": ""}).status_code == 422
    assert client.get("/search", params={"q": "x" * 101}).status_code == 422
    assert client.get("/search", params={"q": "a", "min_price": -1}).status_code == 422
