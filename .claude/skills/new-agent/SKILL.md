---
name: new-agent
description: Scaffold a new domain agent for the backend-agentic framework (a BaseAgent subclass, its pytest fixture, config/exceptions if needed, and an example test), following the exact pattern used by RestAgent/DbAgent/KafkaAgent/etc. Use when asked to add support for a new backend surface or protocol (gRPC, SQS, a message queue, a cache, ...) to this framework.
---

# Scaffolding a new backend-agentic agent

Every domain in this framework follows the same shape (see `CLAUDE.md` for the
full rationale). Reproduce it exactly rather than improvising a new one - the
value of this framework is that every agent behaves the same way.

Before writing anything, confirm with the user (or infer from context): the
domain name (lowercase, e.g. `grpc`, `sqs`), what its core operations are, and
whether it needs a third-party client library that should be an optional extra.

## Steps

1. **Create the module**: `src/backend_agentic/<domain>/__init__.py` (re-exports
   the agent class) and `src/backend_agentic/<domain>/agent.py`.

2. **Write the agent class**, subclassing `backend_agentic.core.agent.BaseAgent`:
   - `name = "<domain>"` class attribute.
   - `__init__(self, context: TestContext, settings: <Domain>Settings) -> None` if
     it needs config (most do); otherwise just `(self, context: TestContext)`
     like `ReconciliationAgent`.
   - Wrap **every** method that does real I/O in `with self.step("action_name", detail=...):`
     - this is what populates `TestContext.timeline()` and the failure-report
     attachment. Look at `rest/agent.py` or `db/agent.py` for the shape.
   - If a method is idempotent (a read), it's fine to retry on a transport
     error with `tenacity`, matching `RestAgent`/`GraphQLAgent`. Never
     auto-retry a write/mutation - see the "Writes are never auto-retried"
     note in `README.md` for why.
   - Add a `close()` method that releases the underlying client/connection.

3. **If the agent needs an optional third-party dependency**, guard the import
   at the top of `agent.py`:
   ```python
   try:
       import the_dependency
   except ImportError as exc:
       raise ImportError(
           "XAgent requires the '<domain>' extra: pip install backend-agentic[<domain>]"
       ) from exc
   ```
   This is what lets `uv run pytest --collect-only` keep working when the
   extra isn't synced in - the import only happens when the fixture is
   actually requested, never at plugin/package load time. Do **not** import the new agent module
   at the top of `plugin.py` if it has an optional dependency; import it
   lazily inside the fixture body instead (see `db_agent`/`kafka_agent` in
   `plugin.py` for the pattern; `recon_agent`/`perf_agent` show the
   dependency-free version).

4. **If it needs config**, add a `<Domain>Settings(BaseModel)` to `config.py`
   and a field for it on `Settings`.

5. **If it has a domain-specific failure mode**, add an exception to
   `core/exceptions.py` subclassing `BackendAgenticError`, following the
   docstring style already there (state what triggers it and, if relevant,
   what does *not* - see `PerfRunError`'s docstring for why that distinction
   matters).

6. **Register the fixture** in `plugin.py`, function-scoped, yielding the
   agent and calling `.close()` after:
   ```python
   @pytest.fixture
   def <domain>_agent(test_context: TestContext, settings: Settings) -> Iterator[<Domain>Agent]:
       from backend_agentic.<domain>.agent import <Domain>Agent  # only if optional dep
       agent = <Domain>Agent(test_context, settings.<domain>)
       yield agent
       agent.close()
   ```

7. **If the dependency is optional**, add an extras group to `pyproject.toml`'s
   `[project.optional-dependencies]` and append it to the `all` group.

8. **Add a pytest marker** for the domain in `pyproject.toml`'s `markers` list.
   If tests for it need the Docker demo stack, add the marker name to
   `_LIVE_MARKERS` in `tests/conftest.py` too.

9. **Write one example test** under `tests/<domain>/test_*.py`, marked with the
   new marker (and `rest` if it also exercises the demo app's REST API to set
   up state), using `assertpy2`'s `assert_that`/`assert_conforms` the way the
   existing example tests do - don't reach for `assert` or a different
   assertion library.

10. **Update `README.md`**: the architecture tree, the fixtures table, and add
    a short usage example if the agent introduces a new pattern worth
    documenting (like `rollback_after()` or `eventually_sync()` polling did).

11. **Verify before considering this done**:
    - `uv run python -m py_compile` the new files.
    - `uv run pytest --collect-only` succeeds when synced *without* the new
      extra (`uv sync` with no `--extra <domain>`) - this is the concrete
      proof the lazy-import boundary holds, not just that the code compiles.
    - If you can reach a real instance of the thing being tested (a local
      server, container, or stub), exercise the agent directly in a throwaway
      script the way `RestAgent`/`DbAgent`/`PerfAgent` were verified during
      the framework's initial build - don't just trust that the code compiles.
