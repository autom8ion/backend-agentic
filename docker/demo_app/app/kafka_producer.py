import json
import os

from confluent_kafka import Producer

_producer: Producer | None = None


def get_producer() -> Producer:
    global _producer
    if _producer is None:
        bootstrap = os.environ.get("KAFKA_BOOTSTRAP", "localhost:19092")
        _producer = Producer({"bootstrap.servers": bootstrap})
    return _producer


def publish_order_created(order: dict) -> None:
    producer = get_producer()
    payload = json.dumps({"event": "order.created", "order": order}).encode("utf-8")
    producer.produce("orders", value=payload, key=str(order["id"]).encode("utf-8"))
    producer.flush(10)
