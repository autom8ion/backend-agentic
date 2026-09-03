# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An agent-architecture backend testing framework: a pytest plugin (`backend_agentic`)
that provides one small **agent** class per backend surface (REST, GraphQL, SQL DB,
Kafka, cross-system reconciliation, Locust-based perf gates), all reporting into a
shared `TestContext` so a multi-system scenario gets one readable timeline when it
fails. See `README.md` for the full user-facing API and design rationale — this file
covers what a Claude session needs to work *on* the framework itself.

## Commands

This project uses [uv](https://docs.astral.sh/uv/) - `pyproject.toml` +
`uv.lock` + `.python-version` (pinned to 3.12) are the source of truth for
dependencies and the interpreter. `uv sync` creates/updates `.venv`
automatically; there's no separate manual venv-creation step.

```bash
uv sync                              # core deps + the `dev` group (ruff, mypy, pytest-cov)
uv sync --extra db --extra kafka --extra perf   # + DB, Kafka, Locust perf agents
uv sync --all-extras                 # everything, including testcontainers + allure-pytest
```

`confluent-kafka` (the `kafka` extra) needs `librdkafka` on the host
(`brew install librdkafka` / `apt-get install librdkafka-dev`) to build.

On a Mac where the resolved Python turns out to be x86_64 running under
Rosetta (check with `uv run python -c "import platform; print(platform.machine())"`
- should print `arm64` on Apple Silicon), `uv`'s wheel resolution still
correctly fetches arm64 wheels for C-extension deps (gevent, connectorx,
confluent-kafka, ...), which then fail to import against an x86_64
interpreter. Fix it at the interpreter, not with `POLARS_SKIP_CPU_CHECK`:
`uv python install cpython-3.12-macos-aarch64-none`, confirm it matches
`.python-version`, then `rm -rf .venv && uv sync` again.

Run tests, via `uv run` so they use the project's own venv without activating it:

```bash
uv run pytest --collect-only          # sanity-check fixture wiring; must pass with ANY subset of extras installed
uv run pytest                         # everything; tests needing the demo stack auto-skip if it's not up
uv run pytest tests/db/test_orders_db.py::test_created_order_is_persisted   # a single test
uv run pytest -m rest                 # by marker: rest/graphql/db/kafka/reconciliation/perf/e2e
uv run pytest -m "not e2e"
```

The example tests in `tests/` are integration tests against the Dockerized demo app,
not unit tests of the framework's own logic — there is currently no unit-test suite
for `reconcile()`, the `PerfAgent` CSV parsing, or the assertpy2 extensions/matchers
in isolation. (This is not hypothetical: the `PerfAgent` CSV parser shipped with a
bug - it didn't handle Locust's `N/A` percentile value on a zero-request row - that
only surfaced by actually running it, because nothing exercised that code path in
isolation. Prefer a real run over trusting new agent code compiles.) Bring up the
demo stack before running the integration tests for real:

```bash
docker compose -f docker/docker-compose.yml up -d --build
cp .env.example .env
```

Lint / type-check:

```bash
uv run ruff check src tests
uv run mypy src
```

After changing dependencies in `pyproject.toml`, run `uv lock` and commit the
updated `uv.lock`.

## Architecture

**The agent pattern.** Every domain module (`rest/`, `graphql/`, `db/`, `kafka/`,
`reconciliation/`, `perf/`) has one `agent.py` defining a class that subclasses
`core.agent.BaseAgent`. An agent owns exactly one client/connection, and every method
that does real work wraps its body in `self.step("action name")`
(`core/reporting.py`), which times it, logs it via structlog, and records a `Step`
onto the test's `core.context.TestContext`. `TestContext.timeline()` renders that as
one ordered log across every agent used in a test — the `plugin.py`
`pytest_runtest_makereport` hook attaches it to a failing test's report (and to
Allure, if installed) automatically. Extending the framework with a new domain agent
means following this same shape: `BaseAgent` subclass, `self.step(...)` around each
real action, a fixture in `plugin.py` that constructs it from `TestContext` + a slice
of `Settings`, and (if it can fail with a domain-specific error) an entry in
`core/exceptions.py`.

