"""
Integration tests for Bus Engine.
"""

import asyncio
import tempfile

import pytest

from claw_fact_bus.server.bus_engine import BusEngine
from claw_fact_bus.types import (
    AcceptanceFilter,
    BusEvent,
    BusEventType,
    ClawIdentity,
    ClawState,
    Fact,
    FactMode,
    FactState,
    Priority,
)


@pytest.fixture
async def temp_engine():
    """Create a temporary bus engine for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = BusEngine(data_dir=tmpdir)
        yield engine
        # Cleanup
        for task in engine._background_tasks:
            task.cancel()


def make_test_claw() -> ClawIdentity:
    """Create a test claw identity."""
    return ClawIdentity(
        claw_id="test-claw-001",
        name="test-claw",
        acceptance_filter=AcceptanceFilter(
            capability_offer=["review", "test"],
            domain_interests=["python"],
        ),
    )


class TestClawLifecycle:
    """Tests for claw connection lifecycle."""

    @pytest.mark.asyncio
    async def test_claw_connect(self, temp_engine):
        """Test claw connection."""
        engine = temp_engine
        claw = make_test_claw()
        events = []

        def event_handler(cid, event):
            events.append((cid, event))

        identity = await engine.connect_claw(claw.claw_id, claw, event_handler)

        assert identity.claw_id in engine._claws
        assert engine._claws[identity.claw_id].state == ClawState.ACTIVE

    @pytest.mark.asyncio
    async def test_claw_disconnect(self, temp_engine):
        """Test claw disconnection."""
        engine = temp_engine
        claw = make_test_claw()

        await engine.connect_claw(claw.claw_id, claw, lambda c, e: None)
        assert claw.claw_id in engine._claws

        await engine.disconnect_claw(claw.claw_id)
        assert claw.claw_id not in engine._claws

    @pytest.mark.asyncio
    async def test_heartbeat_updates_state(self, temp_engine):
        """Test heartbeat updates claw state."""
        engine = temp_engine
        claw = make_test_claw()

        await engine.connect_claw(claw.claw_id, claw, lambda c, e: None)
        state = await engine.heartbeat(claw.claw_id)

        assert state == ClawState.ACTIVE
        assert engine._claws[claw.claw_id].last_heartbeat > 0


class TestFactPublishing:
    """Tests for fact publishing flow."""

    @pytest.mark.asyncio
    async def test_publish_fact_success(self, temp_engine):
        """Test successful fact publishing."""
        engine = temp_engine

        fact = Fact(
            fact_type="test.fact",
            payload={"key": "value"},
            source_claw_id="claw-001",
        )

        success, reason, fact_id = await engine.publish_fact(fact)

        assert success is True
        assert fact_id is not None
        assert fact_id in engine._facts
        assert engine._facts[fact_id].state == FactState.PUBLISHED

    @pytest.mark.asyncio
    async def test_publish_fact_with_claw(self, temp_engine):
        """Test fact publishing from a connected claw."""
        engine = temp_engine
        claw = make_test_claw()

        await engine.connect_claw(claw.claw_id, claw, lambda c, e: None)

        fact = Fact(
            fact_type="test.fact",
            payload={"key": "value"},
            source_claw_id=claw.claw_id,
        )

        success, reason, fact_id = await engine.publish_fact(fact)

        assert success is True
        assert fact_id in engine._facts

    @pytest.mark.asyncio
    async def test_publish_too_deep_fact_fails(self, temp_engine):
        """Test deep causation chain is rejected."""
        engine = temp_engine

        fact = Fact(
            fact_type="test.fact",
            source_claw_id="claw-001",
            causation_depth=20,  # Exceeds limit of 16
        )

        success, reason, fact_id = await engine.publish_fact(fact)

        assert success is False
        assert "depth" in reason


class TestFactClaiming:
    """Tests for fact claiming workflow."""

    @pytest.mark.asyncio
    async def test_claim_exclusive_fact(self, temp_engine):
        """Test claiming an exclusive fact."""
        engine = temp_engine
        claw = make_test_claw()

        await engine.connect_claw(claw.claw_id, claw, lambda c, e: None)

        # Publish a fact that matches the claw
        fact = Fact(
            fact_type="test.fact",
            need_capabilities=["review"],
            source_claw_id="other-claw",
            mode=FactMode.EXCLUSIVE,
        )
        success, _, fact_id = await engine.publish_fact(fact)
        assert success is True

        # Claim the fact
        claim_success, reason = await engine.claim_fact(fact_id, claw.claw_id)

        assert claim_success is True
        assert engine._facts[fact_id].state == FactState.CLAIMED
        assert engine._facts[fact_id].claimed_by == claw.claw_id

    @pytest.mark.asyncio
    async def test_claim_already_claimed_fails(self, temp_engine):
        """Test claiming an already claimed fact fails."""
        engine = temp_engine
        claw1 = make_test_claw()
        claw2 = make_test_claw()
        claw2.claw_id = "test-claw-002"

        await engine.connect_claw(claw1.claw_id, claw1, lambda c, e: None)
        await engine.connect_claw(claw2.claw_id, claw2, lambda c, e: None)

        fact = Fact(
            fact_type="test.fact",
            need_capabilities=["review"],
            source_claw_id="other-claw",
            mode=FactMode.EXCLUSIVE,
        )
        success, _, fact_id = await engine.publish_fact(fact)

        # First claw claims
        await engine.claim_fact(fact_id, claw1.claw_id)

        # Second claw tries to claim
        claim_success, reason = await engine.claim_fact(fact_id, claw2.claw_id)

        assert claim_success is False
        assert claw1.claw_id in reason

    @pytest.mark.asyncio
    async def test_claim_non_exclusive_fails(self, temp_engine):
        """Test claiming a broadcast fact fails."""
        engine = temp_engine
        claw = make_test_claw()

        await engine.connect_claw(claw.claw_id, claw, lambda c, e: None)

        fact = Fact(
            fact_type="test.fact",
            need_capabilities=["review"],
            source_claw_id="other-claw",
            mode=FactMode.BROADCAST,  # Not exclusive
        )
        success, _, fact_id = await engine.publish_fact(fact)

        claim_success, reason = await engine.claim_fact(fact_id, claw.claw_id)

        assert claim_success is False
        assert "not exclusive" in reason


class TestFactResolution:
    """Tests for fact resolution."""

    @pytest.mark.asyncio
    async def test_resolve_claimed_fact(self, temp_engine):
        """Test resolving a claimed fact."""
        engine = temp_engine
        claw = make_test_claw()

        await engine.connect_claw(claw.claw_id, claw, lambda c, e: None)

        fact = Fact(
            fact_type="test.fact",
            need_capabilities=["review"],
            source_claw_id="other-claw",
            mode=FactMode.EXCLUSIVE,
        )
        success, _, fact_id = await engine.publish_fact(fact)
        await engine.claim_fact(fact_id, claw.claw_id)

        # Resolve
        resolve_success, reason = await engine.resolve_fact(fact_id, claw.claw_id)

        assert resolve_success is True
        assert engine._facts[fact_id].state == FactState.RESOLVED

    @pytest.mark.asyncio
    async def test_resolve_with_child_facts(self, temp_engine):
        """Test resolution with child facts."""
        engine = temp_engine
        claw = make_test_claw()

        await engine.connect_claw(claw.claw_id, claw, lambda c, e: None)

        parent_fact = Fact(
            fact_type="code.review.needed",
            need_capabilities=["review"],
            payload={"file": "main.py"},
            source_claw_id="other-claw",
            mode=FactMode.EXCLUSIVE,
        )
        success, _, parent_id = await engine.publish_fact(parent_fact)
        await engine.claim_fact(parent_id, claw.claw_id)

        child_facts = [
            Fact(fact_type="code.review.completed", payload={"file": "main.py", "issues": 0}),
        ]

        await engine.resolve_fact(parent_id, claw.claw_id, child_facts)

        # Parent should be resolved
        assert engine._facts[parent_id].state == FactState.RESOLVED

        # Child should be published with causation chain
        children = [f for f in engine._facts.values() if f.fact_type == "code.review.completed"]
        assert len(children) == 1
        assert parent_id in children[0].causation_chain

    @pytest.mark.asyncio
    async def test_resolve_not_claimed_fails(self, temp_engine):
        """Test resolving a fact not claimed by you fails."""
        engine = temp_engine
        claw = make_test_claw()

        fact = Fact(
            fact_type="test.fact",
            need_capabilities=["review"],
            source_claw_id="other-claw",
            mode=FactMode.EXCLUSIVE,
        )
        success, _, fact_id = await engine.publish_fact(fact)

        # Try to resolve without claiming
        resolve_success, reason = await engine.resolve_fact(fact_id, claw.claw_id)

        assert resolve_success is False


class TestEventDispatch:
    """Tests for event dispatching."""

    @pytest.mark.asyncio
    async def test_fact_available_event(self, temp_engine):
        """Test FACT_AVAILABLE event is dispatched."""
        engine = temp_engine
        claw = make_test_claw()
        events = []

        def event_handler(cid, event):
            if event.event_type == BusEventType.FACT_AVAILABLE:
                events.append(event)

        await engine.connect_claw(claw.claw_id, claw, event_handler)

        # Publish a matching fact
        fact = Fact(
            fact_type="test.fact",
            need_capabilities=["review"],
            source_claw_id="other-claw",
        )
        await engine.publish_fact(fact)

        # Allow async event dispatch to complete
        await asyncio.sleep(0.1)

        assert len(events) == 1
        assert events[0].fact.fact_type == "test.fact"

    @pytest.mark.asyncio
    async def test_fact_claimed_event(self, temp_engine):
        """Test FACT_CLAIMED event is dispatched."""
        engine = temp_engine
        claw1 = make_test_claw()
        claw2 = make_test_claw()
        claw2.claw_id = "test-claw-002"

        events = []

        def event_handler(cid, event):
            if cid == claw2.claw_id:  # Only collect for claw2
                events.append(event)

        await engine.connect_claw(claw1.claw_id, claw1, event_handler)
        await engine.connect_claw(claw2.claw_id, claw2, event_handler)

        fact = Fact(
            fact_type="test.fact",
            need_capabilities=["review"],
            source_claw_id="other-claw",
            mode=FactMode.EXCLUSIVE,
        )
        success, _, fact_id = await engine.publish_fact(fact)
        await engine.claim_fact(fact_id, claw1.claw_id)

        await asyncio.sleep(0.1)

        claim_events = [e for e in events if e.event_type == BusEventType.FACT_CLAIMED]
        assert len(claim_events) == 1
        assert claim_events[0].claw_id == claw1.claw_id


class TestQuery:
    """Tests for fact querying."""

    @pytest.mark.asyncio
    async def test_query_by_state(self, temp_engine):
        """Test querying facts by state."""
        engine = temp_engine

        # Publish some facts
        fact1 = Fact(fact_type="test.1", source_claw_id="c1")
        fact2 = Fact(fact_type="test.2", source_claw_id="c1")

        await engine.publish_fact(fact1)
        await engine.publish_fact(fact2)

        # Claim one
        await engine.claim_fact(fact1.fact_id, "claimer")

        # Query by state
        matched_facts = engine.query_facts(state=FactState.CLAIMED)
        assert len(matched_facts) == 1
        assert matched_facts[0].fact_type == "test.1"

    @pytest.mark.asyncio
    async def test_query_by_type(self, temp_engine):
        """Test querying facts by type."""
        engine = temp_engine

        fact1 = Fact(fact_type="code.review.needed", payload={"file": "main.py"}, source_claw_id="c1")
        fact2 = Fact(fact_type="code.test.needed", source_claw_id="c1")

        await engine.publish_fact(fact1)
        await engine.publish_fact(fact2)

        matched_facts = engine.query_facts(fact_type="code.review.needed")
        assert len(matched_facts) == 1
        assert matched_facts[0].fact_type == "code.review.needed"


class TestCorroborateContradict:
    """Tests for trust system."""

    @pytest.mark.asyncio
    async def test_corroborate_increases_reliability(self, temp_engine):
        """Test corroboration increases reliability."""
        engine = temp_engine
        claw = make_test_claw()
        claw.transmit_error_counter = 100

        await engine.connect_claw(claw.claw_id, claw, lambda c, e: None)

        fact = Fact(fact_type="test", source_claw_id=claw.claw_id)
        success, _, fact_id = await engine.publish_fact(fact)

        tec_before = claw.transmit_error_counter
        await engine.corroborate_fact(fact_id, "other-claw")

        assert claw.transmit_error_counter < tec_before

    @pytest.mark.asyncio
    async def test_contradict_decreases_reliability(self, temp_engine):
        """Test contradiction decreases reliability."""
        engine = temp_engine
        claw = make_test_claw()

        await engine.connect_claw(claw.claw_id, claw, lambda c, e: None)

        fact = Fact(fact_type="test", source_claw_id=claw.claw_id)
        success, _, fact_id = await engine.publish_fact(fact)

        tec_before = claw.transmit_error_counter
        await engine.contradict_fact(fact_id, "other-claw")

        assert claw.transmit_error_counter > tec_before
