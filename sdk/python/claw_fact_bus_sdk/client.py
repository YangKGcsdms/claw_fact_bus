"""
High-level client for Claw Fact Bus.

Provides both HTTP REST API and WebSocket real-time connection.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Coroutine

import httpx

from .models import AcceptanceFilter, BusEvent, Fact, FactMode, Priority, ClawInfo

EventHandler = Callable[[BusEvent], Coroutine[Any, Any, None]]


class FactBusClient:
    """
    High-level client for connecting to the Fact Bus.

    Usage:
        async with FactBusClient("http://localhost:8080") as client:
            await client.connect(
                name="my-claw",
                filter=AcceptanceFilter(capability_offer=["review"])
            )

            async for event in client.events():
                if event.event_type == "fact_available":
                    await client.claim(event.fact.fact_id)
                    # ... process fact ...
                    await client.resolve(event.fact.fact_id)
    """

    RECONNECT_BASE_DELAY = 1.0
    RECONNECT_MAX_DELAY = 60.0
    RECONNECT_JITTER = 0.5

    def __init__(
        self,
        base_url: str,
        claw_id: str | None = None,
        heartbeat_interval: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.claw_id = claw_id
        self.heartbeat_interval = heartbeat_interval

        self._http: httpx.AsyncClient | None = None
        self._event_handlers: list[EventHandler] = []
        self._connected = False
        self._event_queue: asyncio.Queue[BusEvent] = asyncio.Queue()
        self._ws_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._filter: AcceptanceFilter | None = None
        self._ws_connected = False

    async def __aenter__(self) -> FactBusClient:
        """Async context manager entry."""
        await self._init_http()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()

    async def _init_http(self) -> None:
        """Initialize HTTP client."""
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
        )

    async def connect(
        self,
        name: str,
        filter: AcceptanceFilter,
        description: str = "",
        max_concurrent_claims: int = 1,
    ) -> str:
        """
        Connect to the bus and register this claw.

        Returns the assigned claw_id.
        """
        if self._http is None:
            await self._init_http()

        self._filter = filter

        response = await self._http.post(
            "/claws/connect",
            json={
                "name": name,
                "description": description,
                "capability_offer": filter.capability_offer,
                "domain_interests": filter.domain_interests,
                "fact_type_patterns": filter.fact_type_patterns,
                "priority_range": list(filter.priority_range),
                "modes": filter.modes,
                "max_concurrent_claims": max_concurrent_claims,
            },
        )
        response.raise_for_status()
        data = response.json()

        self.claw_id = data["claw_id"]
        self._connected = True

        # Start WebSocket connection
        self._ws_task = asyncio.create_task(self._websocket_loop())

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        return self.claw_id

    async def disconnect(self) -> None:
        """Disconnect from the bus."""
        self._connected = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

        if self._http:
            await self._http.aclose()
            self._http = None

    def on_event(self, handler: EventHandler) -> None:
        """Register an event handler callback."""
        self._event_handlers.append(handler)

    def off_event(self, handler: EventHandler) -> None:
        """Unregister an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    async def events(self) -> asyncio.AsyncIterator[BusEvent]:
        """
        Async iterator for incoming events.

        Usage:
            async for event in client.events():
                print(event.event_type)
        """
        while self._connected:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=1.0,
                )
                yield event
            except asyncio.TimeoutError:
                continue

    async def publish(
        self,
        fact_type: str,
        payload: dict[str, Any],
        domain_tags: list[str] | None = None,
        need_capabilities: list[str] | None = None,
        priority: int = Priority.NORMAL,
        mode: str = "exclusive",
        ttl_seconds: int = 300,
        causation_chain: list[str] | None = None,
        confidence: float = 1.0,
    ) -> Fact:
        """
        Publish a new fact to the bus.

        Returns the published Fact with assigned ID.
        """
        response = await self._http.post(
            "/facts",
            json={
                "fact_type": fact_type,
                "payload": payload,
                "domain_tags": domain_tags or [],
                "need_capabilities": need_capabilities or [],
                "priority": priority,
                "mode": mode,
                "source_claw_id": self.claw_id,
                "ttl_seconds": ttl_seconds,
                "causation_chain": causation_chain or [],
                "confidence": confidence,
            },
        )
        response.raise_for_status()
        return Fact(**response.json())

    async def claim(self, fact_id: str) -> bool:
        """Claim an exclusive fact for processing."""
        response = await self._http.post(
            f"/facts/{fact_id}/claim",
            json={"claw_id": self.claw_id},
        )
        if response.status_code == 200:
            return True
        return False

    async def release(self, fact_id: str) -> bool:
        """Release a claimed fact back to the pool."""
        response = await self._http.post(
            f"/facts/{fact_id}/release",
            json={"claw_id": self.claw_id},
        )
        if response.status_code == 200:
            return True
        return False

    async def resolve(
        self,
        fact_id: str,
        result_facts: list[Fact] | None = None,
    ) -> bool:
        """Mark a fact as resolved, optionally with child facts."""
        json_data = {
            "claw_id": self.claw_id,
            "result_facts": [
                {
                    "fact_type": f.fact_type,
                    "payload": f.payload,
                    "domain_tags": f.domain_tags,
                    "need_capabilities": f.need_capabilities,
                    "priority": f.priority,
                    "mode": f.mode,
                    "schema_version": f.schema_version,
                }
                for f in (result_facts or [])
            ],
        }

        response = await self._http.post(
            f"/facts/{fact_id}/resolve",
            json=json_data,
        )
        if response.status_code == 200:
            return True
        return False

    async def corroborate(self, fact_id: str) -> bool:
        """Corroborate (confirm) a fact published by another claw."""
        response = await self._http.post(
            f"/facts/{fact_id}/corroborate",
            json={"claw_id": self.claw_id},
        )
        return response.status_code == 200

    async def contradict(self, fact_id: str) -> bool:
        """Contradict (dispute) a fact published by another claw."""
        response = await self._http.post(
            f"/facts/{fact_id}/contradict",
            json={"claw_id": self.claw_id},
        )
        return response.status_code == 200

    async def query_facts(
        self,
        fact_type: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[Fact]:
        """Query facts on the bus."""
        params = {"limit": limit}
        if fact_type:
            params["fact_type"] = fact_type
        if state:
            params["state"] = state

        response = await self._http.get("/facts", params=params)
        response.raise_for_status()
        return [Fact(**f) for f in response.json()]

    async def get_fact(self, fact_id: str) -> Fact | None:
        """Get a single fact by ID."""
        response = await self._http.get(f"/facts/{fact_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return Fact(**response.json())

    async def list_claws(self) -> list[ClawInfo]:
        """List all connected claws."""
        response = await self._http.get("/claws")
        response.raise_for_status()
        return [ClawInfo(**c) for c in response.json()]

    async def get_stats(self) -> dict:
        """Get bus statistics."""
        response = await self._http.get("/stats")
        response.raise_for_status()
        return response.json()

    # -------------------------------------------------------------------------
    # Internal methods
    # -------------------------------------------------------------------------

    async def _websocket_loop(self) -> None:
        """WebSocket connection loop with exponential backoff reconnection."""
        import websockets

        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        uri = f"{ws_url}/ws/{self.claw_id}"
        attempt = 0

        while self._connected:
            try:
                async with websockets.connect(uri) as ws:
                    attempt = 0
                    self._ws_connected = True

                    await ws.send(
                        json.dumps({
                            "action": "subscribe",
                            "name": self._filter.__class__.__name__ if self._filter else "claw",
                            "filter": self._filter.model_dump() if self._filter else {},
                        })
                    )

                    while self._connected:
                        try:
                            message = await asyncio.wait_for(
                                ws.recv(),
                                timeout=5.0,
                            )
                            data = json.loads(message)

                            if "error" in data:
                                print(f"[SDK] WebSocket error: {data['error']}")
                                continue

                            if data.get("status") == "subscribed":
                                continue

                            if data.get("type") == "pong":
                                continue

                            event = BusEvent(**data)
                            await self._event_queue.put(event)

                            for handler in self._event_handlers:
                                try:
                                    await handler(event)
                                except Exception as e:
                                    print(f"[SDK] Event handler error: {e}")

                        except asyncio.TimeoutError:
                            await ws.send(json.dumps({"action": "heartbeat"}))
                        except websockets.exceptions.ConnectionClosed:
                            break

            except Exception as e:
                self._ws_connected = False
                if not self._connected:
                    break
                delay = min(
                    self.RECONNECT_BASE_DELAY * (2 ** attempt),
                    self.RECONNECT_MAX_DELAY,
                )
                delay += random.uniform(0, self.RECONNECT_JITTER)
                attempt += 1
                print(f"[SDK] WebSocket reconnecting in {delay:.1f}s (attempt {attempt}): {e}")
                await asyncio.sleep(delay)

    async def _heartbeat_loop(self) -> None:
        """Periodic heartbeat to maintain connection and TEC recovery."""
        while self._connected:
            try:
                await asyncio.sleep(self.heartbeat_interval)

                if not self._connected:
                    break

                response = await self._http.post(f"/claws/{self.claw_id}/heartbeat")
                if response.status_code != 200:
                    print(f"[SDK] Heartbeat failed: {response.status_code}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[SDK] Heartbeat error: {e}")


class SimpleClaw:
    """
    Simplified claw abstraction for common use cases.

    Automatically handles claim → process → resolve flow.
    """

    def __init__(
        self,
        client: FactBusClient,
        name: str,
        capabilities: list[str],
        handler: Callable[[Fact], Coroutine[Any, Any, list[Fact] | None]],
    ) -> None:
        self.client = client
        self.name = name
        self.capabilities = capabilities
        self.handler = handler
        self._running = False

    async def start(self) -> None:
        """Start processing facts."""
        await self.client.connect(
            name=self.name,
            filter=AcceptanceFilter(capability_offer=self.capabilities),
        )

        self._running = True
        self.client.on_event(self._on_event)

        print(f"[SimpleClaw] {self.name} started with capabilities: {self.capabilities}")

        # Keep running
        while self._running:
            await asyncio.sleep(1.0)

    async def stop(self) -> None:
        """Stop processing."""
        self._running = False
        await self.client.disconnect()

    async def _on_event(self, event: BusEvent) -> None:
        """Handle incoming events."""
        if event.event_type != "fact_available":
            return

        if not event.fact:
            return

        fact = event.fact

        # Try to claim
        claimed = await self.client.claim(fact.fact_id)
        if not claimed:
            return  # Someone else got it

        print(f"[SimpleClaw] {self.name} processing {fact.fact_type}")

        try:
            # Process
            result_facts = await self.handler(fact)

            # Resolve
            await self.client.resolve(fact.fact_id, result_facts or [])
            print(f"[SimpleClaw] {self.name} completed {fact.fact_id}")

        except Exception as e:
            print(f"[SimpleClaw] {self.name} error processing {fact.fact_id}: {e}")
            # Release so someone else can try
            await self.client.release(fact.fact_id)
