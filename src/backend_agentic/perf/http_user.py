"""Base class for load-test ``User``s, sharing this framework's conventions
with the functional agents: default host from :mod:`backend_agentic.config`,
and a per-user correlation id stamped on every request so load-test traffic
is identifiable in application logs the same way :class:`~backend_agentic.rest.agent.RestAgent`
traffic is.

Run for real, standalone, the normal Locust way::

    locust -f tests/perf/locustfile.py --host http://localhost:8000

or headlessly as a quick in-CI perf gate via
:class:`backend_agentic.perf.agent.PerfAgent`, which drives the same
locustfile and hands back a result to assert on with assertpy2.

Requires the ``perf`` extra: ``pip install backend-agentic[perf]``.
"""

from __future__ import annotations

import uuid

try:
    from locust import HttpUser
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "backend_agentic.perf.http_user requires the 'perf' extra: pip install backend-agentic[perf]"
    ) from exc

from backend_agentic.config import get_settings


class BackendAgenticHttpUser(HttpUser):
    abstract = True
    host = get_settings().rest.base_url

    def on_start(self) -> None:
        self.correlation_id = uuid.uuid4().hex
        self.client.headers.update({"X-Correlation-Id": self.correlation_id})
