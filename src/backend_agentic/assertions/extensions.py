"""Domain-specific assertpy2 extensions and matchers for backend testing.

Registered once, at pytest session start, by the ``backend_agentic`` pytest
plugin (see ``plugin.py``) - no per-test fixture needed. See assertpy2's own
`extending guide <https://solganis.github.io/assertpy2/extending/custom-assertions/>`_
for the conventions these follow (read ``self.val``, fail via ``self.error()``,
always ``return self``).
"""

from __future__ import annotations

from assertpy2 import add_extension

from backend_agentic.perf.agent import PerfResult
from backend_agentic.reconciliation.agent import ReconciliationResult

_registered = False


def has_status_code(self, *expected: int):  # noqa: ANN001 - assertpy2 extension convention
    """``assert_that(response).has_status_code(200, 201)``"""
    response = self.val
    if not hasattr(response, "status_code"):
        raise TypeError(
            f"val must be an HTTP response with a status_code, but was <{response!r}> "
            f"({type(response).__name__})"
        )
    if response.status_code not in expected:
        preview = str(getattr(response, "text", ""))[:500]
        return self.error(
            f"Expected status code in {expected}, but was <{response.status_code}>. Body: {preview}"
        )
    return self


def is_fully_reconciled(self):  # noqa: ANN001
    """``assert_that(reconciliation_result).is_fully_reconciled()``"""
    result = self.val
    if not isinstance(result, ReconciliationResult):
        raise TypeError(f"val must be a ReconciliationResult, but was <{type(result).__name__}>")
    if not result.is_reconciled:
        return self.error(f"Expected the datasets to be fully reconciled, but they were not.\n{result.summary()}")
    return self


def meets_slo(self, *, max_failure_ratio: float | None = None, max_p95_ms: float | None = None, endpoint: str | None = None):  # noqa: ANN001
    """``assert_that(perf_result).meets_slo(max_failure_ratio=0.01, max_p95_ms=300)``

    Checks the aggregate stats by default; pass ``endpoint`` (as named in the
    locustfile's ``name=`` kwarg) to gate on one endpoint instead.
    """
    result = self.val
    if not isinstance(result, PerfResult):
        raise TypeError(f"val must be a PerfResult, but was <{type(result).__name__}>")
    stats = result.endpoint(endpoint) if endpoint else result.aggregate
    violations = []
    if max_failure_ratio is not None and stats.failure_ratio > max_failure_ratio:
        violations.append(f"failure ratio {stats.failure_ratio:.2%} exceeds {max_failure_ratio:.2%}")
    if max_p95_ms is not None and stats.p95_ms > max_p95_ms:
        violations.append(f"p95 {stats.p95_ms:.1f}ms exceeds {max_p95_ms}ms")
    if violations:
        subject = endpoint or "aggregate"
        return self.error(f"Perf SLO violated for {subject}: {'; '.join(violations)}\n{result.summary()}")
    return self


def register_all() -> None:
    """Register the ``add_extension`` assertions. See ``matchers.py`` for
    ``is_uuid()`` / ``is_iso_datetime()``, which need no registration."""
    global _registered
    if _registered:
        return
    add_extension(has_status_code)
    add_extension(is_fully_reconciled)
    add_extension(meets_slo)
    _registered = True
