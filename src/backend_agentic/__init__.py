"""backend-agentic: an agent-architecture backend testing framework.

Each backend surface (REST, GraphQL, DB, Kafka, reconciliation) is driven by a
small ``Agent`` that logs every action into a shared :class:`TestContext`, so a
scenario that spans several systems still reads as one timeline when it fails.
"""

from backend_agentic.core.agent import BaseAgent
from backend_agentic.core.context import TestContext

__all__ = ["BaseAgent", "TestContext"]

__version__ = "0.1.0"
