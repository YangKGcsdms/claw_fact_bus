"""
Core protocol types for Claw Fact Bus.

These types ARE the protocol specification in machine-readable form.

Design principles:
  1. Fact = Immutable Record + Mutable Bus State (structural separation)
  2. Dual state machine: WorkflowState (task flow) × EpistemicState (truth lifecycle)
  3. Content integrity: hash verified on publish, bus signature as authority stamp
  4. Semantic classification: SemanticKind distinguishes observations from requests
  5. Knowledge evolution: supersede mechanism for fact replacement
  6. Social validation: corroboration/contradiction directly affects fact trust
  7. Content-addressed routing (fact_type + capabilities + domains)
  8. Broadcast with local filtering (AcceptanceFilter)
  9. Priority arbitration (Priority enum, 0-7)
  10. Fault confinement (TEC/REC in ClawIdentity)
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, IntEnum


# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

PROTOCOL_VERSION = "2.0.0"
DEFAULT_CONSENSUS_QUORUM = 2
DEFAULT_REFUTATION_QUORUM = 2


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FactState(str, Enum):
    """
    Workflow states — tracks where a fact is in its processing lifecycle.
    Orthogonal to EpistemicState (truth lifecycle).
    """

    CREATED = "created"
    PUBLISHED = "published"
    MATCHED = "matched"
    CLAIMED = "claimed"
    PROCESSING = "processing"
    RESOLVED = "resolved"
    DEAD = "dead"


class EpistemicState(str, Enum):
    """
    Truth states — tracks how trustworthy a fact is considered.
    Orthogonal to FactState (workflow lifecycle).

    A fact can be workflow=CLAIMED but epistemic=CONTESTED, meaning
    someone is working on it but the premise has been challenged.
    """

    ASSERTED = "asserted"
    CORROBORATED = "corroborated"
    CONSENSUS = "consensus"
    CONTESTED = "contested"
    REFUTED = "refuted"
    SUPERSEDED = "superseded"


# Rank ordering for filter comparison: higher = more trusted
EPISTEMIC_RANK: dict[EpistemicState, int] = {
    EpistemicState.SUPERSEDED: -3,
    EpistemicState.REFUTED: -2,
    EpistemicState.CONTESTED: -1,
    EpistemicState.ASSERTED: 0,
    EpistemicState.CORROBORATED: 1,
    EpistemicState.CONSENSUS: 2,
}


class SemanticKind(str, Enum):
    """
    Classifies WHAT a fact represents epistemically.

    Keeps the Fact envelope universal while distinguishing observations
    from requests from corrections — without splitting into multiple
    struct types (like HTTP keeps one request format but uses Content-Type).
    """

    OBSERVATION = "observation"   # "build failed", "cpu at 92%"
    ASSERTION = "assertion"       # "root cause is cache miss" (inference)
    REQUEST = "request"           # "review needed", "deploy requested"
    RESOLUTION = "resolution"     # "review done: 2 issues found"
    CORRECTION = "correction"     # supersedes a previous fact
    SIGNAL = "signal"             # "heartbeat", "progress 60%" (fire-and-forget)


class FactMode(str, Enum):
    """Delivery semantics — the critical routing decision."""

    BROADCAST = "broadcast"
    EXCLUSIVE = "exclusive"


class Priority(IntEnum):
    """
    Priority levels, lower value = higher priority (CAN convention).
    Range 0-7 mirrors CAN's 3-bit priority field in J1939.
    """

    CRITICAL = 0
    HIGH = 1
    ELEVATED = 2
    NORMAL = 3
    LOW = 4
    BACKGROUND = 5
    IDLE = 6
    BULK = 7


# ---------------------------------------------------------------------------
# State Machines
# ---------------------------------------------------------------------------


class InvalidStateTransition(Exception):
    """Raised when an illegal workflow state transition is attempted."""
    pass


class WorkflowStateMachine:
    """
    Formal transition table for fact workflow states.

    Like TCP's state machine (SYN_SENT → ESTABLISHED → FIN_WAIT → ...),
    only the defined transitions are legal. This is a protocol constraint,
    not just a convention.
    """

    TRANSITIONS: dict[FactState, set[FactState]] = {
        FactState.CREATED: {FactState.PUBLISHED, FactState.DEAD},
        FactState.PUBLISHED: {FactState.MATCHED, FactState.CLAIMED, FactState.DEAD},
        FactState.MATCHED: {FactState.CLAIMED, FactState.DEAD},
        FactState.CLAIMED: {
            FactState.PROCESSING, FactState.RESOLVED,
            FactState.PUBLISHED,  # release
            FactState.DEAD,
        },
        FactState.PROCESSING: {FactState.RESOLVED, FactState.DEAD},
        FactState.RESOLVED: set(),  # terminal
        FactState.DEAD: {FactState.PUBLISHED},  # admin redispatch only
    }

    @classmethod
    def can_transition(cls, from_state: FactState, to_state: FactState) -> bool:
        return to_state in cls.TRANSITIONS.get(from_state, set())

    @classmethod
    def transition(cls, fact: Fact, to_state: FactState, *, force: bool = False) -> None:
        if not force and not cls.can_transition(fact.state, to_state):
            raise InvalidStateTransition(
                f"cannot transition from {fact.state.value} to {to_state.value}"
            )
        fact.state = to_state


class EpistemicStateMachine:
    """
    Recomputes epistemic_state from corroboration/contradiction evidence.

    Unlike WorkflowStateMachine (explicit transitions), epistemic state
    is derived from the accumulated evidence. This mirrors how scientific
    consensus works: the state is a function of the evidence, not of
    explicit commands.
    """

    @classmethod
    def recompute(
        cls,
        fact: Fact,
        consensus_quorum: int = DEFAULT_CONSENSUS_QUORUM,
        refutation_quorum: int = DEFAULT_REFUTATION_QUORUM,
    ) -> EpistemicState:
        if fact.superseded_by:
            fact.epistemic_state = EpistemicState.SUPERSEDED
        elif len(fact.contradictions) >= refutation_quorum:
            fact.epistemic_state = EpistemicState.REFUTED
        elif fact.contradictions:
            fact.epistemic_state = EpistemicState.CONTESTED
        elif len(fact.corroborations) >= consensus_quorum:
            fact.epistemic_state = EpistemicState.CONSENSUS
        elif fact.corroborations:
            fact.epistemic_state = EpistemicState.CORROBORATED
        else:
            fact.epistemic_state = EpistemicState.ASSERTED
        return fact.epistemic_state


# ---------------------------------------------------------------------------
# Fact: The atomic unit on the bus
# ---------------------------------------------------------------------------


@dataclass
class Fact:
    """
    The fundamental unit of communication on the Fact Bus.

    Structurally divided into two zones:
      - IMMUTABLE RECORD: Set at creation, never modified after publish.
        Covered by content_hash and bus signature.
      - MUTABLE BUS STATE: Managed exclusively by the bus engine.
        Changes as the fact moves through workflow and trust lifecycles.

    This separation is the protocol's core integrity guarantee:
    "the content of a published fact never changes; only the bus's
    assessment of it evolves."
    """

    # ===== IMMUTABLE RECORD (frozen after publish) =====

    # --- Identity ---
    fact_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    fact_type: str = ""
    semantic_kind: SemanticKind = SemanticKind.OBSERVATION

    # --- Content ---
    payload: dict = field(default_factory=dict)

    # --- Content Addressing ---
    domain_tags: list[str] = field(default_factory=list)
    need_capabilities: list[str] = field(default_factory=list)

    # --- Routing ---
    priority: int = Priority.NORMAL
    mode: FactMode = FactMode.EXCLUSIVE

    # --- Lineage ---
    source_claw_id: str = ""
    causation_chain: list[str] = field(default_factory=list)
    causation_depth: int = 0

    # --- Knowledge Evolution ---
    subject_key: str = ""       # Groups facts about the same subject
    supersedes: str = ""        # fact_id this fact replaces

    # --- Lifecycle ---
    created_at: float = field(default_factory=time.time)
    ttl_seconds: int = 300
    schema_version: str = "1.0.0"

    # --- Trust (publisher-provided) ---
    confidence: float = 1.0

    # --- Integrity ---
    content_hash: str = ""
    signature: str = ""         # Bus authority HMAC stamp

    # --- Protocol ---
    protocol_version: str = PROTOCOL_VERSION

    # ===== MUTABLE BUS STATE (managed by engine) =====

    state: FactState = FactState.CREATED
    epistemic_state: EpistemicState = EpistemicState.ASSERTED
    claimed_by: str | None = None
    resolved_at: float | None = None
    effective_priority: int | None = None
    sequence_number: int = 0
    superseded_by: str = ""
    corroborations: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)

    # ===== METHODS =====

    def compute_content_hash(self) -> str:
        """Compute SHA-256 over canonical payload representation."""
        canonical = json.dumps(self.payload, sort_keys=True, ensure_ascii=False)
        self.content_hash = hashlib.sha256(canonical.encode()).hexdigest()
        return self.content_hash

    def verify_content_hash(self) -> bool:
        """Verify that content_hash matches the current payload."""
        if not self.content_hash:
            return True  # No hash to verify
        canonical = json.dumps(self.payload, sort_keys=True, ensure_ascii=False)
        expected = hashlib.sha256(canonical.encode()).hexdigest()
        return self.content_hash == expected

    @property
    def parent_fact_id(self) -> str:
        """Direct causal parent (last entry in causation_chain), or empty for root facts."""
        return self.causation_chain[-1] if self.causation_chain else ""

    def is_expired(self) -> bool:
        return time.time() > self.created_at + self.ttl_seconds

    def derive_child(
        self,
        fact_type: str,
        payload: dict,
        source_claw_id: str,
        **kwargs,
    ) -> Fact:
        """Create a child fact inheriting causation lineage."""
        return Fact(
            fact_type=fact_type,
            payload=payload,
            source_claw_id=source_claw_id,
            causation_chain=[*self.causation_chain, self.fact_id],
            causation_depth=self.causation_depth + 1,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Claw: An agent node on the bus (analogous to a CAN ECU)
# ---------------------------------------------------------------------------


class ClawState(str, Enum):
    """
    Node health states, modeled after CAN's error state machine:
      CAN: error-active → error-passive → bus-off
      Bus: active → degraded → isolated
    """

    ACTIVE = "active"
    DEGRADED = "degraded"
    ISOLATED = "isolated"
    OFFLINE = "offline"


@dataclass
class AcceptanceFilter:
    """
    CAN-style acceptance filter for a claw.

    Epistemic and semantic filtering dimensions let consumers say
    "only give me corroborated observations about build.*".
    """

    # --- Content addressing ---
    capability_offer: list[str] = field(default_factory=list)
    domain_interests: list[str] = field(default_factory=list)
    fact_type_patterns: list[str] = field(default_factory=list)
    priority_range: tuple[int, int] = (Priority.CRITICAL, Priority.BULK)
    modes: list[FactMode] = field(
        default_factory=lambda: [FactMode.EXCLUSIVE, FactMode.BROADCAST]
    )

    # --- Semantic + epistemic ---
    semantic_kinds: list[SemanticKind] = field(default_factory=list)  # empty = all
    min_epistemic_rank: int = -3  # default accepts everything
    min_confidence: float = 0.0
    exclude_superseded: bool = True
    subject_key_patterns: list[str] = field(default_factory=list)  # glob patterns


@dataclass
class ClawIdentity:
    """An agent's presence on the bus."""

    claw_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    description: str = ""

    acceptance_filter: AcceptanceFilter = field(default_factory=AcceptanceFilter)
    max_concurrent_claims: int = 1

    state: ClawState = ClawState.OFFLINE
    transmit_error_counter: int = 0
    receive_error_counter: int = 0
    reliability_score: float = 1.0

    connected_at: float | None = None
    last_heartbeat: float | None = None

    @property
    def is_healthy(self) -> bool:
        return self.state in (ClawState.ACTIVE, ClawState.DEGRADED)


