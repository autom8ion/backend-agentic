import pytest
from assertpy2 import assert_that

from backend_agentic.data.fake import unique_id
from backend_agentic.reconciliation import loaders

pytestmark = [pytest.mark.rest, pytest.mark.db, pytest.mark.reconciliation]


def test_rest_listing_matches_db_table(rest_agent, db_agent, recon_agent):
    for _ in range(3):
        rest_agent.post("/orders", json={"sku": unique_id("sku"), "qty": 1})

    db_orders = loaders.from_db(db_agent, "SELECT id, sku, qty, amount, status FROM orders")
    rest_orders = loaders.from_rest(rest_agent.get("/orders")).select(db_orders.columns)

    result = recon_agent.compare(db_orders, rest_orders, keys=["id"], tolerance={"amount": 0.01})

    assert_that(result).is_fully_reconciled()
