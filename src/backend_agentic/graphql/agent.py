"""A minimal GraphQL-over-HTTP client.

Deliberately built on plain ``httpx`` rather than a schema-aware GraphQL
client: query/mutation-over-POST is a thin enough protocol that a full client
library buys little for testing, and it keeps this agent dependency-light and
transport-consistent with :class:`~backend_agentic.rest.agent.RestAgent`
(same correlation header, same retry policy for queries).

``execute()`` returns a :class:`GraphQLResult` carrying both the raw
``httpx.Response`` (for status/header assertions, or ``assert_that(response)``
HTTP assertions) and the parsed ``data``/``errors`` payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend_agentic.config import GraphQLSettings
from backend_agentic.core.agent import BaseAgent
from backend_agentic.core.context import TestContext
from backend_agentic.core.exceptions import GraphQLResponseError


@dataclass
class GraphQLResult:
    response: httpx.Response
    data: Any
    errors: list[dict[str, object]] | None

    def raise_for_errors(self) -> GraphQLResult:
        if self.errors:
            raise GraphQLResponseError(self.errors, self.data)
        return self


class GraphQLAgent(BaseAgent):
    name = "graphql"

    def __init__(self, context: TestContext, settings: GraphQLSettings) -> None:
        super().__init__(context)
        self.settings = settings
        self.client = httpx.Client(
            timeout=settings.timeout,
            headers={
                "X-Correlation-Id": context.correlation_id,
                "Content-Type": "application/json",
                **settings.default_headers,
            },
        )

    def execute(
        self,
        document: str,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
        *,
        raise_on_error: bool = True,
        idempotent: bool = True,
    ) -> GraphQLResult:
        payload: dict[str, Any] = {"query": document}
        if variables is not None:
            payload["variables"] = variables
        if operation_name is not None:
            payload["operationName"] = operation_name

        with self.step("execute", detail=operation_name or document.split("{")[0].strip()):
            response = self._post_with_retry(payload) if idempotent else self.client.post(
                self.settings.endpoint, json=payload
            )
            body = response.json()
            result = GraphQLResult(response=response, data=body.get("data"), errors=body.get("errors"))
            if raise_on_error:
                result.raise_for_errors()
            return result

    def query(self, document: str, variables: dict[str, Any] | None = None, **kwargs: Any) -> GraphQLResult:
        """Run a query. Safe to retry on a transport error, so it is by default."""
        kwargs.setdefault("idempotent", True)
        return self.execute(document, variables, **kwargs)

    def mutate(self, document: str, variables: dict[str, Any] | None = None, **kwargs: Any) -> GraphQLResult:
        """Run a mutation. Never retried automatically, to avoid a duplicate side effect."""
        kwargs.setdefault("idempotent", False)
        return self.execute(document, variables, **kwargs)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.2, max=2),
        retry=retry_if_exception_type(httpx.TransportError),
    )
    def _post_with_retry(self, payload: dict[str, Any]) -> httpx.Response:
        return self.client.post(self.settings.endpoint, json=payload)

    def close(self) -> None:
        self.client.close()
