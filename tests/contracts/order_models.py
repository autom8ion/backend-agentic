"""The order contract, shared by the REST, GraphQL, DB and Kafka example
tests so all four are checked against exactly the same shape.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Order(BaseModel):
    id: int
    sku: str
    qty: int
    amount: float
    status: str
    created_at: datetime


class OrderCreatedEvent(BaseModel):
    event: str
    order: Order
