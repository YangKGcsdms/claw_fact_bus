"""
Fact Bus Handlers for OpenClaw Integration.

Provides a framework for processing facts received from the Fact Bus.
Supports custom handlers for different fact types and semantic kinds.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .fact_bus_client import Fact, FactBusClient, Priority


class FactHandler(Protocol):
    """Protocol for fact handlers."""

    def can_handle(self, fact: Fact) -> bool:
        """Check if this handler can process the fact."""
        ...

    def handle(self, fact: Fact, client: FactBusClient) -> list[dict] | None:
        """
        Process the fact and return optional child facts.

        Returns:
            List of child facts to publish, or None.
        """
        ...


@dataclass
class HandlerRule:
    """A rule for matching and handling facts."""

    fact_type_pattern: str = "*"
    semantic_kinds: list[str] = field(default_factory=list)
    handler: Callable[[Fact, FactBusClient], list[dict] | None] | None = None
    priority: int = 0  # Higher = checked first


class FactBusState:
    """Manages persistent state for the OpenClaw Fact Bus integration."""

    def __init__(self, state_file: str = "~/.openclaw/fact-bus-state.json"):
        self.state_file = Path(os.path.expanduser(state_file))
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        """Load state from file."""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {
            "claw_id": None,
            "token": None,
            "processed_facts": [],
            "claimed_facts": [],
            "last_heartbeat": None,
        }

    def save(self) -> None:
        """Save state to file."""
        with open(self.state_file, "w") as f:
            json.dump(self._state, f, indent=2)

    @property
    def claw_id(self) -> str | None:
        return self._state.get("claw_id")

    @claw_id.setter
    def claw_id(self, value: str | None) -> None:
        self._state["claw_id"] = value
        self.save()

    @property
    def token(self) -> str | None:
        return self._state.get("token")

    @token.setter
    def token(self, value: str | None) -> None:
        self._state["token"] = value
        self.save()

    @property
    def processed_facts(self) -> list[str]:
        return self._state.get("processed_facts", [])

    def mark_processed(self, fact_id: str) -> None:
        """Mark a fact as processed."""
        processed = self._state.setdefault("processed_facts", [])
        if fact_id not in processed:
            processed.append(fact_id)
            # Keep only last 1000
            if len(processed) > 1000:
                self._state["processed_facts"] = processed[-1000:]
        self.save()

    @property
    def claimed_facts(self) -> list[str]:
        return self._state.get("claimed_facts", [])

    def mark_claimed(self, fact_id: str) -> None:
        """Mark a fact as claimed."""
        claimed = self._state.setdefault("claimed_facts", [])
        if fact_id not in claimed:
            claimed.append(fact_id)
        self.save()

    def unclaim(self, fact_id: str) -> None:
        """Remove fact from claimed list."""
        claimed = self._state.get("claimed_facts", [])
        if fact_id in claimed:
            claimed.remove(fact_id)
        self.save()

    @property
    def last_heartbeat(self) -> float | None:
        return self._state.get("last_heartbeat")

    @last_heartbeat.setter
    def last_heartbeat(self, value: float | None) -> None:
        self._state["last_heartbeat"] = value
        self.save()


class FactBusAgent:
    """
    Main agent class for OpenClaw Fact Bus integration.

    Manages connection, fact processing, and state.

    Usage:
        agent = FactBusAgent(bus_url="http://localhost:8080", claw_name="my-agent")
        agent.register_handler("code.review.needed", handle_code_review)
        agent.run()
    """

    def __init__(
        self,
        bus_url: str,
        claw_name: str,
        capabilities: list[str] | None = None,
        domain_interests: list[str] | None = None,
        fact_type_patterns: list[str] | None = None,
        state_file: str = "~/.openclaw/fact-bus-state.json",
        auto_claim: bool = True,
        heartbeat_interval: float = 30.0,
    ):
        self.bus_url = bus_url
        self.claw_name = claw_name
        self.capabilities = capabilities or []
        self.domain_interests = domain_interests or []
        self.fact_type_patterns = fact_type_patterns or ["*"]
        self.auto_claim = auto_claim
        self.heartbeat_interval = heartbeat_interval

        self.client = FactBusClient(bus_url)
        self.state = FactBusState(state_file)
        self._handlers: list[HandlerRule] = []
        self._running = False

    def register_handler(
        self,
        fact_type_pattern: str = "*",
        semantic_kinds: list[str] | None = None,
        priority: int = 0,
    ) -> Callable:
        """
        Decorator to register a fact handler.

        Usage:
            @agent.register_handler("code.review.needed")
            def handle_review(fact, client):
                # Process the fact
                return [{"fact_type": "code.review.completed", "payload": {...}}]
        """

        def decorator(func: Callable[[Fact, FactBusClient], list[dict] | None]) -> Callable:
            self._handlers.append(
                HandlerRule(
                    fact_type_pattern=fact_type_pattern,
                    semantic_kinds=semantic_kinds or [],
                    handler=func,
                    priority=priority,
                )
            )
            # Sort by priority (highest first)
            self._handlers.sort(key=lambda h: h.priority, reverse=True)
            return func

        return decorator

    def _matches_pattern(self, fact_type: str, pattern: str) -> bool:
        """Check if fact_type matches pattern (supports * wildcard)."""
        if pattern == "*":
            return True
        if pattern.endswith("*"):
            return fact_type.startswith(pattern[:-1])
        if pattern.startswith("*"):
            return fact_type.endswith(pattern[1:])
        return fact_type == pattern

    def _find_handler(self, fact: Fact) -> HandlerRule | None:
        """Find the best handler for a fact."""
        for rule in self._handlers:
            if not self._matches_pattern(fact.fact_type, rule.fact_type_pattern):
                continue
            if rule.semantic_kinds and fact.semantic_kind not in rule.semantic_kinds:
                continue
            return rule
        return None

    def connect(self) -> tuple[str, str]:
        """Connect to the Fact Bus."""
        # Try to restore from state
        if self.state.claw_id and self.state.token:
            self.client.claw_id = self.state.claw_id
            self.client.token = self.state.token
            # Verify connection still valid
            if self.client.heartbeat():
                return self.state.claw_id, self.state.token

        # Fresh connection
        claw_id, token = self.client.connect(
            name=self.claw_name,
            capabilities=self.capabilities,
            domain_interests=self.domain_interests,
            fact_type_patterns=self.fact_type_patterns,
        )

        # Persist state
        self.state.claw_id = claw_id
        self.state.token = token

        return claw_id, token

    def process_fact(self, fact: Fact) -> bool:
        """
        Process a single fact.

        Returns:
            True if fact was handled successfully.
        """
        # Skip if already processed
        if fact.fact_id in self.state.processed_facts:
            return False

        # Skip superseded facts
        if fact.epistemic_state == "superseded":
            self.state.mark_processed(fact.fact_id)
            return False

        # Find handler
        handler_rule = self._find_handler(fact)
        if not handler_rule or not handler_rule.handler:
            return False

        # Claim if exclusive and auto_claim enabled
        if self.auto_claim and fact.mode == "exclusive":
            if not self.client.claim(fact.fact_id):
                return False
            self.state.mark_claimed(fact.fact_id)

        try:
            # Process the fact
            child_facts = handler_rule.handler(fact, self.client)

            # Publish child facts
            if child_facts:
                for child_data in child_facts:
                    # Inherit causation chain
                    causation_chain = [*fact.causation_chain, fact.fact_id]
                    self.client.publish(
                        fact_type=child_data.get("fact_type", ""),
                        payload=child_data.get("payload", {}),
                        semantic_kind=child_data.get("semantic_kind", "resolution"),
                        domain_tags=child_data.get("domain_tags"),
                        need_capabilities=child_data.get("need_capabilities"),
                        priority=child_data.get("priority", Priority.NORMAL),
                        mode=child_data.get("mode", "broadcast"),
                        causation_chain=causation_chain,
                        subject_key=child_data.get("subject_key", fact.subject_key),
                        confidence=child_data.get("confidence", 1.0),
                    )

            # Resolve the fact if claimed
            if fact.fact_id in self.state.claimed_facts:
                self.client.resolve(fact.fact_id, result_facts=child_facts)
                self.state.unclaim(fact.fact_id)

            self.state.mark_processed(fact.fact_id)
            return True

        except Exception as e:
            # Release claim on error
            if fact.fact_id in self.state.claimed_facts:
                self.client.release(fact.fact_id)
                self.state.unclaim(fact.fact_id)
            raise e

    def run_once(self) -> int:
        """
        Run one iteration: check for new facts and process them.

        Returns:
            Number of facts processed.
        """
        # Send heartbeat
        now = time.time()
        if (
            self.state.last_heartbeat is None
            or now - self.state.last_heartbeat > self.heartbeat_interval
        ):
            self.client.heartbeat()
            self.state.last_heartbeat = now

        # Query for new facts
        facts = self.client.query_facts(
            state="published",
            limit=10,
        )

        processed = 0
        for fact in facts:
            if self.process_fact(fact):
                processed += 1

        return processed

    def run(self, iterations: int | None = None, interval: float = 5.0) -> None:
        """
        Run the agent loop.

        Args:
            iterations: Number of iterations (None = infinite)
            interval: Seconds between iterations
        """
        import time

        self._running = True
        count = 0

        print(f"🦞 Claw {self.claw_name} connected to {self.bus_url}")
        print(f"   Capabilities: {self.capabilities}")
        print(f"   Patterns: {self.fact_type_patterns}")

        try:
            while self._running:
                if iterations is not None and count >= iterations:
                    break

                processed = self.run_once()
                if processed > 0:
                    print(f"   Processed {processed} facts")

                count += 1
                time.sleep(interval)

        except KeyboardInterrupt:
            print("\n🛑 Shutting down...")

        finally:
            self.disconnect()

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False

    def disconnect(self) -> None:
        """Disconnect from the bus."""
        self.client.disconnect()
        self.state.claw_id = None
        self.state.token = None
        print(f"🦞 Claw {self.claw_name} disconnected")


# ---------------------------------------------------------------------------
# Built-in Handlers
# ---------------------------------------------------------------------------


class ObservationHandler:
    """Handler for observation facts - corroborate if we can verify."""

    def can_handle(self, fact: Fact) -> bool:
        return fact.semantic_kind == "observation"

    def handle(self, fact: Fact, client: FactBusClient) -> list[dict] | None:
        # By default, corroborate observations we can verify
        client.corroborate(fact.fact_id)
        return None


class RequestHandler:
    """Handler for request facts - acknowledge receipt."""

    def can_handle(self, fact: Fact) -> bool:
        return fact.semantic_kind == "request"

    def handle(self, fact: Fact, client: FactBusClient) -> list[dict] | None:
        # Emit acknowledgment signal
        return [
            {
                "fact_type": f"{fact.fact_type}.acknowledged",
                "semantic_kind": "signal",
                "payload": {
                    "original_fact_id": fact.fact_id,
                    "claw_id": client.claw_id,
                    "timestamp": time.time(),
                },
                "mode": "broadcast",
            }
        ]
