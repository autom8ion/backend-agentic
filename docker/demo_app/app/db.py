import os

from sqlalchemy import create_engine

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/orders"
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
