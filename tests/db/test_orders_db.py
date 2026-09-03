import pytest
from assertpy2 import assert_that

from backend_agentic.data.fake import unique_id

pytestmark = [pytest.mark.rest, pytest.mark.db]


def test_created_order_is_persisted(rest_agent, db_agent):
    sku = unique_id("sku")
    created = rest_agent.post("/orders", json={"sku": sku, "qty": 2}).json()

    # the write may still be in flight when this test's request returns, so poll
    # instead of a single immediate read - see backend_agentic.core.agent.BaseAgent
    row = (
        assert_that(lambda: db_agent.query_one("SELECT id, sku, status FROM orders WHERE id = :id", {"id": created["id"]}))
        .eventually_sync()
        .within(5)
        .is_not_none()
        .val
    )

    assert_that(row["sku"]).is_equal_to(sku)
    assert_that(row["status"]).is_equal_to("created")


def test_fixture_row_via_rollback_after_is_not_left_behind(db_agent):
    with db_agent.rollback_after() as conn:
        from sqlalchemy import text

        conn.execute(
            text("INSERT INTO orders (sku, qty, amount, status) VALUES (:sku, 1, 9.99, 'created')"),
            {"sku": "throwaway-fixture-row"},
        )
        row = conn.execute(
            text("SELECT sku FROM orders WHERE sku = :sku"), {"sku": "throwaway-fixture-row"}
        ).mappings().first()
        assert_that(dict(row)["sku"]).is_equal_to("throwaway-fixture-row")

    # outside the block the transaction was rolled back
    assert_that(db_agent.query_one("SELECT sku FROM orders WHERE sku = :sku", {"sku": "throwaway-fixture-row"})).is_none()
