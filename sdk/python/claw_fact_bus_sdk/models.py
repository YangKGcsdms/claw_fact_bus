"""
Pydantic models for the SDK.

Mirrors the server-side types but as Pydantic models for validation.
"""

from __future__ import annotations

from enum import Enum, IntEnum
from typing import Any

from pydantic import BaseModel, Field


class Priority(IntEnum):
    """Priority levels (lower = higher priority)."""

    CRITICAL = 0
    HIGH = 1
    ELEVATED = 2
    NORMAL = 3
    LOW = 4
    BACKGROUND = 5
    IDLE = 6
    BULK = 7


class FactMode(str, Enum):
    """Fact delivery mode."""

    BROADCAST = "broadcast"
    EXCLUSIVE = "exclusive"


class FactState(str, Enum):
    """Fact lifecycle state."""

    CREATED = "created"
    PUBLISHED = "published"
    MATCHED = "matched"
    CLAIMED = "claimed"
    PROCESSING = "processing"
    RESOLVED = "resolved"
    DEAD = "dead"


class BusEventType(str, Enum):
    """Event types pushed by the bus."""

    FACT_AVAILABLE = "fact_available"
    FACT_CLAIMED = "fact_claimed"
    FACT_RESOLVED = "fact_resolved"
    FACT_EXPIRED = "fact_expired"
    FACT_DEAD = "fact_dead"
    CLAW_STATE_CHANGED = "claw_state_changed"


class AcceptanceFilter(BaseModel):
    """
    Filter declaring what facts this claw wants to receive.

    At least one of capability_offer, domain_interests, or fact_type_patterns
    must match for a fact to be delivered.

    For common use cases, use the factory classmethods instead of
    constructing manually::

        AcceptanceFilter.worker(["code_review", "python"])
        AcceptanceFilter.monitor(["backend"])
        AcceptanceFilter.coordinator(["deploy.*", "ci.*"])
    """

    capability_offer: list[str] = Field(
        default_factory=list,
        description="What this claw CAN do (e.g. ['review', 'python'])",
    )
    domain_interests: list[str] = Field(
        default_factory=list,
        description="What domains it cares about (e.g. ['backend', 'api'])",
    )
    fact_type_patterns: list[str] = Field(
        default_factory=list,
        description="Glob patterns for fact types (e.g. ['code.*', 'deploy.*'])",
    )
    priority_range: tuple[int, int] = Field(
        default=(0, 7),
        description="Accepted priority range (min, max)",
    )
    modes: list[str] = Field(
        default_factory=lambda: ["exclusive", "broadcast"],
        description="Which fact modes to accept",
    )

    @classmethod
    def worker(cls, capabilities: list[str], **overrides: Any) -> AcceptanceFilter:
        """Claw that claims and processes exclusive facts matching its capabilities."""
        return cls(
            capability_offer=capabilities,
            modes=["exclusive"],
            **overrides,
        )

    @classmethod
    def monitor(cls, domains: list[str], **overrides: Any) -> AcceptanceFilter:
        """Read-only claw that observes broadcast facts in given domains."""
        return cls(
            domain_interests=domains,
            modes=["broadcast"],
            **overrides,
        )

    @classmethod
    def coordinator(cls, patterns: list[str], **overrides: Any) -> AcceptanceFilter:
        """Claw that receives all delivery modes, filtered by fact_type patterns."""
        return cls(
            fact_type_patterns=patterns,
            modes=["exclusive", "broadcast"],
            **overrides,
        )


class Fact(BaseModel):
    """A fact on the bus."""

    fact_id: str | None = None
    fact_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    domain_tags: list[str] = Field(default_factory=list)
    need_capabilities: list[str] = Field(default_factory=list)
    priority: int = Field(default=Priority.NORMAL, ge=0, le=7)
    mode: str = Field(default="exclusive")
    source_claw_id: str = ""
    causation_chain: list[str] = Field(default_factory=list)
    causation_depth: int = 0
    created_at: float | None = None
    ttl_seconds: int = Field(default=300, ge=10)
    schema_version: str = "1.0"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    state: str | None = None
    claimed_by: str | None = None
    effective_priority: int | None = None


class BusEvent(BaseModel):
    """Event pushed from the bus to a claw."""

    event_type: str
    fact: Fact | None = None
    claw_id: str | None = None
    detail: str = ""
    timestamp: float | None = None


class ClawInfo(BaseModel):
    """Information about a connected claw."""

    claw_id: str
    name: str
    state: str
    reliability_score: float
    capabilities: list[str] = Field(default_factory=list)
