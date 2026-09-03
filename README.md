# backend-agentic

An agent-architecture backend testing framework built on **pytest** and
**assertpy2**, with **polars** as the data-frame engine for cross-system
reconciliation and **Locust** for load testing. It covers REST, GraphQL, SQL
databases, Kafka/event-driven scenarios, reconciling data across all of them,
and gating on performance, as one coherent set of composable agents instead
of six unrelated toolkits glued together per project.

## Why "agentic"

Each backend surface is driven by a small **agent** - `RestAgent`,
`GraphQLAgent`, `DbAgent`, `KafkaAgent`, `ReconciliationAgent`, `PerfAgent` -
that owns one client, knows how to act on it, and reports every action into a shared
[`TestContext`](src/backend_agentic/core/context.py). A scenario wires two or
more agents together against one context (create over REST, verify in the
DB, verify the Kafka event, cross-check with a GraphQL read) and gets a
single, ordered timeline back when a step fails - see
[`tests/e2e/test_order_lifecycle.py`](tests/e2e/test_order_lifecycle.py).

This is a deterministic architecture, not an LLM in the loop: every agent's
behavior is ordinary Python, so a scenario is exactly as reproducible in CI
as any other pytest test.

## Why assertpy2 + polars

- **[assertpy2](https://solganis.github.io/assertpy2/)** is a fully-typed
  fork of assertpy with the pieces backend testing actually needs built in:
  `assert_conforms()` for Pydantic contract testing, `matches_json_schema()`
  / `conforms_to_openapi()`, HTTP-response assertions that work with any
  client library, `eventually()` / `eventually_sync()` polling for eventual
  consistency, and native polars/pandas frame assertions. This framework
  leans on that instead of re-inventing jsonschema/deepdiff/retry helpers.
- **[polars](https://pola.rs/)** is the data-frame engine behind
  `ReconciliationAgent`: a REST listing, a DB table, and a Kafka topic's
  contents all become a `pl.DataFrame`, compared with one vectorized outer
  join instead of a Python nested loop - fast enough for real table sizes,
  not just toy fixtures.
- **[Locust](https://locust.io/)** is the load-testing engine behind
  `PerfAgent`: the same `User`/`@task` classes you'd write for a real,
  standalone load test also run headlessly as a quick in-CI perf gate,
  producing one `PerfResult` to assert an SLO against with assertpy2.

## Architecture

```
backend_agentic/
  core/            TestContext, BaseAgent, step-level reporting/logging
  config.py        pydantic-settings: env-driven config for every agent
  rest/            RestAgent            - httpx, correlation id, retry on GET only
  graphql/         GraphQLAgent         - GraphQL-over-HTTP, retries queries not mutations
  db/              DbAgent              - SQLAlchemy + polars.read_database(_uri)
  kafka/           KafkaAgent           - confluent-kafka, wait_for_message / consume_to_df
  reconciliation/  ReconciliationAgent  - polars-based key/tolerance diffing
  perf/            PerfAgent            - runs Locust headlessly as a subprocess, BackendAgenticHttpUser base
  assertions/      has_status_code / is_fully_reconciled / meets_slo extensions, is_uuid / is_iso_datetime matchers
  data/            a shared Faker instance + unique_id()
  plugin.py        the pytest11 plugin: fixtures + failure-timeline attachment
```

## Install

This project uses [uv](https://docs.astral.sh/uv/). `uv sync` creates
`.venv` and installs the locked dependency set (core deps + the `dev` group)
from `uv.lock`; add `--extra` per optional agent, or `--all-extras` for
everything:

```bash
uv sync                              # core framework + dev tooling (ruff, mypy, pytest-cov)
uv sync --extra db --extra kafka --extra perf   # + DB, Kafka and Locust perf-testing agents
uv sync --all-extras                 # everything, including testcontainers + allure-pytest
uv run pytest                        # run anything through the project's venv, no activation needed
```

Plain `pip` still works if you'd rather not use uv - `pip install -e ".[db,kafka,perf]"`
against your own venv - it just won't use the lockfile.

`confluent-kafka` needs `librdkafka` on the host (`brew install librdkafka` /
`apt-get install librdkafka-dev`) - or just run tests against the Dockerized
demo stack below, where that's already handled in the image.

## Quickstart

Once installed, every fixture and the custom assertions are available in any
test with zero `conftest.py` wiring - the plugin registers via the
`pytest11` entry point.

```python
import pytest
from assertpy2 import assert_conforms, assert_that
from myapp.contracts import Order

pytestmark = pytest.mark.rest

def test_create_order(rest_agent):
    response = rest_agent.post("/orders", json={"sku": "A-1", "qty": 2})

    assert_that(response).has_status_code(201)
    order = assert_conforms(response.json(), Order).value
    assert_that(order.qty).is_equal_to(2)
```

Configure targets via environment variables (see `.env.example`):

```bash
cp .env.example .env
# edit .env, then:
uv run pytest -m rest
```

### Available fixtures

| Fixture         | Type                   | Needs extra |
|-----------------|------------------------|-------------|
| `settings`      | `Settings`             | -           |
| `test_context`  | `TestContext`          | -           |
| `rest_agent`    | `RestAgent`            | -           |
| `graphql_agent` | `GraphQLAgent`         | -           |
| `db_agent`      | `DbAgent`              | `db`        |
| `kafka_agent`   | `KafkaAgent`           | `kafka`     |
| `recon_agent`   | `ReconciliationAgent`  | -           |
| `perf_agent`    | `PerfAgent`            | `perf`      |

A fixture for an uninstalled extra raises a clear error the moment a test
actually requests it (`db_agent`/`kafka_agent` at import time, `perf_agent`
via the `locust` subprocess's own stderr) - collection never fails just
because `kafka`, `db` or `perf` isn't installed.

### Cross-system scenarios read like a story

```python
def test_order_lifecycle(test_context, rest_agent, db_agent, kafka_agent, graphql_agent):
    order = assert_conforms(rest_agent.post("/orders", json={...}).json(), Order).value

    row = (
        assert_that(lambda: db_agent.query_one("SELECT * FROM orders WHERE id = :id", {"id": order.id}))
        .eventually_sync().within(5).is_not_none().val
    )

    event = kafka_agent.wait_for_message("orders", predicate=lambda m: m.value["order"]["id"] == order.id)

    gql = graphql_agent.query(ORDER_QUERY, {"id": order.id}).data["order"]
```

If any step fails, the plugin attaches the full `test_context.timeline()` -
every agent's actions in call order, each stamped with the same
`correlation_id` - to the pytest failure report (and to Allure, if
installed).

### Data reconciliation

```python
from backend_agentic.reconciliation import loaders
from assertpy2 import assert_that

db_orders   = loaders.from_db(db_agent, "SELECT id, sku, amount FROM orders")
rest_orders = loaders.from_rest(rest_agent.get("/orders"))

result = recon_agent.compare(
    db_orders, rest_orders,
    keys=["id"],
    tolerance={"amount": 0.01},          # numeric columns: within tolerance is a match
    case_insensitive_columns=["status"],  # string columns: compared case-insensitively
    ignore_columns=["created_at"],        # dropped before comparing
)

assert_that(result).is_fully_reconciled()
# on failure, result.summary() names exactly which ids are missing on which
# side and which columns differ, with a sample of each
```

`loaders` also has `from_kafka(kafka_agent, topic)` and `from_csv(path)`, and
`recon_agent.compare()` is just `reconciliation.reconcile()` under the hood
if you'd rather call it without an agent/context.

### Test isolation for DB fixtures

```python
def test_something(db_agent):
    with db_agent.rollback_after() as conn:
        conn.execute(text("INSERT INTO orders (...) VALUES (...)"), {...})
        ...  # run the scenario against that row
    # rolled back on exit - nothing left behind
```

### Performance gates

`PerfAgent` runs an ordinary Locust locustfile headlessly - in a subprocess,
so Locust's gevent monkey-patching never touches the same process as httpx/
SQLAlchemy/confluent-kafka - and hands back a `PerfResult` to assert on:

```python
# tests/perf/locustfile.py
from locust import task, between
from backend_agentic.perf.http_user import BackendAgenticHttpUser

class OrderUser(BackendAgenticHttpUser):
    wait_time = between(0.1, 0.5)

    @task
    def list_orders(self):
        self.client.get("/orders", name="GET /orders")
```

```python
# a pytest perf gate, using the same locustfile
def test_orders_api_meets_its_latency_and_error_budget(perf_agent):
    result = perf_agent.run("tests/perf/locustfile.py", users=10, spawn_rate=10, run_time="10s")

    assert_that(result).meets_slo(max_failure_ratio=0.01, max_p95_ms=500)
    # or per-endpoint: meets_slo(endpoint="GET /orders", max_p95_ms=200)
    # or inspect directly: result.endpoint("GET /orders").p99_ms, result.summary()
```

The same locustfile also runs as a *real* load test, unmodified, the normal
Locust way - with the web UI, distributed workers, a long soak run:

```bash
locust -f tests/perf/locustfile.py --host http://localhost:8000
```

`BackendAgenticHttpUser` just supplies a default host (from `Settings`) and
stamps a correlation id on every request, the same convention `RestAgent`
uses - it adds nothing Locust-specific of its own.

## The demo stack

`docker/` contains a small FastAPI + Strawberry GraphQL + Postgres + Redpanda
(Kafka-API-compatible) app that the example tests in `tests/` run against, so
the whole framework is demonstrable end to end:

```bash
docker compose -f docker/docker-compose.yml up -d --build
cp .env.example .env
uv run pytest                      # everything
uv run pytest -m rest              # just REST
uv run pytest -m "not e2e"         # skip the full cross-system scenario
```

Tests marked `rest`/`graphql`/`db`/`kafka`/`reconciliation`/`perf`/`e2e` are
auto-skipped (see `tests/conftest.py`) with a clear message if the stack
isn't reachable, instead of failing with a raw connection error.

## Design notes worth knowing before extending this

- **Writes are never auto-retried.** `RestAgent` only retries idempotent
  `GET`/`HEAD`/`OPTIONS` on a transport error; `GraphQLAgent.mutate()` is
  never retried, `query()` is. A retried `POST`/mutation on a timeout could
  double-create data - not worth the convenience.
- **Kafka consumers get a unique, per-call consumer group** (stamped with
  the scenario's `correlation_id`), reading from the earliest offset by
  default. Parallel tests never share offsets or steal each other's
  messages.
- **`query_df` binds parameters through SQLAlchemy, never string-formats
  them into SQL** - the `connectorx`-backed fast path (`polars.read_database_uri`)
  is only used for parameter-free queries.
- **Reconciliation is one vectorized outer join**, not a Python loop per row
  - `ReconciliationResult.mismatches` is a long-format frame (one row per
    differing column) so a diff report doesn't hide which fields actually
    disagree.
- **`PerfAgent` shells out to `python -m locust`** rather than importing
  Locust into the test process. Locust needs gevent's monkey-patching to run
  correctly, and doing that in the same process as httpx/SQLAlchemy/
  confluent-kafka is exactly the kind of conflict not worth risking. A run
  where requests fail under load isn't an error from `PerfAgent`'s
  perspective - it still returns a full `PerfResult` with a non-zero failure
  ratio, for `meets_slo()` to catch; only a locustfile that couldn't run at
  all (bad path, syntax error) raises `PerfRunError`.

## Development

```bash
uv sync                              # installs the dev group (ruff, mypy, pytest-cov) by default
uv run ruff check src tests
uv run mypy src
uv run pytest --collect-only         # sanity-check fixture wiring without any live services
uv lock                              # after changing dependencies in pyproject.toml
```
