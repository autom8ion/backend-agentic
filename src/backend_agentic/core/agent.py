"""The base class every domain agent (REST, GraphQL, DB, Kafka, reconciliation) extends.

An "agent" here is deliberately unglamorous: it is whatever object owns one
backend surface's client (an ``httpx.Client``, a SQLAlchemy engine, a Kafka
producer/consumer pair), knows how to talk to it, and reports every action it
takes into the shared :class:`~backend_agentic.core.context.TestContext`. The
autonomy is in composition, not magic: a test wires two or more agents
together against one context to run a scenario end to end (create over REST,
verify in the DB, verify the Kafka event, reconcile the two) and gets a single
readable timeline out of it when a step fails.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import structlog

from backend_agentic.core.context import TestContext
from backend_agentic.core.reporting import Step, step


class BaseAgent:
    name: str = "agent"

    def __init__(self, context: TestContext) -> None:
        self.context = context
        self.log = structlog.get_logger(self.name).bind(
            agent=self.name, correlation_id=context.correlation_id
        )

    @contextmanager
    def step(self, action: str, detail: str | None = None) -> Iterator[Step]:
        with step(self.context, self.name, action, detail=detail) as s:
            yield s

    def close(self) -> None:
        """Release any underlying client/connection. Override where relevant."""