**Config.** `config.py` is pydantic-settings, `BACKEND_AGENTIC__<SECTION>__<FIELD>`
env vars (double underscore is both the prefix separator and the nesting delimiter,
including into dict fields like `db.connections`). `.env.example` documents every
variable the demo stack needs. `get_settings()` is `lru_cache`d — one process, one
`Settings` instance.

**Optional extras load lazily, on purpose.** `db` and `kafka` extras are not imported
anywhere at package/plugin top-level; `plugin.py`'s `db_agent`/`kafka_agent` fixtures
import `DbAgent`/`KafkaAgent` inside the fixture body, and those modules raise a
clear `ImportError` at import time if `sqlalchemy`/`confluent-kafka` isn't installed.
This is why `pytest --collect-only` must keep working regardless of which extras are
installed — collection never touches those imports, only actually *requesting* the
fixture does. `perf/agent.py` is a special case: it has no import-time dependency on
`locust` at all, because `PerfAgent.run()` shells out to `python -m locust` as a
subprocess rather than importing it (see below); only `perf/http_user.py`, used by
locustfiles themselves and never imported by the plugin, needs `locust` installed.
Keep new agents following this same lazy-import shape.

**`ReconciliationAgent` (`reconciliation/agent.py`)** is one vectorized polars outer
join (`how="full"`, `coalesce=True`), not a per-row Python loop: two `__in_left`/
`__in_right` indicator columns (rather than trusting nulls, which can be legitimate
data) classify rows into `only_in_left`/`only_in_right`/matched-or-mismatched, then
per-column match expressions (exact / tolerance / case-insensitive, per the columns
passed in) split the rest into `matched` vs a long-format `mismatches` frame (one row
per *differing column*, not per differing row) so a diff report never hides which
field actually disagreed. `loaders.py` intentionally takes already-constructed
agents/responses as arguments rather than importing `DbAgent`/`KafkaAgent` itself, so
using `from_rest`/`from_records`/`from_csv` never pulls in the `db`/`kafka` extras.

**`PerfAgent` (`perf/agent.py`)** shells out to `python -m locust --headless --csv
<tmpdir>` and parses `<prefix>_stats.csv`/`_failures.csv` rather than importing
Locust into the test process — Locust needs gevent's monkey-patching, which would
conflict with httpx/SQLAlchemy/confluent-kafka in the same process. The presence of
the stats CSV file (not the subprocess exit code — a broken locustfile and a run
with failed requests can both exit 1) is what distinguishes "the run itself failed to
execute" (raises `PerfRunError`) from "the run executed and some requests failed"
(returns a normal `PerfResult` with a non-zero failure ratio, for `meets_slo()` to
catch). `perf/http_user.py`'s `BackendAgenticHttpUser` is the shared base for
locustfiles run either way — headlessly through `PerfAgent`, or standalone via
`locust -f ... --host ...` for a real load test.

**Custom assertpy2 extensions/matchers (`assertions/`)** are registered once by
`plugin.py`'s `pytest_configure` calling `extensions.register_all()` — never
per-test. `has_status_code`/`is_fully_reconciled`/`meets_slo` are `add_extension()`
functions (assertpy2 methods, read `self.val`, fail via `self.error()`); `is_uuid`/
`is_iso_datetime` are `BaseMatcher` subclasses in `matchers.py` instead, because
assertpy2's `register_matcher()` decorates a factory composing its own built-in
`match.*` primitives, not an arbitrary predicate — writing a `BaseMatcher` subclass
was the documented way to plug in one directly.

**The demo stack (`docker/`)** is a FastAPI + Strawberry GraphQL + SQLAlchemy +
confluent-kafka app backed by Postgres and Redpanda, existing purely so the example
tests in `tests/` have something real to run against end to end. `app/service.py`
holds the one shared `create_order`/`get_order`/`list_orders` implementation that
both the REST routes (`app/main.py`) and the GraphQL resolvers
(`app/graphql_schema.py`) call, so the two APIs can't drift into different behavior.
`tests/conftest.py`'s `_skip_without_demo_stack` fixture auto-skips any test marked
`rest`/`graphql`/`db`/`kafka`/`reconciliation`/`perf`/`e2e` with a clear message if
`GET {rest.base_url}/health` isn't reachable, instead of failing with a raw
connection error — keep new example tests marked accordingly.
