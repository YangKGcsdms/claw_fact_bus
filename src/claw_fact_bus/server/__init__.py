"""
Fact Bus Web Server.

Provides HTTP API and WebSocket for claw cluster coordination.
"""

from .bus_engine import BusEngine
from .app import create_app

__all__ = ["BusEngine", "create_app"]
