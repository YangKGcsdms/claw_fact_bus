"""
Unit tests for filter matching and arbitration.
"""

import pytest

from claw_fact_bus.filter import MatchResult, arbitrate, evaluate_filter
from claw_fact_bus.types import (
    AcceptanceFilter,
    ClawIdentity,
    ClawState,
    Fact,
    FactMode,
    Priority,
)


class TestEvaluateFilter:
    """Tests for filter evaluation."""

    def test_basic_capability_match(self):
        """Test basic capability matching."""
        fact = Fact(
            need_capabilities=["review", "security"],
            priority=Priority.NORMAL,
            mode=FactMode.EXCLUSIVE,
        )
        claw = ClawIdentity(
            state=ClawState.ACTIVE,
            acceptance_filter=AcceptanceFilter(
                capability_offer=["review", "python"],
            ),
        )

        result = evaluate_filter(fact, claw)
        assert result.matched is True
        assert result.capability_overlap == 1  # "review" matches

    def test_capability_mismatch(self):
        """Test when capabilities don't match."""
        fact = Fact(
            need_capabilities=["deploy"],
            priority=Priority.NORMAL,
            mode=FactMode.EXCLUSIVE,
        )
        claw = ClawIdentity(
            state=ClawState.ACTIVE,
            acceptance_filter=AcceptanceFilter(
                capability_offer=["review", "test"],
                domain_interests=["python"],
            ),
        )

        result = evaluate_filter(fact, claw)
        # Should not match because no capability overlap
        assert result.matched is False

    def test_domain_match(self):
        """Test domain tag matching."""
        fact = Fact(
            domain_tags=["python", "auth"],
            priority=Priority.NORMAL,
            mode=FactMode.EXCLUSIVE,
        )
        claw = ClawIdentity(
            state=ClawState.ACTIVE,
            acceptance_filter=AcceptanceFilter(
                domain_interests=["auth", "security"],
            ),
        )

        result = evaluate_filter(fact, claw)
        assert result.matched is True
        assert result.domain_overlap == 1  # "auth" matches

    def test_fact_type_pattern_match(self):
        """Test glob pattern matching for fact types."""
        fact = Fact(
            fact_type="code.review.needed",
            priority=Priority.NORMAL,
            mode=FactMode.EXCLUSIVE,
        )
        claw = ClawIdentity(
            state=ClawState.ACTIVE,
            acceptance_filter=AcceptanceFilter(
                fact_type_patterns=["code.*", "review.*"],
            ),
        )

        result = evaluate_filter(fact, claw)
        assert result.matched is True
        assert result.type_pattern_hit is True

    def test_priority_range_filter(self):
        """Test priority range filtering."""
        fact_high = Fact(
            need_capabilities=["review"],
            priority=Priority.HIGH,  # 1
            mode=FactMode.EXCLUSIVE,
        )
        fact_bulk = Fact(
            need_capabilities=["review"],
            priority=Priority.BULK,  # 7
            mode=FactMode.EXCLUSIVE,
        )
        claw = ClawIdentity(
            state=ClawState.ACTIVE,
            acceptance_filter=AcceptanceFilter(
                capability_offer=["review"],
                priority_range=(Priority.CRITICAL, Priority.NORMAL),  # 0-3
            ),
        )

        result_high = evaluate_filter(fact_high, claw)
        result_bulk = evaluate_filter(fact_bulk, claw)

        assert result_high.matched is True  # HIGH (1) is in range 0-3
        assert result_bulk.matched is False  # BULK (7) is not in range 0-3

    def test_mode_filter(self):
        """Test mode filtering."""
        fact_broadcast = Fact(
            need_capabilities=["review"],
            priority=Priority.NORMAL,
            mode=FactMode.BROADCAST,
        )
        claw_exclusive_only = ClawIdentity(
            state=ClawState.ACTIVE,
            acceptance_filter=AcceptanceFilter(
                capability_offer=["review"],
                modes=[FactMode.EXCLUSIVE],
            ),
        )
        claw_both_modes = ClawIdentity(
            state=ClawState.ACTIVE,
            acceptance_filter=AcceptanceFilter(
                capability_offer=["review"],
                modes=[FactMode.EXCLUSIVE, FactMode.BROADCAST],
            ),
        )

        result1 = evaluate_filter(fact_broadcast, claw_exclusive_only)
        result2 = evaluate_filter(fact_broadcast, claw_both_modes)

        assert result1.matched is False
        assert result2.matched is True

    def test_isolated_claw_receives_nothing(self):
        """Test that isolated claws receive no facts."""
        fact = Fact(
            need_capabilities=["review"],
            priority=Priority.NORMAL,
            mode=FactMode.EXCLUSIVE,
        )
        claw = ClawIdentity(
            state=ClawState.ISOLATED,
            acceptance_filter=AcceptanceFilter(
                capability_offer=["review"],
            ),
        )

        result = evaluate_filter(fact, claw)
        assert result.matched is False

    def test_offline_claw_receives_nothing(self):
        """Test that offline claws receive no facts."""
        fact = Fact(
            need_capabilities=["review"],
            priority=Priority.NORMAL,
            mode=FactMode.EXCLUSIVE,
        )
        claw = ClawIdentity(
            state=ClawState.OFFLINE,
            acceptance_filter=AcceptanceFilter(
                capability_offer=["review"],
            ),
        )

        result = evaluate_filter(fact, claw)
        assert result.matched is False

    def test_empty_filter_is_monitor_mode(self):
        """Test that empty filter acts as monitor (receives everything)."""
        fact = Fact(
            fact_type="anything",
            priority=Priority.NORMAL,
            mode=FactMode.BROADCAST,
        )
        claw = ClawIdentity(
            state=ClawState.ACTIVE,
            acceptance_filter=AcceptanceFilter(),  # Empty
        )

        result = evaluate_filter(fact, claw)
        assert result.matched is True

    def test_multiple_content_matches(self):
        """Test matching across multiple dimensions."""
        fact = Fact(
            fact_type="code.test.needed",
            need_capabilities=["test", "python"],
            domain_tags=["backend", "api"],
            priority=Priority.NORMAL,
            mode=FactMode.EXCLUSIVE,
        )
        claw = ClawIdentity(
            state=ClawState.ACTIVE,
            acceptance_filter=AcceptanceFilter(
                capability_offer=["test", "review"],
                domain_interests=["backend"],
                fact_type_patterns=["code.*"],
            ),
        )

        result = evaluate_filter(fact, claw)
        assert result.matched is True
        assert result.capability_overlap == 1  # "test"
        assert result.domain_overlap == 1  # "backend"
        assert result.type_pattern_hit is True
        assert result.score > 0


