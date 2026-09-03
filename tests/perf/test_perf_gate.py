"""A perf gate: a short headless Locust run against the demo app, asserted
against an SLO with the same assertpy2 chain as every other agent's result.

This is deliberately brief (10s, 10 users) - a CI smoke check that the order
API hasn't regressed on latency or error rate, not a substitute for a real
load test. For that, run tests/perf/locustfile.py standalone with the
Locust web UI or a longer headless run.
"""

from pathlib import Path

import pytest
from assertpy2 import assert_that

pytestmark = [pytest.mark.perf, pytest.mark.rest]

LOCUSTFILE = Path(__file__).parent / "locustfile.py"


def test_orders_api_meets_its_latency_and_error_budget(perf_agent):
    result = perf_agent.run(LOCUSTFILE, users=10, spawn_rate=10, run_time="10s")

    print(result.summary())
    assert_that(result).meets_slo(max_failure_ratio=0.01, max_p95_ms=500)
