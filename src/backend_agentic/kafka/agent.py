"""Kafka producer/consumer for event-driven scenarios.

Requires the ``kafka`` extra: ``pip install backend-agentic[kafka]`` (which
needs ``librdkafka`` on the host - see the README).

The core operation for testing is "did the expected event show up", not
generic streaming, so :meth:`KafkaAgent.wait_for_message` is the primary API:
it subscribes a **fresh, uniquely-named consumer group** (so parallel tests
never share offsets or steal each other's messages), reads from the earliest
offset, and polls until a message satisfies a predicate or the deadline
passes - raising :class:`~backend_agentic.core.exceptions.KafkaWaitTimeoutError`
with every message it *did* see, which is almost always the fastest way to
debug a failed assertion about an event.

``consume_to_df`` feeds a topic's contents straight into a polars
``DataFrame`` for :mod:`backend_agentic.reconciliation`.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

try:
    import polars as pl
    from confluent_kafka import Consumer, KafkaException, Message, Producer
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "KafkaAgent requires the 'kafka' extra: pip install backend-agentic[kafka]"
    ) from exc

from backend_agentic.config import KafkaSettings
from backend_agentic.core.agent import BaseAgent
from backend_agentic.core.context import TestContext
from backend_agentic.core.exceptions import KafkaWaitTimeoutError

Predicate = Callable[["KafkaMessage"], bool]


@dataclass
class KafkaMessage:
    topic: str
    partition: int
    offset: int
    key: str | None
    value: Any
    headers: dict[str, bytes]
    timestamp_ms: int


def _decode_headers(message: Message) -> dict[str, bytes]:
    return {k: v for k, v in (message.headers() or [])}


class KafkaAgent(BaseAgent):
    name = "kafka"

    def __init__(self, context: TestContext, settings: KafkaSettings) -> None:
        super().__init__(context)
        self.settings = settings
        self._producer: Producer | None = None
        self._consumers: list[Consumer] = []

    @property
    def producer(self) -> Producer:
        if self._producer is None:
            self._producer = Producer(
                {"bootstrap.servers": self.settings.bootstrap_servers, **self.settings.security_config}
            )
        return self._producer

    def produce(
        self,
        topic: str,
        value: Any,
        key: str | None = None,
        headers: dict[str, str] | None = None,
        value_serializer: Callable[[Any], bytes] = lambda v: json.dumps(v).encode("utf-8"),
        flush: bool = True,
        timeout: float = 10.0,
    ) -> None:
        with self.step("produce", detail=f"topic={topic} key={key}"):
            delivery_error: list[Exception] = []

            def _on_delivery(err: Any, _msg: Message) -> None:
                if err is not None:
                    delivery_error.append(KafkaException(err))

            self.producer.produce(
                topic,
                value=value_serializer(value),
                key=key.encode("utf-8") if key else None,
                headers=[(k, v.encode("utf-8")) for k, v in (headers or {}).items()],
                on_delivery=_on_delivery,
            )
            if flush:
                self.producer.flush(timeout)
                if delivery_error:
                    raise delivery_error[0]

    def _new_consumer(self, group_id: str | None, from_beginning: bool) -> Consumer:
        group = group_id or f"{self.settings.consumer_group_prefix}-{self.context.correlation_id}-{uuid.uuid4().hex[:8]}"
        consumer = Consumer(
            {
                "bootstrap.servers": self.settings.bootstrap_servers,
                "group.id": group,
                "auto.offset.reset": "earliest" if from_beginning else "latest",
                "enable.auto.commit": False,
                **self.settings.security_config,
            }
        )
        self._consumers.append(consumer)
        return consumer

    def _poll_messages(
        self,
        topic: str,
        consumer: Consumer,
        timeout: float,
        value_deserializer: Callable[[bytes], Any],
        predicate: Predicate | None,
    ) -> tuple[KafkaMessage | None, list[KafkaMessage]]:
        consumer.subscribe([topic])
        seen: list[KafkaMessage] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = consumer.poll(timeout=min(0.5, max(deadline - time.monotonic(), 0)))
            if raw is None:
                continue
            if raw.error():
                raise KafkaException(raw.error())
            msg = KafkaMessage(
                topic=raw.topic(),
                partition=raw.partition(),
                offset=raw.offset(),
                key=raw.key().decode("utf-8") if raw.key() else None,
                value=value_deserializer(raw.value()),
                headers=_decode_headers(raw),
                timestamp_ms=raw.timestamp()[1],
            )
            seen.append(msg)
            if predicate is None or predicate(msg):
                return msg, seen
        return None, seen

    def wait_for_message(
        self,
        topic: str,
        predicate: Predicate = lambda _m: True,
        timeout: float = 15.0,
        group_id: str | None = None,
        from_beginning: bool = True,
        value_deserializer: Callable[[bytes], Any] = json.loads,
    ) -> KafkaMessage:
        """Poll until a message matching ``predicate`` arrives, or raise with everything seen."""
        with self.step("wait_for_message", detail=f"topic={topic} timeout={timeout}s"):
            consumer = self._new_consumer(group_id, from_beginning)
            found, seen = self._poll_messages(topic, consumer, timeout, value_deserializer, predicate)
            if found is None:
                raise KafkaWaitTimeoutError(topic, timeout, [m.value for m in seen])
            return found

    def consume_all(
        self,
        topic: str,
        timeout: float = 5.0,
        group_id: str | None = None,
        from_beginning: bool = True,
        value_deserializer: Callable[[bytes], Any] = json.loads,
    ) -> list[KafkaMessage]:
        """Collect every message available on ``topic`` within ``timeout`` seconds."""
        with self.step("consume_all", detail=f"topic={topic} timeout={timeout}s"):
            consumer = self._new_consumer(group_id, from_beginning)
            _, seen = self._poll_messages(topic, consumer, timeout, value_deserializer, predicate=None)
            return seen

    def consume_to_df(
        self,
        topic: str,
        timeout: float = 5.0,
        group_id: str | None = None,
        from_beginning: bool = True,
        value_deserializer: Callable[[bytes], Any] = json.loads,
    ) -> "pl.DataFrame":
        """Collect a topic's messages into a polars DataFrame, for reconciliation."""
        messages = self.consume_all(
            topic, timeout=timeout, group_id=group_id, from_beginning=from_beginning,
            value_deserializer=value_deserializer,
        )
        return pl.DataFrame([m.value for m in messages])

    def close(self) -> None:
        for consumer in self._consumers:
            consumer.close()
        self._consumers.clear()
        if self._producer is not None:
            self._producer.flush(5.0)
