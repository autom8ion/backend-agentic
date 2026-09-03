---
name: demo-stack
description: Bring the backend-agentic Docker demo stack (Postgres, Redpanda, and the FastAPI/GraphQL demo app) up or down, wait for it to actually be healthy, and optionally run the example test suite against it. Use when asked to start/stop/rebuild the demo stack, or to actually execute (not just collect) the tests under tests/rest, tests/graphql, tests/db, tests/kafka, tests/reconciliation, tests/perf, or tests/e2e.
---

# Running the backend-agentic demo stack

The example tests in `tests/` are integration tests, not unit tests - they
need Postgres, Redpanda, and the demo app all running and healthy. Without
that, `pytest` auto-skips them via `tests/conftest.py`'s
`_skip_without_demo_stack` fixture; a skip is not a failure and does not mean
something is broken.

## Bringing it up

1. Confirm Docker is actually usable first: `docker info`. If that fails, stop
   and tell the user Docker isn't running/installed rather than proceeding -
   every step below will fail confusingly otherwise.

2. Build and start, detached:
   ```bash
   docker compose -f docker/docker-compose.yml up -d --build
   ```

3. Make sure `.env` exists so `Settings` points at the stack's published
   ports (`localhost:8000` for REST/GraphQL, `localhost:5432` for Postgres,
   `localhost:19092` for Kafka):
   ```bash
   [ -f .env ] || cp .env.example .env
   ```

4. **Wait for real health, not just container-started.** `docker compose ps`
   shows each service's healthcheck status (all three services define one in
   `docker/docker-compose.yml`). Poll it, or poll the app directly:
   ```bash
   until curl -sf http://localhost:8000/health >/dev/null; do sleep 2; done
   ```
   Postgres and Redpanda's healthchecks gate `demo_app`'s own startup via
   `depends_on: condition: service_healthy`, so a healthy `demo_app` implies
   the other two are up - polling `/health` alone is normally sufficient. If
   it never turns healthy, check `docker compose -f docker/docker-compose.yml
   logs demo_app` (and `logs postgres` / `logs redpanda`) before assuming the
   framework itself is broken.

## Running tests against it

```bash
pytest                 # everything, now un-skipped
pytest -m rest         # one domain at a time
pytest -m "not e2e"    # skip the full cross-system scenario
pytest tests/perf/test_perf_gate.py   # the Locust-based perf gate specifically
```

## Tearing it down

```bash
docker compose -f docker/docker-compose.yml down
```

Only add `-v` (which deletes the Postgres volume, discarding all demo data)
if the user actually wants a clean slate, or asked for teardown explicitly -
treat it as the destructive option it is and don't default to it.
