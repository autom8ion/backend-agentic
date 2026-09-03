"""Project-level test config.

The ``backend_agentic`` pytest plugin (fixtures, assertion extensions) is
auto-registered by the ``pytest11`` entry point once the package is
installed - nothing to wire up here. This file only adds one thing specific
to these example tests: skip any test that needs the demo stack (see
``docker/docker-compose.yml``) when it is not running, instead of failing
with a raw connection error.
"""

from __future__ import annotations

import httpx
import pytest

from backend_agentic.config import get_settings

_LIVE_MARKERS = {"rest", "graphql", "db", "kafka", "reconciliation", "perf", "e2e"}


@pytest.fixture(autouse=True)
def _skip_without_demo_stack(request: pytest.FixtureRequest) -> None:
    if not {m.name for m in request.node.iter_markers()} & _LIVE_MARKERS:
        return
    settings = get_settings()
    try:
        httpx.get(f"{settings.rest.base_url}/health", timeout=1.0)
    except httpx.TransportError:
        pytest.skip(
            f"demo backend is not reachable at {settings.rest.base_url} - start it with: "
            "docker compose -f docker/docker-compose.yml up -d --build"
        )
