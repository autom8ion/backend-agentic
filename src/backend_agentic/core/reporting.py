"""Step-level timing and logging shared by every agent.

Every agent method that talks to a real system wraps its body in
``self.step("action name")`` (see :meth:`backend_agentic.core.agent.BaseAgent.step`).
That records a :class:`Step` onto the test's :class:`~backend_agentic.core.context.TestContext`
and emits a structured log line, so a failure deep inside a scenario is
traceable both in the terminal and in the final timeline dump.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger("backend_agentic")


@dataclass
class Step:
    agent: str
    action: str
    correlation_id: str
    detail: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    duration_ms: float = 0.0
    error: str | None = None


@contextmanager
def step(
    context: Any,
    agent: str,
    action: str,
    detail: str | None = None,
) -> Iterator[Step]:
    s = Step(agent=agent, action=action, correlation_id=context.correlation_id, detail=detail)
    log = logger.bind(agent=agent, action=action, correlation_id=context.correlation_id)
    log.info("step.start", detail=detail)
    started = time.monotonic()
    try:
        yield s
    except Exception as exc:
        s.error = f"{type(exc).__name__}: {exc}"
        log.error("step.failed", error=s.error)
        raise
    else:
        log.info("step.ok")
    finally:
        s.duration_ms = (time.monotonic() - started) * 1000
        context.record(s)
