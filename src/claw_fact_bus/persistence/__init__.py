"""
Persistence layer for Fact Bus.

Provides append-only fact log for event sourcing.
"""

from .jsonl_store import JSONLFactStore

__all__ = ["JSONLFactStore"]
