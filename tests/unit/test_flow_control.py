"""
Unit tests for flow control and storm protection.
"""

import time

import pytest

from claw_fact_bus.flow_control import (
    MAX_CAUSATION_DEPTH,
    BusLoadBreaker,
    ClawRateLimiter,
    DeduplicationWindow,
    PublishGate,
    TokenBucket,
    apply_aging,
    check_causation_cycle,
    check_causation_depth,
)
from claw_fact_bus.types import Fact, Priority


class TestCausationDepth:
    """Tests for causation depth breaker."""

    def test_within_limit_passes(self):
        """Test fact within depth limit passes."""
        fact = Fact(causation_depth=10)
        ok, reason = check_causation_depth(fact)
        assert ok is True

    def test_at_limit_passes(self):
        """Test fact at depth limit passes."""
        fact = Fact(causation_depth=MAX_CAUSATION_DEPTH)
        ok, reason = check_causation_depth(fact)
        assert ok is True

    def test_over_limit_fails(self):
        """Test fact over depth limit fails."""
        fact = Fact(causation_depth=MAX_CAUSATION_DEPTH + 1)
        ok, reason = check_causation_depth(fact)
        assert ok is False
        assert "depth" in reason


class TestCausationCycle:
    """Tests for causation cycle detection."""

    def test_no_cycle_passes(self):
        """Test valid chain without cycle."""
        fact = Fact(
            fact_id="fact-003",
            causation_chain=["fact-001", "fact-002"],
        )
        ok, reason = check_causation_cycle(fact)
        assert ok is True

    def test_self_reference_cycle(self):
        """Test detection of self-reference cycle."""
        fact = Fact(
            fact_id="fact-001",
            causation_chain=["fact-001"],  # References itself
        )
        ok, reason = check_causation_cycle(fact)
        assert ok is False
        assert "cycle" in reason


class TestTokenBucket:
    """Tests for token bucket rate limiter."""

    def test_initial_capacity(self):
        """Test bucket starts with full capacity."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        assert bucket.tokens == 10

    def test_consume_reduces_tokens(self):
        """Test that consuming reduces tokens."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        bucket.try_consume(5)
        assert bucket.tokens == 5

    def test_consume_fails_when_empty(self):
        """Test consumption fails when bucket is empty."""
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        bucket.try_consume(5)  # Empty the bucket
        result = bucket.try_consume(1)
        assert result is False

    def test_refill_over_time(self):
        """Test tokens refill over time."""
        bucket = TokenBucket(capacity=10, refill_rate=10.0)  # 10 tokens/sec
        bucket.try_consume(10)  # Empty
        time.sleep(0.2)  # Wait 200ms
        bucket.try_consume(1)  # This will trigger refill
        assert bucket.tokens >= 1


class TestClawRateLimiter:
    """Tests for per-claw rate limiting."""

    def test_first_request_allowed(self):
        """Test first request is always allowed."""
        limiter = ClawRateLimiter()
        ok, reason = limiter.check("claw-001")
        assert ok is True

    def test_burst_limit(self):
        """Test burst limit enforcement."""
        limiter = ClawRateLimiter(default_capacity=5, default_refill_rate=1.0)

        # First 5 should pass
        for _ in range(5):
            ok, _ = limiter.check("claw-001")
            assert ok is True

        # 6th should fail
        ok, reason = limiter.check("claw-001")
        assert ok is False
        assert "rate limit" in reason


