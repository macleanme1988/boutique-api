"""Load demo boutique data:  python -m app.seed   (safe to run twice)."""
from decimal import Decimal

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Category, InventoryMovement, Product

CATALOGUE = {
    "Dresses": [
        ("DRS-001", "Linen Wrap Dress", "Breathable linen, knee length", "89.90", 24),
        ("DRS-002", "Satin Evening Dress", "Floor-length satin with side slit", "149.00", 8),
        ("DRS-003", "Kente Print Midi Dress", "Hand-finished kente-inspired cotton", "120.00", 15),
    ],
    "Tops": [
        ("TOP-001", "Silk Camisole", "Pure silk, adjustable straps", "54.50", 40),
        ("TOP-002", "Cotton Peplum Blouse", "Soft cotton with peplum hem", "39.00", 3),
    ],
    "Accessories": [
        ("ACC-001", "Leather Belt", "Full-grain leather, brass buckle", "35.00", 60),
        ("ACC-002", "Woven Straw Tote", "Hand-woven bag, linen lining", "72.00", 12),
        ("ACC-003", "Silk Scarf", "Printed silk, 90cm square", "28.00", 0),
    ],
}


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.scalar(select(Category.id).limit(1)) is not None:
            print("Database already has data; nothing to do.")
            return
        for category_name, items in CATALOGUE.items():
            category = Category(name=category_name, description=f"{category_name} for every season")
            db.add(category)
            db.flush()
            for sku, name, description, price, stock in items:
                product = Product(
                    sku=sku,
                    name=name,
                    description=description,
                    price=Decimal(price),
                    stock_quantity=stock,
                    category_id=category.id,
                )
                db.add(product)
                db.flush()
                if stock:
                    db.add(InventoryMovement(product_id=product.id, change=stock, reason="Opening stock"))
        db.commit()
        print("Seeded 3 categories and 8 products.")


if __name__ == "__main__":
    seed()
