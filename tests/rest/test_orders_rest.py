import pytest
from assertpy2 import assert_conforms, assert_that

from backend_agentic.assertions.matchers import is_iso_datetime
from backend_agentic.data.fake import fake, unique_id
from tests.contracts.order_models import Order

pytestmark = pytest.mark.rest


def test_create_order_returns_a_conforming_order(rest_agent):
    payload = {"sku": unique_id("sku"), "qty": fake.random_int(min=1, max=5)}

    response = rest_agent.post("/orders", json=payload)

    assert_that(response).has_status_code(201)
    order = assert_conforms(response.json(), Order).value
    assert_that(order.sku).is_equal_to(payload["sku"])
    assert_that(order.status).is_equal_to("created")


def test_get_order_by_id(rest_agent):
    created = rest_agent.post("/orders", json={"sku": unique_id("sku"), "qty": 1}).json()

    response = rest_agent.get(f"/orders/{created['id']}")

    assert_that(response).has_status_code(200)
    assert_that(response.json()).matches_structure({"id": created["id"], "created_at": is_iso_datetime()})


def test_get_missing_order_is_404(rest_agent):
    response = rest_agent.get("/orders/999999999")

    assert_that(response).has_status_code(404)
