# Live API test results

Server: `http://127.0.0.1:8000` · Database: PostgreSQL · Run: 2026-11-17 11:06 UTC

**27/27 checks passed**

| # | Check | Request | Expected | Actual | Result |
|---|---|---|---|---|---|
| 1 | Service and database are healthy | `GET /health` | 200 | 200 | PASS |
| 2 | Create category | `POST /categories` | 201 | 201 | PASS |
| 3 | Duplicate category rejected | `POST /categories` | 409 | 409 | PASS |
| 4 | Create product | `POST /products` | 201 | 201 | PASS |
| 5 | Duplicate SKU rejected | `POST /products` | 409 | 409 | PASS |
| 6 | Invalid price rejected by validation | `POST /products` | 422 | 422 | PASS |
| 7 | Read product | `GET /products/9` | 200 | 200 | PASS |
| 8 | Update product price | `PUT /products/9` | 200 | 200 | PASS |
| 9 | List products by category | `GET /products` | 200 | 200 | PASS |
| 10 | Search finds the product | `GET /search` | 200 | 200 | PASS |
| 11 | Search with no q is rejected | `GET /search` | 422 | 422 | PASS |
| 12 | Place order (reserves stock) | `POST /orders` | 201 | 201 | PASS |
| 13 | Stock reduced by the order | `GET /products/9` | 200 | 200 | PASS |
| 14 | Order for more than available is refused | `POST /orders` | 409 | 409 | PASS |
| 15 | Cannot skip order states | `PUT /orders/1` | 409 | 409 | PASS |
| 16 | Confirm order | `PUT /orders/1` | 200 | 200 | PASS |
| 17 | Cannot delete a confirmed order | `DELETE /orders/1` | 409 | 409 | PASS |
| 18 | Cancel order | `PUT /orders/1` | 200 | 200 | PASS |
| 19 | Cancelling returned the stock | `GET /products/9` | 200 | 200 | PASS |
| 20 | Restock +20 | `POST /products/9/stock` | 200 | 200 | PASS |
| 21 | Over-removal refused | `POST /products/9/stock` | 409 | 409 | PASS |
| 22 | Stock history | `GET /products/9/stock-movements` | 200 | 200 | PASS |
| 23 | Low-stock report | `GET /products/low-stock` | 200 | 200 | PASS |
| 24 | Set up scarce stock | `POST /products/9/stock` | 200 | 200 | PASS |
| 25 | 10 concurrent orders for 3 units | `POST /orders x10` | 3 | 3 | PASS |
| 26 | Deleting a product that has orders is blocked | `DELETE /products/9` | 409 | 409 | PASS |
| 27 | Unknown order is 404 | `GET /orders/999999` | 404 | 404 | PASS |

## Request and response log

### 1. Service and database are healthy
`GET /health` → **200** (expected 200)
```json
{
  "status": "ok",
  "database": "reachable"
}
```

### 2. Create category
`POST /categories` → **201** (expected 201)
```json
{
  "name": "Live Test Knitwear",
  "description": "Created by the live test",
  "id": 4,
  "created_at": "2026-11-17T11:06:24.294209Z"
}
```

### 3. Duplicate category rejected
`POST /categories` → **409** (expected 409)
```json
{
  "detail": "Category 'live test knitwear' already exists"
}
```

### 4. Create product
`POST /products` → **201** (expected 201)
```json
{
  "sku": "LIVE-001",
  "name": "Merino Cardigan",
  "description": "Soft merino wool",
  "price": "95.50",
  "category_id": 4,
  "low_stock_threshold": 5,
  "is_active": true,
  "id": 9,
  "stock_quantity": 5,
  "created_at": "2026-11-17T11:06:24.307472Z",
  "updated_at": "2026-11-17T11:06:24.307472Z",
  "is_low_stock": true
}
```

### 5. Duplicate SKU rejected
`POST /products` → **409** (expected 409)
```json
{
  "detail": "SKU 'LIVE-001' is already in use"
}
```

### 6. Invalid price rejected by validation
`POST /products` → **422** (expected 422)
```json
{
  "detail": [
    {
      "type": "greater_than",
      "loc": [
        "body",
        "price"
      ],
      "msg": "Input should be greater than 0",
      "input": "-5",
      "ctx": {
        "gt": 0
      }
    }
  ]
}
```

### 7. Read product
`GET /products/9` → **200** (expected 200)
```json
{
  "sku": "LIVE-001",
  "name": "Merino Cardigan",
  "description": "Soft merino wool",
  "price": "95.50",
  "category_id": 4,
  "low_stock_threshold": 5,
  "is_active": true,
  "id": 9,
  "stock_quantity": 5,
  "created_at": "2026-11-17T11:06:24.307472Z",
  "updated_at": "2026-11-17T11:06:24.307472Z",
  "is_low_stock": true
}
```

