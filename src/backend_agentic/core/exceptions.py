class BackendAgenticError(Exception):
    """Base class for every error this framework raises directly."""


class GraphQLResponseError(BackendAgenticError):
    """The GraphQL server responded with a top-level ``errors`` array."""

    def __init__(self, errors: list[dict], data: object | None = None) -> None:
        self.errors = errors
        self.data = data
        super().__init__(f"GraphQL request returned {len(errors)} error(s): {errors}")


class KafkaWaitTimeoutError(BackendAgenticError):
    """No message matching the predicate arrived within the deadline."""

    def __init__(self, topic: str, timeout: float, seen: list[object]) -> None:
        self.topic = topic
        self.timeout = timeout
        self.seen = seen
        preview = seen[-5:]
        super().__init__(
            f"No message on topic {topic!r} matched the predicate within {timeout}s. "
            f"Saw {len(seen)} message(s); last {len(preview)}: {preview}"
        )


class ReconciliationSourceError(BackendAgenticError):
    """A reconciliation data source could not be loaded into a DataFrame."""


class PerfRunError(BackendAgenticError):
    """The Locust subprocess did not produce stats - a broken locustfile or bad args, not a load-test failure.

    A run where requests failed under load is not this: it still produces
    stats, so it comes back as a :class:`~backend_agentic.perf.agent.PerfResult`
    with a non-zero failure ratio instead, for the test to assert on.
    """