class TestBusLoadBreaker:
    """Tests for global bus load breaker."""

    def test_normal_load_passes(self):
        """Test normal load passes."""
        breaker = BusLoadBreaker(max_facts_per_window=100)
        fact = Fact(priority=Priority.NORMAL)

        ok, reason = breaker.record_and_check(fact)
        assert ok is True

    def test_emergency_mode_allows_critical(self):
        """Test emergency mode allows critical facts."""
        breaker = BusLoadBreaker(
            max_facts_per_window=2,
            emergency_priority_threshold=Priority.HIGH,
        )

        # Exceed limit
        for _ in range(3):
            breaker.record_and_check(Fact(priority=Priority.NORMAL))

        assert breaker.is_emergency

        # Critical facts should still pass
        critical_fact = Fact(priority=Priority.CRITICAL)
        ok, reason = breaker.record_and_check(critical_fact)
        assert ok is True

    def test_emergency_mode_blocks_low_priority(self):
        """Test emergency mode blocks low priority facts."""
        breaker = BusLoadBreaker(
            max_facts_per_window=2,
            emergency_priority_threshold=Priority.HIGH,
        )

        # Exceed limit
        for _ in range(3):
            breaker.record_and_check(Fact(priority=Priority.NORMAL))

        assert breaker.is_emergency

        # Low priority should be blocked
        low_fact = Fact(priority=Priority.BULK)
        ok, reason = breaker.record_and_check(low_fact)
        assert ok is False
        assert "overloaded" in reason


class TestDeduplicationWindow:
    """Tests for deduplication window."""

    def test_first_occurrence_not_duplicate(self):
        """Test first occurrence is not duplicate."""
        window = DeduplicationWindow()
        fact = Fact(
            source_claw_id="claw-001",
            fact_type="test",
            content_hash="hash123",
        )
        assert window.is_duplicate(fact) is False

    def test_same_fact_is_duplicate(self):
        """Test same fact is duplicate within window."""
        window = DeduplicationWindow()
        fact = Fact(
            source_claw_id="claw-001",
            fact_type="test",
            content_hash="hash123",
        )
        window.is_duplicate(fact)  # First call
        assert window.is_duplicate(fact) is True  # Second call

    def test_different_facts_not_duplicate(self):
        """Test different facts are not duplicates."""
        window = DeduplicationWindow()
        fact1 = Fact(
            source_claw_id="claw-001",
            fact_type="test",
            content_hash="hash123",
        )
        fact2 = Fact(
            source_claw_id="claw-001",
            fact_type="other",
            content_hash="hash456",
        )
        window.is_duplicate(fact1)
        assert window.is_duplicate(fact2) is False


class TestPublishGate:
    """Tests for composite publish gate."""

    def test_valid_fact_passes(self):
        """Test valid fact passes all gates."""
        gate = PublishGate()
        fact = Fact(
            source_claw_id="claw-001",
            causation_depth=5,
        )
        ok, reason = gate.check(fact)
        assert ok is True

    def test_deep_fact_fails(self):
        """Test fact exceeding depth limit fails."""
        gate = PublishGate()
        fact = Fact(
            source_claw_id="claw-001",
            causation_depth=MAX_CAUSATION_DEPTH + 1,
        )
        ok, reason = gate.check(fact)
        assert ok is False
        assert "depth" in reason

    def test_cyclic_fact_fails(self):
        """Test cyclic fact fails."""
        gate = PublishGate()
        fact = Fact(
            fact_id="fact-001",
            source_claw_id="claw-001",
            causation_chain=["fact-001"],  # Self-reference
        )
        ok, reason = gate.check(fact)
        assert ok is False
        assert "cycle" in reason


class TestPriorityAging:
    """Tests for priority aging mechanism."""

    def test_aging_increases_priority(self):
        """Test that aging increases effective priority."""
        fact = Fact(
            priority=Priority.BULK,  # 7
            created_at=time.time() - 100,  # 100 seconds old
        )
        apply_aging(fact, aging_interval_seconds=30.0)

        # Should have aged by ~3 levels (100/30 ≈ 3)
        assert fact.effective_priority < Priority.BULK

    def test_aging_floor(self):
        """Test aging doesn't go below HIGH."""
        fact = Fact(
            priority=Priority.BULK,
            created_at=time.time() - 1000,  # Very old
        )
        apply_aging(fact, aging_interval_seconds=30.0)

        # Floor is HIGH (1), not CRITICAL (0)
        assert fact.effective_priority >= Priority.HIGH

    def test_fresh_fact_no_aging(self):
        """Test fresh fact doesn't age."""
        fact = Fact(
            priority=Priority.NORMAL,
            created_at=time.time(),
        )
        apply_aging(fact)
        assert fact.effective_priority == Priority.NORMAL
