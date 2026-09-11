"""Property-based tests (via Hypothesis) for the ``is_uuid()`` /
``is_iso_datetime()`` assertpy2 matchers (``assertions/matchers.py``) - pure
predicates with no I/O, and per CLAUDE.md another piece of the framework
with no unit-test coverage in isolation before this.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend_agentic.assertions.matchers import is_iso_datetime, is_uuid

pytestmark = pytest.mark.unit

# Characters a valid UUID string can never contain, so text built only from
# this alphabet can never accidentally satisfy the UUID pattern - no filter/
# rejection sampling needed to keep the strategy a true negative case.
_non_hex_non_hyphen = st.characters(
    codec="utf-8", exclude_characters="0123456789abcdefABCDEF-", exclude_categories=["Cs"]
)


@given(value=st.uuids())
def test_is_uuid_matches_every_generated_uuid(value: uuid.UUID) -> None:
    assert is_uuid().matches(str(value))


@given(value=st.text(alphabet=_non_hex_non_hyphen, min_size=1, max_size=40))
def test_is_uuid_rejects_strings_that_cannot_look_like_a_uuid(value: str) -> None:
    assert not is_uuid().matches(value)


def test_is_uuid_rejects_a_uuid_without_hyphens() -> None:
    assert not is_uuid().matches(uuid.uuid4().hex)


def test_is_uuid_rejects_a_non_string_uuid_value() -> None:
    assert not is_uuid().matches(uuid.uuid4())


@given(value=st.datetimes())
def test_is_iso_datetime_matches_every_isoformat_datetime(value: datetime) -> None:
    assert is_iso_datetime().matches(value.isoformat())


@given(value=st.one_of(st.integers(), st.none(), st.booleans(), st.floats(), st.uuids()))
def test_is_iso_datetime_rejects_non_string_values(value: object) -> None:
    assert not is_iso_datetime().matches(value)


@given(value=st.text(max_size=20).filter(lambda s: not s or not s[0].isdigit()))
def test_is_iso_datetime_rejects_text_not_shaped_like_a_datetime(value: str) -> None:
    assert not is_iso_datetime().matches(value)
