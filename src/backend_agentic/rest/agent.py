"""A thin, observable REST client.

``RestAgent`` returns plain ``httpx.Response`` objects on purpose: assertpy2's
HTTP assertions (``decoded_as_json()``, and friends) are duck-typed against
any response with ``status_code``/``headers``/body, so nothing further needs
wrapping to keep the fluent assertion chain going, e.g.::

    response = rest_agent.post("/orders", json={"sku": "A-1", "qty": 2})
    assert_that(response).has_status_code(201)
    assert_conforms(response.json(), OrderModel)

Every call is stamped with the scenario's correlation id (``X-Correlation-Id``)
so it can be traced through application logs, and idempotent ``GET``/``HEAD``
requests are retried on transient transport errors; writes are not, so a
flaky network never risks a duplicate side effect.
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend_agentic.config import RestSettings
from backend_agentic.core.agent import BaseAgent
from backend_agentic.core.context import TestContext

_IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS"}


class RestAgent(BaseAgent):
    name = "rest"

    def __init__(self, context: TestContext, settings: RestSettings) -> None:
        super().__init__(context)
        self.settings = settings
        headers = {
            "X-Correlation-Id": context.correlation_id,
            **settings.default_headers,
        }
        self.client = httpx.Client(
            base_url=settings.base_url,
            timeout=settings.timeout,
            verify=settings.verify_ssl,
            headers=headers,
        )

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        with self.step(f"{method.upper()} {url}", detail=str(kwargs.get("params") or "")):
            if method.upper() in _IDEMPOTENT_METHODS:
                return self._send_with_retry(method, url, **kwargs)
            return self.client.request(method, url, **kwargs)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.2, max=2),
        retry=retry_if_exception_type(httpx.TransportError),
    )
    def _send_with_retry(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return self.client.request(method, url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)

    def close(self) -> None:
        self.client.close()
