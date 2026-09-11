"""Great Expectations examples: validating a dataset's *shape and business
rules* in isolation - schema, nulls, uniqueness, value ranges, allowed sets,
and format patterns.

This is a different kind of check than :mod:`backend_agentic.reconciliation`:
reconciliation compares two datasets *to each other* (did REST and the DB
agree on every order?); data-quality expectations describe what a *single*
dataset must look like on its own (is every id unique? is every amount
positive?) regardless of where it came from. The two compose naturally in a
real scenario - validate a DB pull's quality before trusting it as the
source of truth for a reconciliation.

Requires the optional ``data-quality`` extra
(``pip install backend-agentic[data-quality]``, or ``uv sync --extra
data-quality``) - skipped via ``importorskip`` if it isn't installed, same as
any other optional capability in this framework never imported at package
top-level.
"""

from __future__ import annotations

import pytest

gx = pytest.importorskip("great_expectations")
pd = pytest.importorskip("pandas")
from great_expectations.expectations import (
    ExpectColumnValuesToBeBetween,
    ExpectColumnValuesToBeInSet,
    ExpectColumnValuesToBeUnique,
    ExpectColumnValuesToMatchRegex,
    ExpectColumnValuesToNotBeNull,
)

pytestmark = pytest.mark.unit

_ALLOWED_STATUSES = ["created", "shipped", "cancelled"]
_SKU_PATTERN = r"^[A-Z0-9]+-\d+$"


def _orders_expectation_suite(context: object, name: str) -> object:
    """The data-quality contract every ``orders`` dataset must satisfy,
    independent of which system it came from (DB, REST, a CSV export)."""
    suite = context.suites.add(gx.ExpectationSuite(name=name))
    suite.add_expectation(ExpectColumnValuesToBeUnique(column="id"))
    suite.add_expectation(ExpectColumnValuesToNotBeNull(column="sku"))
    suite.add_expectation(ExpectColumnValuesToMatchRegex(column="sku", regex=_SKU_PATTERN))
    suite.add_expectation(ExpectColumnValuesToBeBetween(column="amount", min_value=0, strict_min=True))
    suite.add_expectation(ExpectColumnValuesToBeInSet(column="status", value_set=_ALLOWED_STATUSES))
    return suite


def _validate_orders(context: object, df: pd.DataFrame, name: str) -> object:
    data_source = context.data_sources.add_pandas(f"{name}_source")
    asset = data_source.add_dataframe_asset(name=f"{name}_asset")
    batch_definition = asset.add_batch_definition_whole_dataframe(f"{name}_batch")
    batch = batch_definition.get_batch(batch_parameters={"dataframe": df})
    suite = _orders_expectation_suite(context, f"{name}_suite")
    return batch.validate(suite)


@pytest.fixture
def gx_context() -> object:
    # Ephemeral: config lives in memory for the test's lifetime, nothing
    # written to disk and no `great_expectations.yml` project needed - the
    # right mode for a suite defined and used entirely inside one test.
    return gx.get_context(mode="ephemeral")


def test_valid_orders_dataset_passes_every_expectation(gx_context: object) -> None:
    df = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "sku": ["A-1", "B-2", "C-30"],
            "amount": [10.5, 20.0, 5.25],
            "status": ["created", "shipped", "created"],
        }
    )

    result = _validate_orders(gx_context, df, "valid_orders")

    assert result.success, [r.expectation_config.type for r in result.results if not r.success]


def test_data_quality_violations_are_reported_per_expectation(gx_context: object) -> None:
    df = pd.DataFrame(
        {
            "id": [1, 1, 3],  # duplicate id
            "sku": ["A-1", "bad sku", None],  # bad pattern + null
            "amount": [10.5, -5.0, 0.0],  # non-positive amounts
            "status": ["created", "archived", "created"],  # "archived" not allowed
        }
    )

    result = _validate_orders(gx_context, df, "invalid_orders")

    assert not result.success
    failed = {r.expectation_config.type for r in result.results if not r.success}
    assert failed == {
        "expect_column_values_to_be_unique",
        "expect_column_values_to_not_be_null",
        "expect_column_values_to_match_regex",
        "expect_column_values_to_be_between",
        "expect_column_values_to_be_in_set",
    }
