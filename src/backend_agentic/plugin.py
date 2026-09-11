"""The pytest plugin: registers fixtures for every agent plus the custom
assertpy2 extensions, and attaches a scenario's timeline to a failed test's
report.

Installing the package registers this automatically via the ``pytest11``
entry point in ``pyproject.toml`` - no ``conftest.py`` wiring required. A
project only needs its own ``conftest.py`` to override a fixture (a
different ``settings`` source, a session-scoped ``db_agent``, ...).
"""

from __future__ import annotations

from collections.abc import Generator, Iterator

import pluggy
import pytest

from backend_agentic.assertions.extensions import register_all
from backend_agentic.config import Settings, get_settings
from backend_agentic.core.context import TestContext
from backend_agentic.graphql.agent import GraphQLAgent
from backend_agentic.perf.agent import PerfAgent
from backend_agentic.reconciliation.agent import ReconciliationAgent
from backend_agentic.rest.agent import RestAgent


def pytest_configure(config: pytest.Config) -> None:
    register_all()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pluggy.Result[pytest.TestReport], None]:
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    context = item.funcargs.get("test_context") if hasattr(item, "funcargs") else None
    if not isinstance(context, TestContext) or not context.steps:
        return
    timeline = context.timeline()
    report.sections.append(("backend-agentic timeline", timeline))
    try:
        import allure

        allure.attach(timeline, name="backend-agentic timeline", attachment_type=allure.attachment_type.TEXT)
    except ImportError:
        pass


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    try:
        from backend_agentic.db.agent import dispose_all_engines

        dispose_all_engines()
    except ImportError:
        pass


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def test_context(request: pytest.FixtureRequest) -> Iterator[TestContext]:
    yield TestContext(test_name=request.node.nodeid)


@pytest.fixture
def rest_agent(test_context: TestContext, settings: Settings) -> Iterator[RestAgent]:
    agent = RestAgent(test_context, settings.rest)
    yield agent
    agent.close()


@pytest.fixture
def graphql_agent(test_context: TestContext, settings: Settings) -> Iterator[GraphQLAgent]:
    agent = GraphQLAgent(test_context, settings.graphql)
    yield agent
    agent.close()


@pytest.fixture
def db_agent(test_context: TestContext, settings: Settings) -> Iterator[object]:
    from backend_agentic.db.agent import DbAgent

    agent = DbAgent(test_context, settings.db)
    yield agent
    agent.close()


@pytest.fixture
def kafka_agent(test_context: TestContext, settings: Settings) -> Iterator[object]:
    from backend_agentic.kafka.agent import KafkaAgent

    agent = KafkaAgent(test_context, settings.kafka)
    yield agent
    agent.close()


@pytest.fixture
def recon_agent(test_context: TestContext) -> Iterator[ReconciliationAgent]:
    yield ReconciliationAgent(test_context)


@pytest.fixture
def perf_agent(test_context: TestContext, settings: Settings) -> Iterator[PerfAgent]:
    yield PerfAgent(test_context, settings.rest)