# ---------------------------------------------------------------------------
# Bus Operations (the protocol verbs)
# ---------------------------------------------------------------------------


class OpCode(str, Enum):
    """All operations on the bus."""

    CONNECT = "connect"
    DISCONNECT = "disconnect"
    HEARTBEAT = "heartbeat"
    PUBLISH = "publish"
    CLAIM = "claim"
    RELEASE = "release"
    RESOLVE = "resolve"
    QUERY = "query"
    SUBSCRIBE = "subscribe"
    CORROBORATE = "corroborate"
    CONTRADICT = "contradict"


@dataclass
class BusMessage:
    """Wire format for all bus communication."""

    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    op: OpCode = OpCode.HEARTBEAT
    claw_id: str = ""
    timestamp: float = field(default_factory=time.time)

    fact: Fact | None = None
    claim_fact_id: str | None = None
    query_filter: dict | None = None
    target_fact_id: str | None = None
    result_facts: list[Fact] | None = None
    claw_identity: ClawIdentity | None = None

    success: bool = True
    error: str | None = None


# ---------------------------------------------------------------------------
# Bus Events
# ---------------------------------------------------------------------------


class BusEventType(str, Enum):
    """Events the bus pushes to subscribed claws."""

    FACT_AVAILABLE = "fact_available"
    FACT_CLAIMED = "fact_claimed"
    FACT_RESOLVED = "fact_resolved"
    FACT_EXPIRED = "fact_expired"
    FACT_DEAD = "fact_dead"
    FACT_SUPERSEDED = "fact_superseded"
    FACT_TRUST_CHANGED = "fact_trust_changed"
    CLAW_STATE_CHANGED = "claw_state_changed"


@dataclass
class BusEvent:
    """Notification pushed from bus to claw."""

    event_type: BusEventType = BusEventType.FACT_AVAILABLE
    fact: Fact | None = None
    claw_id: str | None = None
    detail: str = ""
    timestamp: float = field(default_factory=time.time)
