"""
OpenClaw Claw Fact Bus Integration Skill.

Connects OpenClaw instances to the Claw Fact Bus as autonomous agents.
"""

from .fact_bus_client import (
    Fact,
    FactBusClient,
    ClawInfo,
    Priority,
    create_client,
)
from .handlers import (
    FactBusAgent,
    FactBusState,
    HandlerRule,
    ObservationHandler,
    RequestHandler,
)

__version__ = "1.0.0"
__author__ = "Carter.Yang"

__all__ = [
    # Client
    "Fact",
    "FactBusClient",
    "ClawInfo",
    "Priority",
    "create_client",
    # Handlers
    "FactBusAgent",
    "FactBusState",
    "HandlerRule",
    "ObservationHandler",
    "RequestHandler",
]
