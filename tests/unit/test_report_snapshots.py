"""Snapshot tests (via syrupy) for the framework's human-readable report
formats: ``TestContext.timeline()``, ``PerfResult.summary()``, and
``ReconciliationResult.summary()``. These strings are what a failing test
actually shows a developer (the timeline gets attached to every failure
report - see ``plugin.py``), so their *formatting* is worth locking down the
same way an API response shape is: a snapshot test fails the moment someone
reorders a field or breaks column alignment, even though no assertion in the
example integration tests would ever notice that kind of regression.

Every fixture below is built directly (fixed ``Step``s, a fixed
``correlation_id``, static DataFrames) rather than driven through a real
agent, so the snapshot never flakes on timing or generated ids.

After a deliberate, reviewed formatting change, regenerate the committed
snapshots in ``tests/unit/__snapshots__/``::

    uv run pytest tests/unit/test_report_snapshots.py --snapshot-update
"""

from __future__ import annotations

import polars as pl
import pytest
from syrupy.assertion import SnapshotAssertion

from backend_agentic.core.context import TestContext
from backend_agentic.core.reporting import Step
from backend_agentic.perf.agent import PerfEndpointStats, PerfResult
from backend_agentic.reconciliation.agent import reconcile

pytestmark = pytest.mark.unit


def _endpoint(name: str, *, request_count: int, failure_count: int, p95_ms: float) -> PerfEndpointStats:
    return PerfEndpointStats(
        method="GET",
        name=name,
        request_count=request_count,
        failure_count=failure_count,
        median_ms=10.0,
        average_ms=12.0,
        min_ms=5.0,
        max_ms=40.0,
        requests_per_sec=5.0,
        failures_per_sec=0.1,
        p50_ms=10.0,
        p66_ms=11.0,
        p75_ms=12.0,
        p80_ms=13.0,
        p90_ms=15.0,
        p95_ms=p95_ms,
        p98_ms=18.0,
        p99_ms=20.0,
        p999_ms=22.0,
        p9999_ms=25.0,
        p100_ms=30.0,
    )


def test_timeline_snapshot(snapshot: SnapshotAssertion) -> None:
    context = TestContext(test_name="test_example_scenario", correlation_id="fixed-correlation-id")
    context.record(
        Step(
            agent="rest",
            action="post",
            correlation_id=context.correlation_id,
            detail="POST /orders",
            duration_ms=12.345,
        )
    )
    context.record(
        Step(
            agent="db",
            action="query_one",
            correlation_id=context.correlation_id,
            detail="SELECT * FROM orders WHERE id = :id",
            duration_ms=3.2,
        )
    )
    context.record(
        Step(
            agent="kafka",
            action="wait_for_message",
            correlation_id=context.correlation_id,
            detail="topic=orders.events timeout=5.0s",
            duration_ms=5004.1,
            error="KafkaWaitTimeoutError: No message on topic 'orders.events' matched the predicate within 5.0s",
        )
    )

    assert context.timeline() == snapshot


def test_perf_result_summary_snapshot(snapshot: SnapshotAssertion) -> None:
    result = PerfResult(
        endpoints=[
            _endpoint("GET /orders", request_count=100, failure_count=2, p95_ms=180.0),
            _endpoint("POST /orders", request_count=50, failure_count=0, p95_ms=90.0),
        ],
        aggregate=_endpoint("Aggregated", request_count=150, failure_count=2, p95_ms=160.0),
        failures=[{"method": "GET", "name": "GET /orders", "error": "ConnectionRefusedError"}],
        returncode=0,
        stdout="",
    )

    assert result.summary() == snapshot


def test_reconciliation_summary_snapshot(snapshot: SnapshotAssertion) -> None:
    left = pl.DataFrame({"id": [1, 2, 3], "amount": [10.0, 20.0, 30.0]})
    right = pl.DataFrame({"id": [2, 3, 4], "amount": [20.0, 99.0, 40.0]})

    result = reconcile(left, right, keys=["id"])

    assert result.summary() == snapshot
