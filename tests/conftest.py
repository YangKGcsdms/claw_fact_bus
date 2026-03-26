"""
Shared fixtures for Claw Fact Bus integration tests.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from claw_fact_bus.server.app import app, _engine, set_engine
from claw_fact_bus.server.bus_engine import BusEngine
from claw_fact_bus.types import (
    AcceptanceFilter,
    ClawIdentity,
    Fact,
    FactMode,
    Priority,
    SemanticKind,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest_asyncio.fixture
async def engine(temp_dir: Path) -> AsyncGenerator[BusEngine, None]:
    """Create a fresh BusEngine for testing."""
    eng = BusEngine(data_dir=str(temp_dir))
    set_engine(eng)
    await eng.start_background_tasks()
    yield eng
    await eng.shutdown()
    set_engine(None)


@pytest_asyncio.fixture
async def client(engine: BusEngine) -> AsyncGenerator[AsyncClient, None]:
    """Create an HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def connected_claw(client: AsyncClient) -> dict:
    """Connect a test claw and return its info."""
    response = await client.post(
        "/claws/connect",
        json={
            "name": "test-claw",
            "description": "Integration test claw",
            "capability_offer": ["test", "review"],
            "domain_interests": ["python", "testing"],
            "fact_type_patterns": ["test.*", "code.*"],
        },
    )
    assert response.status_code == 200
    return response.json()


@pytest_asyncio.fixture
async def connected_claw_2(client: AsyncClient) -> dict:
    """Connect a second test claw."""
    response = await client.post(
        "/claws/connect",
        json={
            "name": "test-claw-2",
            "description": "Second integration test claw",
            "capability_offer": ["review", "security"],
            "domain_interests": ["python", "security"],
            "fact_type_patterns": ["code.*", "security.*"],
        },
    )
    assert response.status_code == 200
    return response.json()


@pytest_asyncio.fixture
async def published_fact(client: AsyncClient, connected_claw: dict) -> dict:
    """Publish a test fact and return its info."""
    response = await client.post(
        "/facts",
        json={
            "fact_type": "test.example",
            "semantic_kind": "observation",
            "payload": {"message": "test fact", "value": 42},
            "domain_tags": ["test"],
            "need_capabilities": ["test"],
            "priority": Priority.NORMAL,
            "mode": "exclusive",
            "source_claw_id": connected_claw["claw_id"],
            "token": connected_claw["token"],
            "confidence": 0.9,
        },
    )
    assert response.status_code == 200
    return response.json()


@pytest_asyncio.fixture
async def broadcast_fact(client: AsyncClient, connected_claw: dict) -> dict:
    """Publish a broadcast test fact."""
    response = await client.post(
        "/facts",
        json={
            "fact_type": "test.broadcast",
            "semantic_kind": "signal",
            "payload": {"status": "broadcasting"},
            "domain_tags": ["test"],
            "priority": Priority.NORMAL,
            "mode": "broadcast",
            "source_claw_id": connected_claw["claw_id"],
            "token": connected_claw["token"],
        },
    )
    assert response.status_code == 200
    return response.json()


def make_claw(
    name: str = "test-claw",
    capabilities: list[str] | None = None,
    domain_interests: list[str] | None = None,
    fact_type_patterns: list[str] | None = None,
) -> ClawIdentity:
    """Factory for creating test ClawIdentity instances."""
    return ClawIdentity(
        name=name,
        description=f"Test claw: {name}",
        acceptance_filter=AcceptanceFilter(
            capability_offer=capabilities or ["test"],
            domain_interests=domain_interests or ["test"],
            fact_type_patterns=fact_type_patterns or ["test.*"],
        ),
    )


def make_fact(
    fact_type: str = "test.example",
    payload: dict | None = None,
    semantic_kind: SemanticKind = SemanticKind.OBSERVATION,
    mode: FactMode = FactMode.EXCLUSIVE,
    priority: int = Priority.NORMAL,
    source_claw_id: str = "test-source",
    subject_key: str = "",
    confidence: float = 1.0,
) -> Fact:
    """Factory for creating test Fact instances."""
    fact = Fact(
        fact_type=fact_type,
        payload=payload or {"test": True},
        semantic_kind=semantic_kind,
        mode=mode,
        priority=priority,
        source_claw_id=source_claw_id,
        subject_key=subject_key,
        confidence=confidence,
    )
    fact.compute_content_hash()
    return fact
