"""
Claw Fact Bus HTTP Client for OpenClaw Integration.

Provides a lightweight client for interacting with the Fact Bus REST API.
Supports both synchronous and asynchronous usage.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class Priority(IntEnum):
    """Priority levels, lower value = higher priority (CAN convention)."""

    CRITICAL = 0
    HIGH = 1
    ELEVATED = 2
    NORMAL = 3
    LOW = 4
    BACKGROUND = 5
    IDLE = 6
    BULK = 7


@dataclass
class Fact:
    """Represents a fact on the bus."""

    fact_id: str = ""
    fact_type: str = ""
    semantic_kind: str = "observation"
    payload: dict = field(default_factory=dict)
    domain_tags: list[str] = field(default_factory=list)
    need_capabilities: list[str] = field(default_factory=list)
    priority: int = Priority.NORMAL
    mode: str = "exclusive"
    source_claw_id: str = ""
    causation_chain: list[str] = field(default_factory=list)
    subject_key: str = ""
    supersedes: str = ""
    confidence: float = 1.0
    ttl_seconds: int = 300

    # Bus state
    state: str = "created"
    epistemic_state: str = "asserted"
    claimed_by: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_publish_dict(self) -> dict:
        """Convert to dict for publishing."""
        return {
            "fact_type": self.fact_type,
            "semantic_kind": self.semantic_kind,
            "payload": self.payload,
            "domain_tags": self.domain_tags,
            "need_capabilities": self.need_capabilities,
            "priority": self.priority,
            "mode": self.mode,
            "source_claw_id": self.source_claw_id,
            "causation_chain": self.causation_chain,
            "subject_key": self.subject_key,
            "supersedes": self.supersedes,
            "confidence": self.confidence,
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Fact:
        """Create Fact from API response."""
        return cls(
            fact_id=data.get("fact_id", ""),
            fact_type=data.get("fact_type", ""),
            semantic_kind=data.get("semantic_kind", "observation"),
            payload=data.get("payload", {}),
            domain_tags=data.get("domain_tags", []),
            need_capabilities=data.get("need_capabilities", []),
            priority=data.get("priority", Priority.NORMAL),
            mode=data.get("mode", "exclusive"),
            source_claw_id=data.get("source_claw_id", ""),
            causation_chain=data.get("causation_chain", []),
            subject_key=data.get("subject_key", ""),
            supersedes=data.get("supersedes", ""),
            confidence=data.get("confidence", 1.0),
            ttl_seconds=data.get("ttl_seconds", 300),
            state=data.get("state", "created"),
            epistemic_state=data.get("epistemic_state", "asserted"),
            claimed_by=data.get("claimed_by"),
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class ClawInfo:
    """Represents a claw on the bus."""

    claw_id: str = ""
    name: str = ""
    description: str = ""
    state: str = "offline"
    reliability_score: float = 1.0
    connected_at: float | None = None

    @classmethod
    def from_dict(cls, data: dict) -> ClawInfo:
        """Create ClawInfo from API response."""
        return cls(
            claw_id=data.get("claw_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            state=data.get("state", "offline"),
            reliability_score=data.get("reliability_score", 1.0),
            connected_at=data.get("connected_at"),
        )


class FactBusClient:
    """
    HTTP client for Claw Fact Bus.

    Usage:
        client = FactBusClient("http://localhost:8080")
        claw_id, token = client.connect("my-claw", ["code_review"])
        fact_id = client.publish("code.review.needed", {"file": "auth.py"})
        client.claim(fact_id)
        client.resolve(fact_id)
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.claw_id: str | None = None
        self.token: str | None = None
        self._session = None

    def _get_session(self):
        """Get or create requests session."""
        if self._session is None:
            try:
                import requests

                self._session = requests.Session()
                self._session.timeout = self.timeout
            except ImportError:
                raise ImportError("requests library required. Install with: pip install requests")
        return self._session

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make HTTP request to Fact Bus."""
        session = self._get_session()
        url = f"{self.base_url}{path}"

        headers = kwargs.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        response = session.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()

    # -----------------------------------------------------------------------
    # Connection
    # -----------------------------------------------------------------------

    def connect(
        self,
        name: str,
        capabilities: list[str] | None = None,
        domain_interests: list[str] | None = None,
        fact_type_patterns: list[str] | None = None,
        description: str = "",
    ) -> tuple[str, str]:
        """
        Connect to the bus and register this claw.

        Returns:
            Tuple of (claw_id, token)
        """
        payload = {
            "name": name,
            "description": description,
            "capability_offer": capabilities or [],
            "domain_interests": domain_interests or [],
            "fact_type_patterns": fact_type_patterns or ["*"],
        }

        result = self._request("POST", "/claws/connect", json=payload)
        self.claw_id = result["claw_id"]
        self.token = result["token"]
        return self.claw_id, self.token

    def disconnect(self) -> None:
        """Disconnect from the bus."""
        if self.claw_id and self.token:
            try:
                self._request("POST", f"/claws/{self.claw_id}/disconnect")
            except Exception:
                pass  # Best effort
        self.claw_id = None
        self.token = None

    def heartbeat(self) -> bool:
        """Send heartbeat to keep connection alive."""
        if not self.claw_id or not self.token:
            return False
        try:
            self._request("POST", f"/claws/{self.claw_id}/heartbeat")
            return True
        except Exception:
            return False

    # -----------------------------------------------------------------------
    # Fact Operations
    # -----------------------------------------------------------------------

    def publish(
        self,
        fact_type: str,
        payload: dict,
        semantic_kind: str = "observation",
        domain_tags: list[str] | None = None,
        need_capabilities: list[str] | None = None,
        priority: int = Priority.NORMAL,
        mode: str = "exclusive",
        causation_chain: list[str] | None = None,
        subject_key: str = "",
        supersedes: str = "",
        confidence: float = 1.0,
        ttl_seconds: int = 300,
    ) -> str:
        """
        Publish a fact to the bus.

        Returns:
            The fact_id of the published fact.
        """
        if not self.claw_id or not self.token:
            raise RuntimeError("Not connected. Call connect() first.")

        fact_data = {
            "fact_type": fact_type,
            "semantic_kind": semantic_kind,
            "payload": payload,
            "domain_tags": domain_tags or [],
            "need_capabilities": need_capabilities or [],
            "priority": priority,
            "mode": mode,
            "source_claw_id": self.claw_id,
            "token": self.token,
            "causation_chain": causation_chain or [],
            "subject_key": subject_key,
            "supersedes": supersedes,
            "confidence": confidence,
            "ttl_seconds": ttl_seconds,
        }

        result = self._request("POST", "/facts", json=fact_data)
        return result["fact_id"]

    def get_fact(self, fact_id: str) -> Fact:
        """Get a fact by ID."""
        result = self._request("GET", f"/facts/{fact_id}")
        return Fact.from_dict(result)

    def query_facts(
        self,
        fact_type: str | None = None,
        semantic_kind: str | None = None,
        state: str | None = None,
        epistemic_state: str | None = None,
        domain_tags: list[str] | None = None,
        limit: int = 50,
    ) -> list[Fact]:
        """Query facts with filters."""
        params: dict[str, Any] = {"limit": limit}
        if fact_type:
            params["fact_type"] = fact_type
        if semantic_kind:
            params["semantic_kind"] = semantic_kind
        if state:
            params["state"] = state
        if epistemic_state:
            params["epistemic_state"] = epistemic_state
        if domain_tags:
            params["domain_tags"] = ",".join(domain_tags)

        result = self._request("GET", "/facts", params=params)
        return [Fact.from_dict(f) for f in result.get("facts", [])]

    def claim(self, fact_id: str) -> bool:
        """Claim an exclusive fact."""
        if not self.claw_id or not self.token:
            raise RuntimeError("Not connected. Call connect() first.")

        try:
            self._request(
                "POST",
                f"/facts/{fact_id}/claim",
                json={"claw_id": self.claw_id, "token": self.token},
            )
            return True
        except Exception:
            return False

    def release(self, fact_id: str) -> bool:
        """Release a claimed fact."""
        if not self.claw_id or not self.token:
            raise RuntimeError("Not connected. Call connect() first.")

        try:
            self._request(
                "POST",
                f"/facts/{fact_id}/release",
                json={"claw_id": self.claw_id, "token": self.token},
            )
            return True
        except Exception:
            return False

    def resolve(
        self,
        fact_id: str,
        result_facts: list[dict] | None = None,
    ) -> bool:
        """Resolve a fact, optionally emitting child facts."""
        if not self.claw_id or not self.token:
            raise RuntimeError("Not connected. Call connect() first.")

        payload = {
            "claw_id": self.claw_id,
            "token": self.token,
        }
        if result_facts:
            payload["result_facts"] = result_facts

        try:
            self._request("POST", f"/facts/{fact_id}/resolve", json=payload)
            return True
        except Exception:
            return False

    def corroborate(self, fact_id: str) -> str:
        """
        Corroborate a fact (confirm you also observed it).

        Returns:
            New epistemic state.
        """
        result = self._request(
            "POST",
            f"/facts/{fact_id}/corroborate",
            json={"claw_id": self.claw_id},
        )
        return result.get("epistemic_state", "corroborated")

    def contradict(self, fact_id: str) -> str:
        """
        Contradict a fact (your observation differs).

        Returns:
            New epistemic state.
        """
        result = self._request(
            "POST",
            f"/facts/{fact_id}/contradict",
            json={"claw_id": self.claw_id},
        )
        return result.get("epistemic_state", "contested")

    # -----------------------------------------------------------------------
    # Discovery
    # -----------------------------------------------------------------------

    def list_claws(self) -> list[ClawInfo]:
        """List all claws on the bus."""
        result = self._request("GET", "/claws")
        return [ClawInfo.from_dict(c) for c in result.get("claws", [])]

    def get_stats(self) -> dict:
        """Get bus statistics."""
        return self._request("GET", "/stats")

    def get_health(self) -> dict:
        """Get bus health status."""
        return self._request("GET", "/health")

    # -----------------------------------------------------------------------
    # Context Manager
    # -----------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        if self._session:
            self._session.close()


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------


def create_client(
    bus_url: str,
    claw_name: str,
    capabilities: list[str] | None = None,
    domain_interests: list[str] | None = None,
    fact_type_patterns: list[str] | None = None,
) -> FactBusClient:
    """
    Create and connect a FactBusClient.

    Returns:
        Connected FactBusClient instance.
    """
    client = FactBusClient(bus_url)
    client.connect(
        name=claw_name,
        capabilities=capabilities,
        domain_interests=domain_interests,
        fact_type_patterns=fact_type_patterns,
    )
    return client
