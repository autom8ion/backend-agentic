import pytest
from assertpy2 import assert_that

from backend_agentic.data.fake import unique_id

pytestmark = [pytest.mark.rest, pytest.mark.kafka]


def test_order_created_publishes_event(rest_agent, kafka_agent):
    sku = unique_id("sku")
    created = rest_agent.post("/orders", json={"sku": sku, "qty": 1}).json()

    message = kafka_agent.wait_for_message(
        "orders",
        predicate=lambda m: m.value.get("order", {}).get("id") == created["id"],
        timeout=15,
    )

    assert_that(message.value["event"]).is_equal_to("order.created")
    assert_that(message.value["order"]).matches_structure({"id": created["id"], "sku": sku})
