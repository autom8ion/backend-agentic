"""Matchers for values that show up constantly in backend contracts:
server-generated ids and timestamps that a REST/GraphQL/Kafka payload can't
pin down to a literal, so ``matches_structure()`` / ``is_equal_to()`` needs a
predicate instead::

    assert_that(payload).matches_structure({"id": is_uuid(), "created_at": is_iso_datetime()})

Written as :class:`assertpy2.BaseMatcher` subclasses per the
`custom matchers guide <https://solganis.github.io/assertpy2/guides/matchers/#custom-matchers>`_:
fully typed, composable with ``&`` / ``|`` / ``~``, and free of any dependency
on assertpy2's internals.
"""

from __future__ import annotations

import re
from datetime import datetime

from assertpy2 import BaseMatcher

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class _UuidMatcher(BaseMatcher):
    def matches(self, value: object) -> bool:
        return isinstance(value, str) and bool(_UUID_RE.match(value))

    def describe(self) -> str:
        return "a valid UUID string"


class _IsoDatetimeMatcher(BaseMatcher):
    def matches(self, value: object) -> bool:
        if not isinstance(value, str):
            return False
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False

    def describe(self) -> str:
        return "a valid ISO-8601 datetime string"


def is_uuid() -> _UuidMatcher:
    return _UuidMatcher()


def is_iso_datetime() -> _IsoDatetimeMatcher:
    return _IsoDatetimeMatcher()
