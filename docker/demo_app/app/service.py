from typing import Any

from sqlalchemy import text

from app.db import engine
from app.kafka_producer import publish_order_created

UNIT_PRICE = 9.99

_ORDER_COLUMNS = "id, sku, qty, amount, status, created_at"


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    order = dict(row)
    order["created_at"] = order["created_at"].isoformat()
    order["amount"] = float(order["amount"])
    return order


def create_order(sku: str, qty: int) -> dict[str, Any]:
    amount = round(qty * UNIT_PRICE, 2)
    with engine.begin() as conn:
        row = conn.execute(
            text(
                f"INSERT INTO orders (sku, qty, amount, status) VALUES (:sku, :qty, :amount, 'created') "
                f"RETURNING {_ORDER_COLUMNS}"
            ),
            {"sku": sku, "qty": qty, "amount": amount},
        ).mappings().first()
    order = _serialize(dict(row))
    publish_order_created(order)
    return order


def get_order(order_id: int) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT {_ORDER_COLUMNS} FROM orders WHERE id = :id"), {"id": order_id}
        ).mappings().first()
    return _serialize(dict(row)) if row is not None else None


def list_orders() -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT {_ORDER_COLUMNS} FROM orders ORDER BY id")).mappings().all()
    return [_serialize(dict(row)) for row in rows]
