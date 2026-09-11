"""Property-based tests (via Hypothesis) for ``PerfEndpointStats._from_csv_row``
- the pure CSV-row parser ``PerfResult._from_csv`` calls once per row of
Locust's ``--csv`` output.

CLAUDE.md flags this exact function by name: it shipped with a real bug
(Locust writes ``"N/A"`` in every timing column for a row with zero
requests, and the first cut of this parser didn't handle that) that only
surfaced by actually running a load test, because nothing exercised the
parser in isolation. Hypothesis generates far more row shapes - including
"N/A" landing on an arbitrary subset of columns - than anyone would hand-write
as example tests, which is exactly the kind of regression this is meant to
catch before a live run does.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend_agentic.perf.agent import _PERCENTILE_COLUMNS, PerfEndpointStats

pytestmark = pytest.mark.unit

# Every non-count column Locust's stats CSV can write "N/A" into, mapped to
# the PerfEndpointStats attribute it feeds.
_TIMING_ATTR_BY_COLUMN: dict[str, str] = {
    "Median Response Time": "median_ms",
    "Average Response Time": "average_ms",
    "Min Response Time": "min_ms",
    "Max Response Time": "max_ms",
    "Requests/s": "requests_per_sec",
    "Failures/s": "failures_per_sec",
    **_PERCENTILE_COLUMNS,
}

# Locust writes "N/A" for a timing column on a zero-request row, otherwise a
# plain decimal string - so any given row can mix both shapes.
_timing_value = st.one_of(
    st.just("N/A"),
    st.floats(min_value=0, max_value=1_000_000, allow_nan=False, allow_infinity=False).map(str),
)


@st.composite
def _locust_stats_rows(draw: st.DrawFn) -> dict[str, str]:
    row = {
        "Type": draw(st.sampled_from(["GET", "POST", "PUT", "DELETE"])),
        "Name": draw(st.text(min_size=1, max_size=30)),
        "Request Count": str(draw(st.integers(min_value=0, max_value=1_000_000))),
        "Failure Count": str(draw(st.integers(min_value=0, max_value=1_000_000))),
    }
    for column in _TIMING_ATTR_BY_COLUMN:
        row[column] = draw(_timing_value)
    return row


@given(row=_locust_stats_rows())
def test_from_csv_row_never_raises_on_any_locust_row_shape(row: dict[str, str]) -> None:
    stats = PerfEndpointStats._from_csv_row(row)

    assert stats.method == row["Type"]
    assert stats.name == row["Name"]
    assert stats.request_count == int(row["Request Count"])
    assert stats.failure_count == int(row["Failure Count"])


@given(row=_locust_stats_rows())
def test_na_timing_columns_parse_as_zero_not_a_parse_error(row: dict[str, str]) -> None:
    stats = PerfEndpointStats._from_csv_row(row)

    for column, attr in _TIMING_ATTR_BY_COLUMN.items():
        if row[column] == "N/A":
            assert getattr(stats, attr) == 0.0


def test_from_csv_row_regression_zero_request_row_with_every_percentile_na() -> None:
    """The exact shape of the row that shipped broken: a zero-request
    endpoint, where Locust writes "N/A" for every single timing/percentile
    column rather than "0". A fixed-example regression test alongside the
    property tests above, per Hypothesis's own guidance to keep a concrete
    repro even once a property test covers the general case.
    """
    row = {"Type": "GET", "Name": "GET /untouched", "Request Count": "0", "Failure Count": "0"}
    row.update(dict.fromkeys(_TIMING_ATTR_BY_COLUMN, "N/A"))

    stats = PerfEndpointStats._from_csv_row(row)

    assert stats.request_count == 0
    assert stats.failure_ratio == 0.0
    assert all(getattr(stats, attr) == 0.0 for attr in _TIMING_ATTR_BY_COLUMN.values())


@given(data=st.data())
def test_failure_ratio_is_always_a_valid_proportion(data: st.DataObject) -> None:
    request_count = data.draw(st.integers(min_value=0, max_value=1_000_000))
    failure_count = data.draw(st.integers(min_value=0, max_value=request_count))
    stats = PerfEndpointStats(
        method="GET",
        name="GET /orders",
        request_count=request_count,
        failure_count=failure_count,
        median_ms=0,
        average_ms=0,
        min_ms=0,
        max_ms=0,
        requests_per_sec=0,
        failures_per_sec=0,
        p50_ms=0,
        p66_ms=0,
        p75_ms=0,
        p80_ms=0,
        p90_ms=0,
        p95_ms=0,
        p98_ms=0,
        p99_ms=0,
        p999_ms=0,
        p9999_ms=0,
        p100_ms=0,
    )

    assert 0.0 <= stats.failure_ratio <= 1.0
    if request_count == 0:
        assert stats.failure_ratio == 0.0