### 8. Update product price
`PUT /products/9` → **200** (expected 200)
```json
{
  "sku": "LIVE-001",
  "name": "Merino Cardigan",
  "description": "Soft merino wool",
  "price": "99.00",
  "category_id": 4,
  "low_stock_threshold": 2,
  "is_active": true,
  "id": 9,
  "stock_quantity": 5,
  "created_at": "2026-11-17T11:06:24.307472Z",
  "updated_at": "2026-11-17T11:06:24.325895Z",
  "is_low_stock": false
}
```

### 9. List products by category
`GET /products` → **200** (expected 200)
```json
[
  {
    "sku": "LIVE-001",
    "name": "Merino Cardigan",
    "description": "Soft merino wool",
    "price": "99.00",
    "category_id": 4,
    "low_stock_threshold": 2,
    "is_active": true,
    "id": 9,
    "stock_quantity": 5,
    "created_at": "2026-11-17T11:06:24.307472Z",
    "updated_at": "2026-11-17T11:06:24.325895Z",
    "is_low_stock": false
  }
]
```

### 10. Search finds the product
`GET /search` → **200** (expected 200)
```json
{
  "query": "merino",
  "total_products": 1,
  "products": [
    {
      "sku": "LIVE-001",
      "name": "Merino Cardigan",
      "description": "Soft merino wool",
      "price": "99.00",
      "category_id": 4,
      "low_stock_threshold": 2,
      "is_active": true,
      "id": 9,
      "stock_quantity": 5,
      "created_at": "2026-11-17T11:06:24.307472Z",
      "updated_at": "2026-11-17T11:06:24.325895Z",
      "is_low_stock": false
    }
  ],
  "categories": []
}
```

