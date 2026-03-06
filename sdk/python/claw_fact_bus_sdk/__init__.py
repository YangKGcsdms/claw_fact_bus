"""
Claw Fact Bus Python SDK.

High-level client for connecting AI agents (claws) to the Fact Bus.
"""

from .client import FactBusClient
from .models import (
    AcceptanceFilter,
    Fact,
    FactMode,
    FactState,
    Priority,
    BusEvent,
    BusEventType,
)

__version__ = "0.1.0"
__all__ = [
    "FactBusClient",
    "AcceptanceFilter",
    "Fact",
    "FactMode",
    "FactState",
    "Priority",
    "BusEvent",
    "BusEventType",
]
