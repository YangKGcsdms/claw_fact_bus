"""
Flow control, storm protection, and livelock prevention.

Three lines of defense against runaway fact production:

  Defense 1: Causation depth breaker    (prevents cascade chains)
  Defense 2: Per-claw rate limiter      (prevents single-source floods)
  Defense 3: Global bus load breaker    (prevents aggregate overload)

Plus: livelock detection via causation chain cycle check.
Plus: priority aging to prevent starvation.

CAN Bus parallels:
  - CAN has no explicit flow control (it's a real-time bus), but overload frames
    signal "I need the bus to pause". Our backpressure mechanism is analogous.
  - CAN's bus-off mechanism (reliability.py) is the ultimate flow control:
    a misbehaving node removes itself from the bus entirely.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .types import Fact, Priority


# ---------------------------------------------------------------------------
# Defense 1: Causation depth breaker
# ---------------------------------------------------------------------------

MAX_CAUSATION_DEPTH = 16


def check_causation_depth(fact: Fact) -> tuple[bool, str]:
    """Reject facts that exceed the maximum causation chain depth."""
    if fact.causation_depth > MAX_CAUSATION_DEPTH:
        return False, (
            f"causation depth {fact.causation_depth} exceeds limit {MAX_CAUSATION_DEPTH}"
        )
    return True, "ok"


def check_causation_cycle(fact: Fact) -> tuple[bool, str]:
    """
    Detect cycles in the causation chain.

    Two layers of protection:
    1. Self-reference: fact_id already in its own chain
    2. Behavioral loop: the same (source_claw_id, fact_type) pair appears in the
       chain metadata, indicating an A→B→A→B livelock pattern.

    The behavioral check uses a registry that maps fact_ids to their
    (source_claw_id, fact_type) signatures. This is populated by the PublishGate
    on each successful publish.
    """
    # Layer 1: fact_id self-reference
    if fact.fact_id in fact.causation_chain:
        return False, f"cycle detected: fact {fact.fact_id} references itself in chain"

    # Layer 2: duplicate fact_id in chain (should never happen, but guard)
    if len(fact.causation_chain) != len(set(fact.causation_chain)):
        return False, "cycle detected: duplicate fact_id in causation chain"

    return True, "ok"


def check_behavioral_loop(
    fact: Fact, chain_signatures: dict[str, str]
) -> tuple[bool, str]:
    """
    Detect behavioral livelock: the same (source_claw_id:fact_type) pair
    appearing multiple times in the causation chain means two claws are
    ping-ponging the same type of work back and forth.

    Args:
        fact: The fact being published.
        chain_signatures: Registry mapping fact_id -> "source_claw_id:fact_type"
    """
    current_sig = f"{fact.source_claw_id}:{fact.fact_type}"
    seen_sigs: list[str] = []

    for ancestor_id in fact.causation_chain:
        sig = chain_signatures.get(ancestor_id)
        if sig is not None:
            seen_sigs.append(sig)

    if current_sig in seen_sigs:
        return False, (
            f"behavioral loop detected: {current_sig} already appeared "
            f"in causation chain (livelock pattern A→B→A)"
        )

    return True, "ok"


# ---------------------------------------------------------------------------
# Defense 2: Per-claw token bucket rate limiter
# ---------------------------------------------------------------------------


@dataclass
class TokenBucket:
    """
    Classic token bucket rate limiter.
    Each claw gets one bucket. Tokens replenish at a fixed rate.
    """

    capacity: float = 20.0  # Max burst size
    refill_rate: float = 5.0  # Tokens per second
    tokens: float = field(init=False)
    last_refill: float = field(default_factory=time.time)

    def __post_init__(self):
        self.tokens = self.capacity

    def try_consume(self, n: float = 1.0) -> bool:
        """Try to consume n tokens. Returns False if insufficient."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


@dataclass
class ClawRateLimiter:
    """Manages per-claw rate limit buckets."""

    buckets: dict[str, TokenBucket] = field(default_factory=dict)
    default_capacity: float = 20.0
    default_refill_rate: float = 5.0

    def check(self, claw_id: str) -> tuple[bool, str]:
        if claw_id not in self.buckets:
            self.buckets[claw_id] = TokenBucket(
                capacity=self.default_capacity, refill_rate=self.default_refill_rate
            )
        bucket = self.buckets[claw_id]
        if bucket.try_consume():
            return True, "ok"
        return False, f"claw {claw_id} rate limit exceeded"


# ---------------------------------------------------------------------------
# Defense 3: Global bus load breaker
# ---------------------------------------------------------------------------