### 11. Search with no q is rejected
`GET /search` → **422** (expected 422)
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": [
        "query",
        "q"
      ],
      "msg": "Field required",
      "input": null
    }
  ]
}
```

### 12. Place order (reserves stock)
`POST /orders` → **201** (expected 201)
```json
{
  "id": 1,
  "customer_name": "Ama Mensah",
  "customer_email": "ama@example.com",
  "shipping_address": "12 Market Road, Bolgatanga",
  "status": "pending",
  "total_amount": "198.00",
  "items": [
    {
      "product_id": 9,
      "product_name": "Merino Cardigan",
      "quantity": 2,
      "unit_price": "99.00",
      "line_total": "198.00"
    }
  ],
  "created_at": "2026-11-17T11:06:24.349311Z",
  "updated_at": "2026-11-17T11:06:24.349311Z"
}
```

### 13. Stock reduced by the order
`GET /products/9` → **200** (expected 200)
```json
{
  "sku": "LIVE-001",
  "name": "Merino Cardigan",
  "description": "Soft merino wool",
  "price": "99.00",
  "category_id": 4,
  "low_stock_threshold": 2,
  "is_active": true,
  "id": 9,
  "stock_quantity": 3,
  "created_at": "2026-11-17T11:06:24.307472Z",
  "updated_at": "2026-11-17T11:06:24.349311Z",
  "is_low_stock": false
}
```

### 14. Order for more than available is refused
`POST /orders` → **409** (expected 409)
```json
{
  "detail": "Insufficient stock for product 9 ('Merino Cardigan'): requested 99, available 3"
}
```

### 15. Cannot skip order states
`PUT /orders/1` → **409** (expected 409)
```json
{
  "detail": "Cannot move order from pending to delivered; allowed: cancelled, confirmed"
}
```

### 16. Confirm order
`PUT /orders/1` → **200** (expected 200)
```json
{
  "id": 1,
  "customer_name": "Ama Mensah",
  "customer_email": "ama@example.com",
  "shipping_address": null,
  "status": "confirmed",
  "total_amount": "198.00",
  "items": [
    {
      "product_id": 9,
      "product_name": "Merino Cardigan",
      "quantity": 2,
      "unit_price": "99.00",
      "line_total": "198.00"
    }
  ],
  "created_at": "2026-11-17T11:06:24.349311Z",
  "updated_at": "2026-11-17T11:06:24.383260Z"
}
```

### 17. Cannot delete a confirmed order
`DELETE /orders/1` → **409** (expected 409)
```json
{
  "detail": "Order 1 is confirmed; cancel it first or keep it for the records"
}
```

### 18. Cancel order
`PUT /orders/1` → **200** (expected 200)
```json
{
  "id": 1,
  "customer_name": "Ama Mensah",
  "customer_email": "ama@example.com",
  "shipping_address": null,
  "status": "cancelled",
  "total_amount": "198.00",
  "items": [
    {
      "product_id": 9,
      "product_name": "Merino Cardigan",
      "quantity": 2,
      "unit_price": "99.00",
      "line_total": "198.00"
    }
  ],
  "created_at": "2026-11-17T11:06:24.349311Z",
  "updated_at": "2026-11-17T11:06:24.396688Z"
}
```

### 19. Cancelling returned the stock
`GET /products/9` → **200** (expected 200)
```json
{
  "sku": "LIVE-001",
  "name": "Merino Cardigan",
  "description": "Soft merino wool",
  "price": "99.00",
  "category_id": 4,
  "low_stock_threshold": 2,
  "is_active": true,
  "id": 9,
  "stock_quantity": 5,
  "created_at": "2026-11-17T11:06:24.307472Z",
  "updated_at": "2026-11-17T11:06:24.396688Z",
  "is_low_stock": false
}
```

### 20. Restock +20
`POST /products/9/stock` → **200** (expected 200)
```json
{
  "sku": "LIVE-001",
  "name": "Merino Cardigan",
  "description": "Soft merino wool",
  "price": "99.00",
  "category_id": 4,
  "low_stock_threshold": 2,
  "is_active": true,
  "id": 9,
  "stock_quantity": 25,
  "created_at": "2026-11-17T11:06:24.307472Z",
  "updated_at": "2026-11-17T11:06:24.408228Z",
  "is_low_stock": false
}
```

### 21. Over-removal refused
`POST /products/9/stock` → **409** (expected 409)
```json
{
  "detail": "Cannot remove 100: only 25 in stock"
}
```

### 22. Stock history
`GET /products/9/stock-movements` → **200** (expected 200)
```json
[
  {
    "id": 11,
    "product_id": 9,
    "change": 20,
    "reason": "Supplier delivery",
    "order_id": null,
    "created_at": "2026-11-17T11:06:24.408228Z"
  },
  {
    "id": 10,
    "product_id": 9,
    "change": 2,
    "reason": "Order cancelled",
    "order_id": 1,
    "created_at": "2026-11-17T11:06:24.396688Z"
  },
  {
    "id": 9,
    "product_id": 9,
    "change": -2,
    "reason": "Order placed",
    "order_id": 1,
    "created_at": "2026-11-17T11:06:24.349311Z"
  },
  {
    "id": 8,
    "product_id": 9,
    "change": 5,
    "reason": "Opening stock",
    "order_id": null,
    "created_at": "2026-11-17T11:06:24.307472Z"
  }
]
```

### 23. Low-stock report
`GET /products/low-stock` → **200** (expected 200)
```json
[
  {
    "sku": "ACC-003",
    "name": "Silk Scarf",
    "description": "Printed silk, 90cm square",
    "price": "28.00",
    "category_id": 3,
    "low_stock_threshold": 5,
    "is_active": true,
    "id": 8,
    "stock_quantity": 0,
    "created_at": "2026-11-17T11:06:20.031956Z",
    "updated_at": "2026-11-17T11:06:20.031956Z",
    "is_low_stock": true
  },
  {
    "sku": "TOP-002",
    "name": "Cotton Peplum Blouse",
    "description": "Soft cotton with peplum hem",
    "price": "39.00",
    "category_id": 2,
    "low_stock_threshold": 5,
    "is_active": true,
    "id": 5,
    "stock_quantity": 3,
    "created_at": "2026-11-17T11:06:20.031956Z",
    "updated_at": "2026-11-17T11:06:20.031956Z",
    "is_low_stock": true
  }
]
```

### 24. Set up scarce stock
`POST /products/9/stock` → **200** (expected 200)
```json
{
  "sku": "LIVE-001",
  "name": "Merino Cardigan",
  "description": "Soft merino wool",
  "price": "99.00",
  "category_id": 4,
  "low_stock_threshold": 2,
  "is_active": true,
  "id": 9,
  "stock_quantity": 3,
  "created_at": "2026-11-17T11:06:24.307472Z",
  "updated_at": "2026-11-17T11:06:24.423230Z",
  "is_low_stock": false
}
```

### Concurrency check
10 simultaneous orders for 3 units → **3 accepted, 7 refused**, final stock **0**.

### 26. Deleting a product that has orders is blocked
`DELETE /products/9` → **409** (expected 409)
```json
{
  "detail": "Product 9 appears in 4 order line(s); deactivate it (is_active=false) instead"
}
```

### 27. Unknown order is 404
`GET /orders/999999` → **404** (expected 404)
```json
{
  "detail": "Order 999999 not found"
}
```
