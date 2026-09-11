"""SQL database access for assertions and fixture setup, with polars as the
data-frame boundary shared with :mod:`backend_agentic.reconciliation`.

Requires the ``db`` extra: ``pip install backend-agentic[db]``.

``query_df`` reads through `connectorx <https://github.com/sfu-db/connector-x>`_
(via ``polars.read_database_uri``) when no bound parameters are needed, since
it is materially faster for the bulk pulls a reconciliation scenario tends to
do; parameterised queries fall back to a SQLAlchemy connection so values are
always bound, never string-formatted into SQL.

``rollback_after()`` hands back a live connection inside a transaction that is
always rolled back on exit - the standard way to insert fixture data for a
test without leaving it behind.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

try:
    import polars as pl
    from sqlalchemy import Connection, Engine, create_engine, text
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "DbAgent requires the 'db' extra: pip install backend-agentic[db]"
    ) from exc

from backend_agentic.config import DbSettings
from backend_agentic.core.agent import BaseAgent
from backend_agentic.core.context import TestContext

_engine_cache: dict[str, Engine] = {}


class DbAgent(BaseAgent):
    name = "db"

    def __init__(self, context: TestContext, settings: DbSettings) -> None:
        super().__init__(context)
        self.settings = settings

    def _dsn(self, connection: str) -> str:
        name = connection or self.settings.default_connection
        try:
            return self.settings.connections[name]
        except KeyError as exc:
            raise KeyError(
                f"no DB connection named {name!r} configured; known: {list(self.settings.connections)}"
            ) from exc

    def _engine(self, connection: str) -> Engine:
        dsn = self._dsn(connection)
        if dsn not in _engine_cache:
            _engine_cache[dsn] = create_engine(dsn, pool_pre_ping=True)
        return _engine_cache[dsn]

    def execute(self, sql: str, params: dict[str, Any] | None = None, *, connection: str = "default") -> Any:
        with self.step("execute", detail=sql[:120]):
            engine = self._engine(connection)
            with engine.begin() as conn:
                return conn.execute(text(sql), params or {})

    def query_df(
        self, sql: str, params: dict[str, Any] | None = None, *, connection: str = "default"
    ) -> pl.DataFrame:
        with self.step("query_df", detail=sql[:120]):
            if params:
                engine = self._engine(connection)
                with engine.connect() as conn:
                    return pl.read_database(query=text(sql), connection=conn, execute_options={"parameters": params})
            try:
                return pl.read_database_uri(query=sql, uri=self._dsn(connection))
            except Exception:  # noqa: BLE001 - connectorx fast path falls back to SQLAlchemy on any failure
                engine = self._engine(connection)
                with engine.connect() as conn:
                    return pl.read_database(query=text(sql), connection=conn)

    def query_one(
        self, sql: str, params: dict[str, Any] | None = None, *, connection: str = "default"
    ) -> dict[str, Any] | None:
        with self.step("query_one", detail=sql[:120]):
            engine = self._engine(connection)
            with engine.connect() as conn:
                row = conn.execute(text(sql), params or {}).mappings().first()
                return dict(row) if row is not None else None

    def query_scalar(
        self, sql: str, params: dict[str, Any] | None = None, *, connection: str = "default"
    ) -> Any:
        row = self.query_one(sql, params, connection=connection)
        if not row:
            return None
        return next(iter(row.values()))

    @contextmanager
    def rollback_after(self, connection: str = "default") -> Iterator[Connection]:
        """Yield a connection inside a transaction that is always rolled back.

        Use to insert fixture rows a test needs without leaving them behind::

            with db_agent.rollback_after() as conn:
                conn.execute(text("INSERT INTO orders (id, sku) VALUES (:id, :sku)"), {"id": 1, "sku": "A-1"})
                ... run the scenario against that row ...
        """
        engine = self._engine(connection)
        conn = engine.connect()
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()
            conn.close()

    def close(self) -> None:
        pass


def dispose_all_engines() -> None:
    """Dispose every cached engine. Called once at the end of the test session."""
    for engine in _engine_cache.values():
        engine.dispose()
    _engine_cache.clear()
