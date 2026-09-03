"""Turn a REST response, a DB query, a Kafka topic, or a CSV file into the
``pl.DataFrame`` that :func:`backend_agentic.reconciliation.agent.reconcile`
compares.

These take an already-constructed agent (or an ``httpx.Response``) as an
argument rather than importing ``DbAgent``/``KafkaAgent`` themselves, so
using ``from_rest``/``from_records``/``from_csv`` never requires the ``db`` or
``kafka`` extras to be installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import httpx
import polars as pl


def from_records(records: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(records)


def from_rest(response: httpx.Response, record_path: str | None = None) -> pl.DataFrame:
    """Build a DataFrame from a JSON REST response.

    ``record_path`` drills into a nested envelope with dotted keys, e.g.
    ``record_path="data.items"`` for ``{"data": {"items": [...]}}``.
    """
    body: Any = response.json()
    if record_path:
        for part in record_path.split("."):
            body = body[part]
    if isinstance(body, dict):
        body = [body]
    return pl.DataFrame(body)


def from_csv(path: str | Path, **read_csv_kwargs: Any) -> pl.DataFrame:
    return pl.read_csv(path, **read_csv_kwargs)


class _QueryDfCapable(Protocol):
    def query_df(self, sql: str, params: dict[str, Any] | None = None, *, connection: str = "default") -> pl.DataFrame: ...


def from_db(
    db_agent: _QueryDfCapable, sql: str, params: dict[str, Any] | None = None, *, connection: str = "default"
) -> pl.DataFrame:
    return db_agent.query_df(sql, params, connection=connection)


class _ConsumeToDfCapable(Protocol):
    def consume_to_df(self, topic: str, timeout: float = ..., **kwargs: Any) -> pl.DataFrame: ...


def from_kafka(kafka_agent: _ConsumeToDfCapable, topic: str, timeout: float = 5.0, **kwargs: Any) -> pl.DataFrame:
    return kafka_agent.consume_to_df(topic, timeout=timeout, **kwargs)
