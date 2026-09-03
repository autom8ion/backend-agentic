"""A shared Faker instance and a uniqueness helper for building test payloads.

Domain-specific factories (an ``OrderFactory``, a ``UserFactory``, ...) belong
in the project using this framework, next to the schemas they build for -
this module only provides the two primitives every factory needs.
"""

from __future__ import annotations

import uuid

from faker import Faker

fake = Faker()


def unique_id(prefix: str = "") -> str:
    """A short, collision-safe id for naming test entities, e.g. `unique_id("order")`."""
    token = uuid.uuid4().hex[:12]
    return f"{prefix}-{token}" if prefix else token