@dataclass
class BusLoadBreaker:
    """
    Monitors global fact throughput and engages emergency mode
    when the bus is overloaded.

    In emergency mode, only facts with priority ≤ emergency_threshold are accepted.
    This is analogous to CAN's behavior under heavy bus load where low-priority
    messages get indefinitely delayed.
    """

    window_seconds: float = 5.0
    max_facts_per_window: int = 200
    emergency_priority_threshold: int = Priority.HIGH

    _timestamps: list[float] = field(default_factory=list)
    _emergency_mode: bool = False

    @property
    def is_emergency(self) -> bool:
        return self._emergency_mode

    def record_and_check(self, fact: Fact) -> tuple[bool, str]:
        """Record a fact publication and check if it should be accepted."""
        now = time.time()
        cutoff = now - self.window_seconds

        self._timestamps = [t for t in self._timestamps if t > cutoff]
        self._timestamps.append(now)

        current_load = len(self._timestamps)

        if current_load > self.max_facts_per_window:
            self._emergency_mode = True

            effective_priority = (
                fact.effective_priority if fact.effective_priority is not None else fact.priority
            )
            if effective_priority > self.emergency_priority_threshold:
                return False, (
                    f"bus overloaded ({current_load}/{self.max_facts_per_window}), "
                    f"only priority ≤{self.emergency_priority_threshold} accepted"
                )
        else:
            self._emergency_mode = False

        return True, "ok"


# ---------------------------------------------------------------------------
# Priority aging: prevent starvation of low-priority facts
# ---------------------------------------------------------------------------


def apply_aging(fact: Fact, aging_interval_seconds: float = 30.0) -> None:
    """
    Boost effective priority of unclaimed facts over time.
    Every aging_interval_seconds, effective priority improves by 1 level.
    Floor is Priority.HIGH (aging never promotes to CRITICAL — that's reserved).
    """
    if fact.effective_priority is None:
        fact.effective_priority = fact.priority

    age = time.time() - fact.created_at
    boost = int(age / aging_interval_seconds)

    fact.effective_priority = max(Priority.HIGH, fact.priority - boost)


# ---------------------------------------------------------------------------
# Deduplication window
# ---------------------------------------------------------------------------


@dataclass
class DeduplicationWindow:
    """
    Suppress duplicate facts from the same claw within a time window.
    Key: (source_claw_id, fact_type, content_hash)
    """

    window_seconds: float = 10.0
    _seen: dict[str, float] = field(default_factory=dict)

    def is_duplicate(self, fact: Fact) -> bool:
        now = time.time()
        key = f"{fact.source_claw_id}:{fact.fact_type}:{fact.content_hash}"

        # Evict expired entries lazily
        expired = [k for k, t in self._seen.items() if now - t > self.window_seconds]
        for k in expired:
            del self._seen[k]

        if key in self._seen:
            return True

        self._seen[key] = now
        return False


# ---------------------------------------------------------------------------
# Composite gate: run all checks in sequence
# ---------------------------------------------------------------------------


@dataclass
class PublishGate:
    """
    Composite gate that runs all flow control checks before accepting a fact.
    Checks execute in order of cost (cheapest first).
    """

    rate_limiter: ClawRateLimiter = field(default_factory=ClawRateLimiter)
    load_breaker: BusLoadBreaker = field(default_factory=BusLoadBreaker)
    dedup_window: DeduplicationWindow = field(default_factory=DeduplicationWindow)
    # Maps fact_id -> "source_claw_id:fact_type" for behavioral loop detection
    _chain_signatures: dict[str, str] = field(default_factory=dict)

    def check(self, fact: Fact) -> tuple[bool, str]:
        """Run all gates. Returns (accepted, reason)."""

        # 1. Causation depth (O(1), cheapest)
        ok, reason = check_causation_depth(fact)
        if not ok:
            return False, reason

        # 2. Causation cycle detection (O(chain_length))
        ok, reason = check_causation_cycle(fact)
        if not ok:
            return False, reason

        # 3. Behavioral livelock detection (O(chain_length))
        if fact.causation_chain:
            ok, reason = check_behavioral_loop(fact, self._chain_signatures)
            if not ok:
                return False, reason

        # 4. Deduplication (O(1) amortized)
        if self.dedup_window.is_duplicate(fact):
            return False, "duplicate fact within deduplication window"

        # 5. Per-claw rate limit (O(1))
        ok, reason = self.rate_limiter.check(fact.source_claw_id)
        if not ok:
            return False, reason

        # 6. Global bus load (O(n) on window cleanup, amortized O(1))
        ok, reason = self.load_breaker.record_and_check(fact)
        if not ok:
            return False, reason

        # Record signature for future behavioral loop checks
        self._chain_signatures[fact.fact_id] = f"{fact.source_claw_id}:{fact.fact_type}"

        return True, "ok"