class TestArbitrate:
    """Tests for arbitration logic."""

    def test_broadcast_mode_all_match(self):
        """Test that broadcast facts go to all matched claws."""
        fact = Fact(
            need_capabilities=["review"],
            mode=FactMode.BROADCAST,
        )
        claws = [
            ClawIdentity(
                claw_id="c1",
                state=ClawState.ACTIVE,
                acceptance_filter=AcceptanceFilter(capability_offer=["review"]),
            ),
            ClawIdentity(
                claw_id="c2",
                state=ClawState.ACTIVE,
                acceptance_filter=AcceptanceFilter(capability_offer=["review"]),
            ),
        ]

        winners = arbitrate(fact, claws)
        assert len(winners) == 2
        assert winners[0].claw_id in ["c1", "c2"]
        assert winners[1].claw_id in ["c1", "c2"]

    def test_exclusive_mode_single_winner(self):
        """Test that exclusive facts have exactly one winner."""
        fact = Fact(
            need_capabilities=["review"],
            domain_tags=["python"],
            mode=FactMode.EXCLUSIVE,
        )
        claws = [
            ClawIdentity(
                claw_id="c1",
                state=ClawState.ACTIVE,
                acceptance_filter=AcceptanceFilter(
                    capability_offer=["review"],
                    domain_interests=["python"],
                ),
            ),
            ClawIdentity(
                claw_id="c2",
                state=ClawState.ACTIVE,
                acceptance_filter=AcceptanceFilter(
                    capability_offer=["review"],
                ),
            ),
        ]

        winners = arbitrate(fact, claws)
        assert len(winners) == 1
        # c1 wins: capability(10) + domain(5) = 15 vs c2's capability-only(10)
        assert winners[0].claw_id == "c1"

    def test_exclusive_mode_no_matches(self):
        """Test arbitration with no matching claws."""
        fact = Fact(
            need_capabilities=["deploy"],
            mode=FactMode.EXCLUSIVE,
        )
        claws = [
            ClawIdentity(
                claw_id="c1",
                state=ClawState.ACTIVE,
                acceptance_filter=AcceptanceFilter(capability_offer=["review"]),
            ),
        ]

        winners = arbitrate(fact, claws)
        assert len(winners) == 0

    def test_exclusive_mode_reliability_tiebreaker(self):
        """Test that reliability score breaks ties."""
        fact = Fact(
            need_capabilities=["review"],
            mode=FactMode.EXCLUSIVE,
        )
        claws = [
            ClawIdentity(
                claw_id="c1",
                state=ClawState.ACTIVE,
                acceptance_filter=AcceptanceFilter(capability_offer=["review"]),
                reliability_score=0.5,  # Less reliable
            ),
            ClawIdentity(
                claw_id="c2",
                state=ClawState.ACTIVE,
                acceptance_filter=AcceptanceFilter(capability_offer=["review"]),
                reliability_score=1.0,  # More reliable
            ),
        ]

        winners = arbitrate(fact, claws)
        assert len(winners) == 1
        # c2 wins due to higher reliability score
        assert winners[0].claw_id == "c2"

    def test_empty_candidates(self):
        """Test arbitration with empty candidate list."""
        fact = Fact(mode=FactMode.EXCLUSIVE)
        winners = arbitrate(fact, [])
        assert winners == []
