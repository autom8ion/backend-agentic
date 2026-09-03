"""The shared state a scenario's agents pass work through.

A single :class:`TestContext` is created per test by the ``test_context``
fixture and handed to every agent fixture (``rest_agent``, ``db_agent``,
``kafka_agent``, ...). Agents record every action they take into it, so a
scenario that touches five systems still has one linear timeline to read
when something fails - see ``plugin.py`` for how that timeline gets printed.

It also doubles as scratch space for correlating a scenario end to end: the
REST agent stamps every outgoing request with ``context.correlation_id``, and
a test can stash the ids it creates in ``context.data`` for later steps to
pick up.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from backend_agentic.core.reporting import Step


@dataclass
class TestContext:
    test_name: str
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    steps: list[Step] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def record(self, step: Step) -> None:
        self.steps.append(step)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def failed_steps(self) -> list[Step]:
        return [s for s in self.steps if s.error is not None]

    def timeline(self) -> str:
        """Render the recorded steps as a human-readable timeline."""
        lines = [f"Timeline for {self.test_name!r} (correlation_id={self.correlation_id}):"]
        for i, s in enumerate(self.steps, start=1):
            marker = "FAIL" if s.error else "ok"
            lines.append(
                f"  {i:>2}. [{marker:<4}] {s.agent:<10} {s.action:<24} "
                f"({s.duration_ms:.1f}ms) {s.detail or ''}"
            )
            if s.error:
                lines.append(f"        -> {s.error}")
        return "\n".join(lines)
