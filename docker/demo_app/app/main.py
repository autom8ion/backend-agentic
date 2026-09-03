from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from strawberry.fastapi import GraphQLRouter

from app import service
from app.graphql_schema import schema

app = FastAPI(title="backend-agentic demo app")
app.include_router(GraphQLRouter(schema), prefix="/graphql")


class CreateOrderRequest(BaseModel):
    sku: str
    qty: int


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/orders", status_code=201)
def create_order(payload: CreateOrderRequest) -> dict:
    return service.create_order(payload.sku, payload.qty)


@app.get("/orders/{order_id}")
def get_order(order_id: int) -> dict:
    order = service.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@app.get("/orders")
def list_orders() -> list[dict]:
    return service.list_orders()
