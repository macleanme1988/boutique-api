"""Application settings, read from environment variables."""
import os

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://boutique:boutique@localhost:5432/boutique",
)
