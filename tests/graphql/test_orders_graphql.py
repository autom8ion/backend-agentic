import pytest
from assertpy2 import assert_that

from backend_agentic.data.fake import unique_id

pytestmark = pytest.mark.graphql

CREATE_ORDER = """
mutation CreateOrder($sku: String!, $qty: Int!) {
  createOrder(sku: $sku, qty: $qty) {
    id sku qty amount status createdAt
  }
}
"""

ORDER_QUERY = """
query Order($id: Int!) {
  order(id: $id) {
    id sku qty amount status createdAt
  }
}
"""


def test_create_and_query_order(graphql_agent):
    sku = unique_id("sku")

    created = graphql_agent.mutate(CREATE_ORDER, {"sku": sku, "qty": 3}).data["createOrder"]
    assert_that(created["sku"]).is_equal_to(sku)

    order = graphql_agent.query(ORDER_QUERY, {"id": created["id"]}).data["order"]
    assert_that(order).is_equal_to(created)


def test_query_missing_order_returns_null(graphql_agent):
    result = graphql_agent.query(ORDER_QUERY, {"id": -1})

    assert_that(result.data["order"]).is_none()
