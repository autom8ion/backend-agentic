"""Property-based tests (via Hypothesis) for ``reconcile()`` - the vectorized
polars outer join ``ReconciliationAgent.compare()`` wraps (see
``reconciliation/agent.py``). Per CLAUDE.md, this is another piece of the
framework's pure logic with no unit-test coverage in isolation before this;
every existing example test only exercises it against the live demo stack.

The strategy below is a classic "test against a naive oracle" property test:
Hypothesis generates random left/right key sets and amounts (including the
empty-frame and fully-overlapping edge cases a hand-written example test
would rarely think to cover), a plain Python set comparison computes what the
*correct* classification should be, and the test asserts ``reconcile()``'s
vectorized join agrees with it exactly.
"""

from __future__ import annotations

import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend_agentic.reconciliation.agent import reconcile

pytestmark = pytest.mark.unit

_ids = st.lists(st.integers(min_value=0, max_value=30), max_size=12, unique=True)


def _frame(ids: list[int], amounts: dict[int, int]) -> pl.DataFrame:
    return pl.DataFrame(
        {"id": ids, "amount": [amounts[i] for i in ids]},
        schema={"id": pl.Int64, "amount": pl.Int64},
    )


@given(left_ids=_ids, right_ids=_ids, data=st.data())
def test_matched_and_mismatched_agree_with_a_naive_set_comparison(
    left_ids: list[int], right_ids: list[int], data: st.DataObject
) -> None:
    left_amounts = {i: data.draw(st.integers(min_value=0, max_value=1000)) for i in left_ids}
    right_amounts = {i: data.draw(st.integers(min_value=0, max_value=1000)) for i in right_ids}
    left = _frame(left_ids, left_amounts)
    right = _frame(right_ids, right_amounts)

    result = reconcile(left, right, keys=["id"])

    common = set(left_ids) & set(right_ids)
    expected_matched = {i for i in common if left_amounts[i] == right_amounts[i]}
    expected_mismatched = common - expected_matched
    expected_only_left = set(left_ids) - common
    expected_only_right = set(right_ids) - common

    assert set(result.matched["id"].to_list()) == expected_matched
    assert set(result.mismatches["id"].to_list()) == expected_mismatched
    assert set(result.only_in_left["id"].to_list()) == expected_only_left
    assert set(result.only_in_right["id"].to_list()) == expected_only_right
    # every id landed in exactly one bucket - no double-counting, nothing dropped
    assert result.matched.height + len(expected_mismatched) + result.only_in_left.height + result.only_in_right.height == len(
        set(left_ids) | set(right_ids)
    )


@given(left_ids=_ids, right_ids=_ids, data=st.data())
def test_match_rate_is_always_a_valid_proportion(
    left_ids: list[int], right_ids: list[int], data: st.DataObject
) -> None:
    left_amounts = {i: data.draw(st.integers(min_value=0, max_value=1000)) for i in left_ids}
    right_amounts = {i: data.draw(st.integers(min_value=0, max_value=1000)) for i in right_ids}
    left = _frame(left_ids, left_amounts)
    right = _frame(right_ids, right_amounts)

    result = reconcile(left, right, keys=["id"])

    assert 0.0 <= result.match_rate <= 1.0
    if not left_ids and not right_ids:
        assert result.match_rate == 1.0  # vacuously fully reconciled
    assert result.is_reconciled == (result.match_rate == 1.0)
