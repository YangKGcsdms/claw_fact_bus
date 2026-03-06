"""
Reliability scoring and fault confinement protocol.

Directly modeled after CAN Bus error handling (ISO 11898-1 §6.7):

CAN Error State Machine:
  error-active  (TEC<128, REC<128)  → normal operation, can send active error flags
  error-passive (TEC≥128 or REC≥128) → restricted, can only send passive error flags
  bus-off       (TEC≥256)            → disconnected from bus, must recover

Fact Bus Error State Machine:
  active    (TEC<128)  → normal operation
  degraded  (TEC≥128)  → facts published are marked low-confidence
  isolated  (TEC≥256)  → cannot publish, facts are dropped by bus

Error counter rules (adapted from CAN):
  - Contradiction received:           TEC += 8   (like CAN: transmit error detected)
  - Fact expired without resolution:  TEC += 2   (like CAN: stuff error)
  - Fact rejected by schema:          TEC += 8   (like CAN: form error)
  - Rate limit exceeded:              TEC += 1   (like CAN: overload)
  - Corroboration received:           TEC -= 1   (like CAN: successful transmit)
  - Fact successfully resolved:       TEC -= 1   (like CAN: successful transmit)
  - Successful heartbeat:             TEC -= 1   (gradual recovery, min 0)

Recovery from isolated:
  Like CAN bus-off recovery, requires 128 consecutive successful heartbeats
  (CAN requires 128 occurrences of 11 consecutive recessive bits).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .types import ClawIdentity, ClawState, Fact


class ErrorEvent(IntEnum):
    """Events that affect a claw's error counters."""

    CONTRADICTION = 8  # Another claw disputed this claw's fact
    SCHEMA_VIOLATION = 8  # Published fact failed schema validation
    FACT_EXPIRED = 2  # A fact this claw published expired without resolution
    RATE_EXCEEDED = 1  # This claw exceeded its publish rate limit
    CORROBORATION = -1  # Another claw confirmed this claw's fact
    FACT_RESOLVED = -1  # A fact this claw published was successfully resolved
    HEARTBEAT_OK = -1  # Successful heartbeat (gradual recovery)


# Thresholds (matching CAN spec values)
DEGRADED_THRESHOLD = 128
ISOLATED_THRESHOLD = 256
RECOVERY_HEARTBEATS = 128  # Consecutive clean heartbeats needed to leave isolated


@dataclass
class ReliabilityManager:
    """
    Manages error counters and state transitions for all claws.
    Stateless per call — the claw's state is stored on the ClawIdentity itself.
    """

    def record_event(self, claw: ClawIdentity, event: ErrorEvent) -> ClawState:
        """
        Apply an error event to a claw's counters and transition state if needed.
        Returns the new state.
        """
        if claw.state == ClawState.OFFLINE:
            return ClawState.OFFLINE

        old_tec = claw.transmit_error_counter
        claw.transmit_error_counter = max(0, claw.transmit_error_counter + int(event))
        new_tec = claw.transmit_error_counter

        new_state = self._evaluate_state(claw, old_tec, new_tec)
        claw.state = new_state
        claw.reliability_score = self._compute_reliability(claw)

        return new_state

    def _evaluate_state(
        self, claw: ClawIdentity, old_tec: int, new_tec: int
    ) -> ClawState:
        """CAN-style state machine transitions."""

        if claw.state == ClawState.ISOLATED:
            # Recovery: only possible through sustained clean heartbeats.
            # The claw must accumulate enough negative events to drop below threshold.
            if new_tec < DEGRADED_THRESHOLD:
                return ClawState.ACTIVE
            if new_tec < ISOLATED_THRESHOLD:
                return ClawState.DEGRADED
            return ClawState.ISOLATED

        if new_tec >= ISOLATED_THRESHOLD:
            return ClawState.ISOLATED
        if new_tec >= DEGRADED_THRESHOLD:
            return ClawState.DEGRADED

        return ClawState.ACTIVE

    def _compute_reliability(self, claw: ClawIdentity) -> float:
        """
        Derive a 0.0-1.0 reliability score from error counters.

        Linear interpolation: TEC=0 → 1.0, TEC≥256 → 0.0
        This score is used as a multiplier in arbitration (filter.py).
        """
        tec = claw.transmit_error_counter
        if tec >= ISOLATED_THRESHOLD:
            return 0.0
        return max(0.0, 1.0 - (tec / ISOLATED_THRESHOLD))

    def should_accept_publication(self, claw: ClawIdentity, fact: Fact) -> tuple[bool, str]:
        """
        Gate check before accepting a fact from a claw.
        Returns (accepted, reason).
        """
        if claw.state == ClawState.ISOLATED:
            return False, "claw is isolated (bus-off equivalent)"

        if claw.state == ClawState.OFFLINE:
            return False, "claw is not connected"

        if claw.state == ClawState.DEGRADED:
            fact.confidence = min(fact.confidence, 0.3)

        return True, "ok"
