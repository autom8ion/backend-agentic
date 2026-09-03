"""The "agentic" payoff: one scenario, four agents, one context, one
timeline. If any step below fails, the pytest plugin prints
``test_context.timeline()`` under the failure automatically - the REST call,
the DB poll, the Kafka wait and the GraphQL query all stamped with the same
correlation id and appearing in call order.
"""

import pytest
from assertpy2 import assert_conforms, assert_that

from backend_agentic.data.fake import unique_id
from tests.contracts.order_models import Order, OrderCreatedEvent

pytestmark = [pytest.mark.e2e, pytest.mark.rest, pytest.mark.db, pytest.mark.kafka, pytest.mark.graphql]

ORDER_QUERY = """
query Order($id: Int!) {
  order(id: $id) { id sku qty amount status createdAt }
}
"""


def test_order_lifecycle_across_every_surface(test_context, rest_agent, db_agent, kafka_agent, graphql_agent):
    sku = unique_id("sku")

    response = rest_agent.post("/orders", json={"sku": sku, "qty": 2})
    assert_that(response).has_status_code(201)
    order = assert_conforms(response.json(), Order).value

    row = (
        assert_that(lambda: db_agent.query_one("SELECT id, sku, status FROM orders WHERE id = :id", {"id": order.id}))
        .eventually_sync()
        .within(5)
        .is_not_none()
        .val
    )
    assert_that(row["sku"]).is_equal_to(sku)

    message = kafka_agent.wait_for_message(
        "orders", predicate=lambda m: m.value.get("order", {}).get("id") == order.id, timeout=15
    )
    event = assert_conforms(message.value, OrderCreatedEvent).value
    assert_that(event.order.id).is_equal_to(order.id)

    gql_order = graphql_agent.query(ORDER_QUERY, {"id": order.id}).data["order"]
    assert_that(gql_order["sku"]).is_equal_to(sku)

    assert_that(test_context.steps).is_not_empty()
