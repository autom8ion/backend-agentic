from datetime import datetime
from typing import Optional

import strawberry

from app import service


@strawberry.type
class Order:
    id: int
    sku: str
    qty: int
    amount: float
    status: str
    created_at: datetime


def _to_order(row: dict) -> Order:
    return Order(
        id=row["id"],
        sku=row["sku"],
        qty=row["qty"],
        amount=row["amount"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


@strawberry.type
class Query:
    @strawberry.field
    def order(self, id: int) -> Optional[Order]:
        row = service.get_order(id)
        return _to_order(row) if row is not None else None

    @strawberry.field
    def orders(self) -> list[Order]:
        return [_to_order(row) for row in service.list_orders()]


@strawberry.type
class Mutation:
    @strawberry.mutation
    def create_order(self, sku: str, qty: int) -> Order:
        return _to_order(service.create_order(sku, qty))


schema = strawberry.Schema(query=Query, mutation=Mutation)
