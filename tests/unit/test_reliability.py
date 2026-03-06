"""
Unit tests for reliability and fault confinement.
"""

import pytest

from claw_fact_bus.reliability import (
    DEGRADED_THRESHOLD,
    ISOLATED_THRESHOLD,
    ErrorEvent,
    ReliabilityManager,
)
from claw_fact_bus.types import ClawIdentity, ClawState, Fact, Priority


class TestReliabilityManager:
    """Tests for reliability management."""

    def test_healthy_claw_stays_active(self):
        """Test that healthy claw remains active."""
        claw = ClawIdentity(state=ClawState.ACTIVE, transmit_error_counter=10)
        manager = ReliabilityManager()

        new_state = manager.record_event(claw, ErrorEvent.HEARTBEAT_OK)

        assert new_state == ClawState.ACTIVE
        assert claw.transmit_error_counter == 9  # Decremented

    def test_contradiction_increases_tec(self):
        """Test that contradiction increases TEC significantly."""
        claw = ClawIdentity(state=ClawState.ACTIVE, transmit_error_counter=10)
        manager = ReliabilityManager()

        new_state = manager.record_event(claw, ErrorEvent.CONTRADICTION)

        assert claw.transmit_error_counter == 18  # +8

    def test_degraded_transition(self):
        """Test transition to degraded state."""
        claw = ClawIdentity(
            state=ClawState.ACTIVE,
            transmit_error_counter=DEGRADED_THRESHOLD - 10,
        )
        manager = ReliabilityManager()

        # Add enough errors to cross threshold
        new_state = manager.record_event(claw, ErrorEvent.CONTRADICTION)  # +8
        new_state = manager.record_event(claw, ErrorEvent.CONTRADICTION)  # +8

        assert new_state == ClawState.DEGRADED
        assert claw.state == ClawState.DEGRADED

    def test_isolated_transition(self):
        """Test transition to isolated state."""
        claw = ClawIdentity(
            state=ClawState.DEGRADED,
            transmit_error_counter=DEGRADED_THRESHOLD + 100,
        )
        manager = ReliabilityManager()

        # Add enough errors to cross isolated threshold
        for _ in range(20):
            new_state = manager.record_event(claw, ErrorEvent.CONTRADICTION)

        assert new_state == ClawState.ISOLATED
        assert claw.state == ClawState.ISOLATED

    def test_recovery_from_isolated(self):
        """Test recovery from isolated state via heartbeats."""
        claw = ClawIdentity(
            state=ClawState.ISOLATED,
            transmit_error_counter=ISOLATED_THRESHOLD,
        )
        manager = ReliabilityManager()

        # Send many heartbeats to recover
        for _ in range(256):
            new_state = manager.record_event(claw, ErrorEvent.HEARTBEAT_OK)

        assert new_state == ClawState.ACTIVE
        assert claw.transmit_error_counter == 0

    def test_tec_floor_at_zero(self):
        """Test that TEC never goes below zero."""
        claw = ClawIdentity(state=ClawState.ACTIVE, transmit_error_counter=0)
        manager = ReliabilityManager()

        # Send many heartbeats
        for _ in range(10):
            new_state = manager.record_event(claw, ErrorEvent.HEARTBEAT_OK)

        assert claw.transmit_error_counter == 0

    def test_reliability_score_calculation(self):
        """Test reliability score calculation."""
        claw = ClawIdentity(state=ClawState.ACTIVE, transmit_error_counter=0)
        manager = ReliabilityManager()

        # Initial score should be 1.0
        assert claw.reliability_score == 1.0

        # Add errors
        manager.record_event(claw, ErrorEvent.CONTRADICTION)  # +8
        assert claw.reliability_score < 1.0

        # At isolated threshold
        claw.transmit_error_counter = ISOLATED_THRESHOLD
        score = manager._compute_reliability(claw)
        assert score == 0.0

    def test_should_accept_publication(self):
        """Test publication acceptance gate."""
        claw = ClawIdentity(state=ClawState.ACTIVE)
        fact = Fact(priority=Priority.NORMAL, confidence=1.0)
        manager = ReliabilityManager()

        accepted, reason = manager.should_accept_publication(claw, fact)
        assert accepted is True

    def test_isolated_claw_cannot_publish(self):
        """Test that isolated claws cannot publish."""
        claw = ClawIdentity(state=ClawState.ISOLATED)
        fact = Fact()
        manager = ReliabilityManager()

        accepted, reason = manager.should_accept_publication(claw, fact)
        assert accepted is False
        assert "isolated" in reason

    def test_degraded_claw_reduced_confidence(self):
        """Test that degraded claws have reduced confidence."""
        claw = ClawIdentity(state=ClawState.DEGRADED)
        fact = Fact(confidence=1.0)
        manager = ReliabilityManager()

        manager.should_accept_publication(claw, fact)
        assert fact.confidence <= 0.3

    def test_corroboration_decreases_tec(self):
        """Test that corroboration decreases TEC."""
        claw = ClawIdentity(
            state=ClawState.ACTIVE,
            transmit_error_counter=100,
        )
        manager = ReliabilityManager()

        manager.record_event(claw, ErrorEvent.CORROBORATION)

        assert claw.transmit_error_counter == 99

    def test_fact_resolved_decreases_tec(self):
        """Test that successful resolution decreases TEC."""
        claw = ClawIdentity(
            state=ClawState.ACTIVE,
            transmit_error_counter=100,
        )
        manager = ReliabilityManager()

        manager.record_event(claw, ErrorEvent.FACT_RESOLVED)

        assert claw.transmit_error_counter == 99
