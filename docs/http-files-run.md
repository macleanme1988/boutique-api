# .http collection run against `http://127.0.0.1:8000`

**40/40 requests returned the documented status**

| File | Request | Call | Expected | Actual | Result |
|---|---|---|---|---|---|
| categories.http | List categories (sorted by name, paginated) | `GET /categories?skip=0&limit=50` | 2xx | 200 | PASS |
| categories.http | Get one category | `GET /categories/1` | 2xx | 200 | PASS |
| categories.http | Create a category | `POST /categories` | 201 | 201 | PASS |
| categories.http | Duplicate name (case-insensitive) | `POST /categories` | 409 | 409 | PASS |
| categories.http | Replace a category (PUT) | `PUT /categories/1` | 200 | 200 | PASS |
| categories.http | Missing category | `GET /categories/99999` | 404 | 404 | PASS |
| categories.http | Validation error (empty name) | `POST /categories` | 422 | 422 | PASS |
| categories.http | Delete a category that still has products | `DELETE /categories/1` | 409 | 409 | PASS |
| products.http | List products (filters: category_id, is_active, skip, limit) | `GET /products?category_id=1&is_active=true&limit=20` | 2xx | 200 | PASS |
| products.http | Get one product | `GET /products/1` | 2xx | 200 | PASS |
| products.http | Create a product | `POST /products` | 201 | 201 | PASS |
| products.http | Duplicate SKU | `POST /products` | 409 | 409 | PASS |
| products.http | Unknown category | `POST /products` | 422 | 422 | PASS |
| products.http | Invalid price | `POST /products` | 422 | 422 | PASS |
| products.http | Replace catalogue fields (PUT). Stock is NOT changed here; use /stock. | `PUT /products/1` | 2xx | 200 | PASS |
| products.http | Deactivate a product (hides it from search, blocks new orders) | `PUT /products/8` | 2xx | 200 | PASS |
| products.http | Delete a product that is in no order | `DELETE /products/8` | 204 | 204 | PASS |
| inventory.http | Low-stock report: active products at or below their reorder level | `GET /products/low-stock` | 2xx | 200 | PASS |
| inventory.http | Restock +20 | `POST /products/1/stock` | 200 | 200 | PASS |
| inventory.http | Remove stock (damaged goods) | `POST /products/1/stock` | 200 | 200 | PASS |
| inventory.http | Remove more than exists | `POST /products/1/stock` | 409 | 409 | PASS |
| inventory.http | Zero change | `POST /products/1/stock` | 422 | 422 | PASS |
| inventory.http | Stock history for a product (newest first) | `GET /products/1/stock-movements` | 2xx | 200 | PASS |
| orders.http | List orders (filters: status, customer_email, skip, limit) | `GET /orders?status=pending` | 2xx | 200 | PASS |
| orders.http | Place an order | `POST /orders` | 201 | 201 | PASS |
| orders.http | Get the order we just placed | `GET /orders/1` | 2xx | 200 | PASS |
| orders.http | More than available | `POST /orders` | 409 | 409 | PASS |
| orders.http | Unknown product | `POST /orders` | 422 | 422 | PASS |
| orders.http | Empty basket | `POST /orders` | 422 | 422 | PASS |
| orders.http | Confirm the order. Lifecycle: pending > confirmed > shipped > delivere | `PUT /orders/1` | 2xx | 200 | PASS |
| orders.http | Skip a state (confirmed > delivered) | `PUT /orders/1` | 409 | 409 | PASS |
| orders.http | Cancel the order: stock goes back, order becomes final | `PUT /orders/1` | 2xx | 200 | PASS |
| orders.http | Delete a cancelled (or pending) order | `DELETE /orders/1` | 204 | 204 | PASS |
| orders.http | Missing order | `GET /orders/99999` | 404 | 404 | PASS |
| search.http | Simple search (case-insensitive; name matches are listed first) | `GET /search?q=linen` | 2xx | 200 | PASS |
| search.http | Search by SKU | `GET /search?q=drs-001` | 2xx | 200 | PASS |
| search.http | With filters: price range, in-stock only, one category | `GET /search?q=dress&min_price=50&max_price=150&in_stock=true&category_id=1` | 2xx | 200 | PASS |
| search.http | Pagination (total_products counts all matches) | `GET /search?q=silk&skip=0&limit=5` | 2xx | 200 | PASS |
| search.http | Missing q | `GET /search` | 422 | 422 | PASS |
| search.http | Health check | `GET /health` | 2xx | 200 | PASS |
