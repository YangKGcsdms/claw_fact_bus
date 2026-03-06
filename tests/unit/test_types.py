"""
Unit tests for core types.
"""

import time

import pytest

from claw_fact_bus.types import (
    AcceptanceFilter,
    BusEvent,
    BusEventType,
    ClawIdentity,
    ClawState,
    Fact,
    FactMode,
    FactState,
    OpCode,
    BusMessage,
    Priority,
)


class TestFact:
    """Tests for Fact dataclass."""

    def test_fact_default_creation(self):
        """Test that Fact can be created with defaults."""
        fact = Fact()
        assert fact.fact_id
        assert len(fact.fact_id) == 16  # UUID hex[:16]
        assert fact.fact_type == ""
        assert fact.payload == {}
        assert fact.priority == Priority.NORMAL
        assert fact.mode == FactMode.EXCLUSIVE
        assert fact.state == FactState.CREATED

    def test_fact_custom_creation(self):
        """Test that Fact can be created with custom values."""
        fact = Fact(
            fact_type="code.review.needed",
            payload={"file": "auth.py"},
            domain_tags=["python", "auth"],
            need_capabilities=["review"],
            priority=Priority.HIGH,
            mode=FactMode.BROADCAST,
            source_claw_id="claw-001",
            ttl_seconds=600,
            confidence=0.9,
        )
        assert fact.fact_type == "code.review.needed"
        assert fact.payload == {"file": "auth.py"}
        assert fact.domain_tags == ["python", "auth"]
        assert fact.need_capabilities == ["review"]
        assert fact.priority == Priority.HIGH
        assert fact.mode == FactMode.BROADCAST
        assert fact.source_claw_id == "claw-001"
        assert fact.ttl_seconds == 600
        assert fact.confidence == 0.9

    def test_fact_content_hash(self):
        """Test content hash computation."""
        fact = Fact(
            fact_type="test",
            payload={"key": "value", "nested": {"a": 1}},
        )
        hash1 = fact.compute_content_hash()
        assert hash1
        assert len(hash1) == 64  # SHA256 hex length

        # Same payload should produce same hash
        fact2 = Fact(
            fact_type="test",
            payload={"key": "value", "nested": {"a": 1}},
        )
        hash2 = fact2.compute_content_hash()
        assert hash1 == hash2

        # Different payload should produce different hash
        fact3 = Fact(
            fact_type="test",
            payload={"key": "different"},
        )
        hash3 = fact3.compute_content_hash()
        assert hash1 != hash3

    def test_fact_expiration(self):
        """Test fact expiration logic."""
        # Expired fact
        old_fact = Fact(
            created_at=time.time() - 1000,
            ttl_seconds=300,
        )
        assert old_fact.is_expired()

        # Non-expired fact
        fresh_fact = Fact(
            created_at=time.time(),
            ttl_seconds=300,
        )
        assert not fresh_fact.is_expired()

    def test_fact_derive_child(self):
        """Test child fact derivation."""
        parent = Fact(
            fact_id="parent-001",
            fact_type="parent",
            causation_chain=["grandparent"],
            causation_depth=1,
            source_claw_id="claw-a",
        )

        child = parent.derive_child(
            fact_type="child",
            payload={"data": "child-data"},
            source_claw_id="claw-b",
        )

        assert child.fact_type == "child"
        assert child.payload == {"data": "child-data"}
        assert child.source_claw_id == "claw-b"
        assert child.causation_chain == ["grandparent", "parent-001"]
        assert child.causation_depth == 2


class TestClawIdentity:
    """Tests for ClawIdentity dataclass."""

    def test_claw_default_creation(self):
        """Test that ClawIdentity can be created with defaults."""
        claw = ClawIdentity()
        assert claw.claw_id
        assert len(claw.claw_id) == 12
        assert claw.name == ""
        assert claw.state == ClawState.OFFLINE
        assert claw.reliability_score == 1.0

    def test_claw_custom_creation(self):
        """Test custom claw creation."""
        claw = ClawIdentity(
            claw_id="test-123",
            name="code-reviewer",
            description="Reviews code",
            acceptance_filter=AcceptanceFilter(
                capability_offer=["review", "python"],
                domain_interests=["backend"],
            ),
            max_concurrent_claims=3,
        )
        assert claw.claw_id == "test-123"
        assert claw.name == "code-reviewer"
        assert claw.acceptance_filter.capability_offer == ["review", "python"]
        assert claw.max_concurrent_claims == 3

    def test_claw_is_healthy(self):
        """Test health check property."""
        assert ClawIdentity(state=ClawState.ACTIVE).is_healthy
        assert ClawIdentity(state=ClawState.DEGRADED).is_healthy
        assert not ClawIdentity(state=ClawState.ISOLATED).is_healthy
        assert not ClawIdentity(state=ClawState.OFFLINE).is_healthy


class TestAcceptanceFilter:
    """Tests for AcceptanceFilter."""

    def test_default_filter(self):
        """Test default filter accepts everything (monitor mode)."""
        af = AcceptanceFilter()
        assert af.capability_offer == []
        assert af.domain_interests == []
        assert af.fact_type_patterns == []
        assert af.priority_range == (Priority.CRITICAL, Priority.BULK)

    def test_custom_filter(self):
        """Test custom filter creation."""
        af = AcceptanceFilter(
            capability_offer=["review", "test"],
            domain_interests=["python", "api"],
            fact_type_patterns=["code.*", "deploy.*"],
            priority_range=(Priority.HIGH, Priority.NORMAL),
            modes=[FactMode.EXCLUSIVE],
        )
        assert af.capability_offer == ["review", "test"]
        assert af.fact_type_patterns == ["code.*", "deploy.*"]


class TestBusMessage:
    """Tests for BusMessage."""

    def test_message_default(self):
        """Test default message creation."""
        msg = BusMessage()
        assert msg.message_id
        assert msg.op == OpCode.HEARTBEAT
        assert msg.success is True
        assert msg.timestamp > 0

    def test_message_with_fact(self):
        """Test message with fact payload."""
        fact = Fact(fact_type="test")
        msg = BusMessage(
            op=OpCode.PUBLISH,
            claw_id="claw-001",
            fact=fact,
        )
        assert msg.op == OpCode.PUBLISH
        assert msg.claw_id == "claw-001"
        assert msg.fact == fact


class TestBusEvent:
    """Tests for BusEvent."""

    def test_event_default(self):
        """Test default event creation."""
        event = BusEvent()
        assert event.event_type == BusEventType.FACT_AVAILABLE
        assert event.timestamp > 0

    def test_event_with_fact(self):
        """Test event with fact."""
        fact = Fact(fact_type="test")
        event = BusEvent(
            event_type=BusEventType.FACT_CLAIMED,
            fact=fact,
            claw_id="claimer-001",
            detail="claimed for processing",
        )
        assert event.event_type == BusEventType.FACT_CLAIMED
        assert event.fact == fact
        assert event.claw_id == "claimer-001"


class TestPriority:
    """Tests for Priority enum."""

    def test_priority_values(self):
        """Test priority values are correctly ordered."""
        assert Priority.CRITICAL == 0
        assert Priority.HIGH == 1
        assert Priority.NORMAL == 3
        assert Priority.BULK == 7
        assert Priority.CRITICAL < Priority.BULK

    def test_priority_comparison(self):
        """Test priority comparison."""
        assert Priority.CRITICAL < Priority.HIGH
        assert Priority.NORMAL > Priority.HIGH
        assert Priority.BULK > Priority.CRITICAL
