"""
FastAPI Application for Fact Bus.

Provides:
- HTTP REST API for facts, claws, and queries
- WebSocket endpoint for real-time event push
- Health and status endpoints
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Optional

from fastapi import Body, Depends, FastAPI, Header, Query, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from fastapi.staticfiles import StaticFiles

from ..filter import MatchResult, evaluate_filter
from ..types import (
    AcceptanceFilter,
    BusEvent,
    BusEventType,
    ClawIdentity,
    ClawState,
    Fact,
    FactMode,
    FactState,
    Priority,
    SemanticKind,
)
from .bus_engine import BusEngine


# Global engine instance (singleton pattern)
_engine: Optional[BusEngine] = None


def get_engine() -> BusEngine:
    """Get or create the global engine instance."""
    global _engine
    if _engine is None:
        data_dir = os.getenv("FACT_BUS_DATA_DIR", ".data")
        _engine = BusEngine(data_dir)
    return _engine


# =============================================================================
# Pydantic Models for Request/Response - Defined at module level for FastAPI
# =============================================================================

class FactCreateRequest(BaseModel):
    fact_type: str = Field(..., description="Dot-notation taxonomy, e.g. 'code.review.needed'")
    semantic_kind: str = "observation"
    payload: dict = Field(default_factory=dict)
    domain_tags: list[str] = Field(default_factory=list)
    need_capabilities: list[str] = Field(default_factory=list)
    priority: int = Field(default=3, ge=0, le=7)
    mode: str = Field(default="exclusive")
    source_claw_id: str
    token: str = ""
    ttl_seconds: int = Field(default=300, ge=10)
    schema_version: str = "1.0.0"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    causation_chain: list[str] = Field(default_factory=list)
    causation_depth: int = Field(default=0)
    subject_key: str = ""
    supersedes: str = ""


class FactResponse(BaseModel):
    fact_id: str
    fact_type: str
    semantic_kind: str = "observation"
    payload: dict
    domain_tags: list[str]
    need_capabilities: list[str]
    priority: int
    mode: str
    source_claw_id: str
    state: str
    epistemic_state: str = "asserted"
    created_at: float
    claimed_by: Optional[str] = None
    effective_priority: Optional[int] = None
    confidence: float = 1.0
    subject_key: str = ""
    supersedes: str = ""
    superseded_by: str = ""
    signature: str = ""
    sequence_number: int = 0
    corroborations: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    protocol_version: str = "2.0.0"


class ClawConnectRequest(BaseModel):
    name: str
    description: str = ""
    capability_offer: list[str] = Field(default_factory=list)
    domain_interests: list[str] = Field(default_factory=list)
    fact_type_patterns: list[str] = Field(default_factory=list)
    priority_range: tuple[int, int] = (0, 7)
    modes: list[str] = Field(default_factory=lambda: ["exclusive", "broadcast"])
    max_concurrent_claims: int = 1


class ClawResponse(BaseModel):
    claw_id: str
    name: str
    state: str
    reliability_score: float
    token: Optional[str] = None


class ClaimRequest(BaseModel):
    claw_id: str
    token: str = ""


class ResolveRequest(BaseModel):
    claw_id: str
    token: str = ""
    result_facts: list[dict] = Field(default_factory=list)


class CorroborateRequest(BaseModel):
    claw_id: str


class ContradictRequest(BaseModel):
    claw_id: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    engine = get_engine()
    print(f"[Bus] Started with {len(engine._facts)} recovered facts")
    yield
    if _engine:
        print("[Bus] Shutting down – cancelling background tasks...")
        for task in list(_engine._background_tasks):
            task.cancel()
        await asyncio.gather(*_engine._background_tasks, return_exceptions=True)
        print("[Bus] Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Claw Fact Bus",
        description="CAN-Bus inspired fact bus for AI agent cluster coordination",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Static files (Web UI)
    import os as _os
    static_dir = _os.path.join(_os.path.dirname(__file__), "static")
    if _os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # =============================================================================
    # Web UI
    # =============================================================================

    @app.get("/")
    async def root():
        """Redirect to dashboard."""
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/static/index.html")

    # =============================================================================
    # Health & Status
    # =============================================================================

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "ok", "timestamp": time.time()}

    @app.get("/stats")
    async def stats():
        """Get bus statistics."""
        engine = get_engine()
        return engine.get_stats()

    # =============================================================================
    # Facts API
    # =============================================================================

    @app.post("/facts", response_model=FactResponse, status_code=status.HTTP_201_CREATED)
    async def create_fact(request: FactCreateRequest = Body(...)):
        """
        Publish a new fact onto the bus.

        The fact will be filtered against all connected claws and dispatched
        to matching recipients via WebSocket.
        """
        engine = get_engine()

        auth_err = _verify_claw_token(engine, request.source_claw_id, request.token)
        if auth_err:
            return auth_err

        fact = Fact(
            fact_type=request.fact_type,
            semantic_kind=SemanticKind(request.semantic_kind),
            payload=request.payload,
            domain_tags=request.domain_tags,
            need_capabilities=request.need_capabilities,
            priority=request.priority,
            mode=FactMode(request.mode),
            source_claw_id=request.source_claw_id,
            ttl_seconds=request.ttl_seconds,
            schema_version=request.schema_version,
            confidence=request.confidence,
            causation_chain=request.causation_chain,
            causation_depth=request.causation_depth,
            subject_key=request.subject_key,
            supersedes=request.supersedes,
        )

        success, reason, fact_id = await engine.publish_fact(fact)

        if not success:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={"error": reason},
            )

        return _fact_to_response(fact)

    @app.get("/facts")
    async def list_facts(
        fact_type: Annotated[Optional[str], Query()] = None,
        state: Annotated[Optional[str], Query()] = None,
        source_claw_id: Annotated[Optional[str], Query()] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ):
        """Query facts with optional filters."""
        engine = get_engine()

        state_enum = FactState(state) if state else None

        facts = engine.query_facts(
            fact_type=fact_type,
            state=state_enum,
            source_claw_id=source_claw_id,
            limit=limit,
        )

        return [_fact_to_response(f) for f in facts]

    @app.get("/facts/{fact_id}", response_model=FactResponse)
    async def get_fact(fact_id: str):
        """Get a single fact by ID."""
        engine = get_engine()

        if fact_id not in engine._facts:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "fact not found"},
            )

        return _fact_to_response(engine._facts[fact_id])

    @app.post("/facts/{fact_id}/claim")
    async def claim_fact(fact_id: str, request: ClaimRequest = Body(...)):
        """Claim an exclusive fact for processing."""
        engine = get_engine()

        auth_err = _verify_claw_token(engine, request.claw_id, request.token)
        if auth_err:
            return auth_err

        success, reason = await engine.claim_fact(fact_id, request.claw_id)

        if not success:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"error": reason},
            )

        return {"success": True, "fact_id": fact_id, "claimed_by": request.claw_id}

    @app.post("/facts/{fact_id}/resolve")
    async def resolve_fact(fact_id: str, request: ResolveRequest = Body(...)):
        """Mark a fact as resolved with optional result facts."""
        engine = get_engine()

        auth_err = _verify_claw_token(engine, request.claw_id, request.token)
        if auth_err:
            return auth_err

        result_facts = [
            Fact(
                fact_type=rf.get("fact_type", ""),
                payload=rf.get("payload", {}),
                domain_tags=rf.get("domain_tags", []),
                need_capabilities=rf.get("need_capabilities", []),
                priority=rf.get("priority", Priority.NORMAL),
                mode=FactMode(rf.get("mode", "exclusive")),
                source_claw_id=request.claw_id,
                schema_version=rf.get("schema_version", "1.0"),
            )
            for rf in request.result_facts
        ]

        success, reason = await engine.resolve_fact(
            fact_id, request.claw_id, result_facts if result_facts else None
        )

        if not success:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"error": reason},
            )

        return {"success": True, "fact_id": fact_id}

    @app.post("/facts/{fact_id}/corroborate")
    async def corroborate_fact(fact_id: str, request: CorroborateRequest = Body(...)):
        """Corroborate (confirm) a fact. Directly affects epistemic state."""
        engine = get_engine()
        success, detail = await engine.corroborate_fact(fact_id, request.claw_id)

        if not success:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND
                if detail == "fact not found" else status.HTTP_409_CONFLICT,
                content={"error": detail},
            )

        return {"success": True, "fact_id": fact_id, "epistemic_state": detail}

    @app.post("/facts/{fact_id}/contradict")
    async def contradict_fact(fact_id: str, request: ContradictRequest = Body(...)):
        """Contradict (dispute) a fact. Directly affects epistemic state."""
        engine = get_engine()
        success, detail = await engine.contradict_fact(fact_id, request.claw_id)

        if not success:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND
                if detail == "fact not found" else status.HTTP_409_CONFLICT,
                content={"error": detail},
            )

        return {"success": True, "fact_id": fact_id, "epistemic_state": detail}

    @app.post("/facts/{fact_id}/release")
    async def release_fact(fact_id: str, request: ClaimRequest = Body(...)):
        """Release a claimed fact back to the pool."""
        engine = get_engine()

        success, reason = await engine.release_fact(fact_id, request.claw_id)

        if not success:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"error": reason},
            )

        return {"success": True, "fact_id": fact_id}

    # =============================================================================
    # Claws API
    # =============================================================================

    def _verify_claw_token(engine: BusEngine, claw_id: str, token: str) -> Optional[JSONResponse]:
        """Verify claw token. Returns error response if invalid, None if ok."""
        if not engine._claw_tokens:
            return None
        if not token:
            return None
        if not engine.verify_claw_token(claw_id, token):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"error": f"invalid token for claw {claw_id}"},
            )
        return None

    @app.post("/claws/connect", response_model=ClawResponse)
    async def connect_claw(request: ClawConnectRequest = Body(...)):
        """
        Register a new claw connection.

        Returns the assigned claw_id and auth token.
        Include the token in subsequent requests for identity verification.
        """
        engine = get_engine()

        claw_id = uuid.uuid4().hex[:12]

        identity = ClawIdentity(
            claw_id=claw_id,
            name=request.name,
            description=request.description,
            acceptance_filter=AcceptanceFilter(
                capability_offer=request.capability_offer,
                domain_interests=request.domain_interests,
                fact_type_patterns=request.fact_type_patterns,
                priority_range=request.priority_range,
                modes=[FactMode(m) for m in request.modes],
            ),
            max_concurrent_claims=request.max_concurrent_claims,
        )

        def dummy_callback(claw_id: str, event: BusEvent) -> None:
            pass

        await engine.connect_claw(claw_id, identity, dummy_callback)

        token = engine.generate_claw_token(claw_id)

        return ClawResponse(
            claw_id=claw_id,
            name=identity.name,
            state=identity.state.value,
            reliability_score=identity.reliability_score,
            token=token,
        )

    @app.post("/claws/{claw_id}/heartbeat")
    async def heartbeat(claw_id: str):
        """Send a heartbeat to maintain claw connection and TEC recovery."""
        engine = get_engine()
        state = await engine.heartbeat(claw_id)

        return {
            "claw_id": claw_id,
            "state": state.value,
            "timestamp": time.time(),
        }

    @app.get("/claws")
    async def list_claws():
        """List all connected claws."""
        engine = get_engine()

        return [
            {
                "claw_id": c.claw_id,
                "name": c.name,
                "state": c.state.value,
                "reliability_score": c.reliability_score,
                "capabilities": c.acceptance_filter.capability_offer,
            }
            for c in engine._claws.values()
        ]

    @app.get("/claws/{claw_id}/activity")
    async def claw_activity(
        claw_id: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        """Get recent activity log for a specific claw."""
        engine = get_engine()

        if claw_id not in engine._claws and claw_id not in engine._claw_activity:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "claw not found"},
            )

        return {
            "claw_id": claw_id,
            "activity": engine.get_claw_activity(claw_id, limit),
        }

    # =============================================================================
    # Schema Registry API
    # =============================================================================

    @app.get("/schemas")
    async def list_schemas():
        """List all registered schemas and their versions."""
        engine = get_engine()
        return engine._schema_registry.list_schemas()

    @app.get("/schemas/{fact_type}")
    async def get_schema(fact_type: str, version: Optional[str] = None):
        """Get schema for a fact type. Returns latest version if not specified."""
        engine = get_engine()
        schema = engine._schema_registry.get_schema(fact_type, version)

        if schema is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": f"Schema not found for {fact_type}"},
            )

        return schema.to_json()

    @app.post("/schemas/{fact_type}/validate")
    async def validate_payload(fact_type: str, request: dict, version: Optional[str] = None):
        """Validate a payload against a schema without publishing."""
        engine = get_engine()
        payload = request.get("payload", {})

        schema = engine._schema_registry.get_schema(fact_type, version)
        if schema is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": f"Schema not found for {fact_type}"},
            )

        is_valid, errors = schema.validate_payload(payload)

        return {
            "valid": is_valid,
            "errors": errors,
            "fact_type": fact_type,
            "schema_version": schema.version if schema else None,
        }

    # =============================================================================
    # Admin API
    # =============================================================================

    async def _verify_admin(x_admin_key: str = Header(default="")):
        """Dependency: verify admin auth via X-Admin-Key header."""
        expected = os.getenv("FACT_BUS_ADMIN_KEY", "")
        if expected and x_admin_key != expected:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "missing or invalid X-Admin-Key header"},
            )
        return None

    @app.get("/admin/dead-letter")
    async def get_dead_letter_facts(
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        auth_err=Depends(_verify_admin),
    ):
        """Get all facts in dead letter state."""
        if isinstance(auth_err, JSONResponse):
            return auth_err
        engine = get_engine()
        dead_facts = engine.query_facts(state=FactState.DEAD, limit=limit)
        return [_fact_to_response(f) for f in dead_facts]

    @app.post("/admin/facts/{fact_id}/redispatch")
    async def redispatch_fact(fact_id: str, auth_err=Depends(_verify_admin)):
        """Manually redispatch a dead/expired fact."""
        if isinstance(auth_err, JSONResponse):
            return auth_err

        engine = get_engine()

        if fact_id not in engine._facts:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "fact not found"},
            )

        fact = engine._facts[fact_id]

        from ..types import WorkflowStateMachine
        WorkflowStateMachine.transition(fact, FactState.PUBLISHED, force=True)
        fact.claimed_by = None
        fact.effective_priority = fact.priority
        fact.created_at = time.time()

        await engine._dispatch_fact(fact)

        return {
            "success": True,
            "fact_id": fact_id,
            "new_state": fact.state.value,
        }

    @app.post("/admin/claws/{claw_id}/isolate")
    async def isolate_claw(claw_id: str, auth_err=Depends(_verify_admin)):
        """Manually isolate a claw (emergency stop)."""
        if isinstance(auth_err, JSONResponse):
            return auth_err

        engine = get_engine()

        if claw_id not in engine._claws:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "claw not found"},
            )

        claw = engine._claws[claw_id]
        claw.state = ClawState.ISOLATED
        claw.transmit_error_counter = 256

        return {
            "success": True,
            "claw_id": claw_id,
            "state": claw.state.value,
        }

    @app.post("/admin/claws/{claw_id}/restore")
    async def restore_claw(claw_id: str, auth_err=Depends(_verify_admin)):
        """Restore an isolated claw to active state."""
        if isinstance(auth_err, JSONResponse):
            return auth_err

        engine = get_engine()

        if claw_id not in engine._claws:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "claw not found"},
            )

        claw = engine._claws[claw_id]
        claw.state = ClawState.ACTIVE
        claw.transmit_error_counter = 0
        claw.reliability_score = 1.0

        return {
            "success": True,
            "claw_id": claw_id,
            "state": claw.state.value,
            "reliability_score": claw.reliability_score,
        }

    @app.get("/admin/metrics")
    async def get_detailed_metrics():
        """Get detailed metrics for monitoring."""
        engine = get_engine()
        stats = engine.get_stats()

        # Add computed metrics
        total_facts = stats["facts"]["total"]
        by_state = stats["facts"]["by_state"]

        metrics = {
            **stats,
            "computed": {
                "resolution_rate": (
                    by_state.get("resolved", 0) / max(total_facts, 1)
                ),
                "dead_letter_rate": (
                    by_state.get("dead", 0) / max(total_facts, 1)
                ),
                "active_claims": by_state.get("claimed", 0) + by_state.get("processing", 0),
                "pending_facts": (
                    by_state.get("published", 0) + by_state.get("matched", 0)
                ),
            },
        }

        return metrics

    # =============================================================================
    # WebSocket Endpoint
    # =============================================================================

    @app.websocket("/ws/{claw_id}")
    async def websocket_endpoint(websocket: WebSocket, claw_id: str):
        """
        WebSocket endpoint for real-time event subscription.

        Connect with: ws://host:port/ws/{claw_id}

        After connecting, send your AcceptanceFilter as JSON:
        {
            "action": "subscribe",
            "filter": {
                "capability_offer": ["review", "python"],
                "domain_interests": ["backend"],
                "fact_type_patterns": ["code.*"],
                "priority_range": [0, 3],
                "modes": ["exclusive", "broadcast"]
            }
        }

        Events will be pushed as JSON:
        {
            "event_type": "fact_available",
            "fact": {...},
            "timestamp": 1709712000.0
        }
        """
        engine = get_engine()
        await websocket.accept()

        # Track pending events for this connection
        pending_events: list[BusEvent] = []

        def websocket_callback(cid: str, event: BusEvent) -> None:
            """Callback to receive events from the engine."""
            if cid == claw_id:
                pending_events.append(event)

        try:
            # Wait for subscription message
            subscription_data = await websocket.receive_json()

            if subscription_data.get("action") != "subscribe":
                await websocket.send_json({"error": "expected action: subscribe"})
                await websocket.close()
                return

            filter_data = subscription_data.get("filter", {})

            # Build or update claw identity
            if claw_id in engine._claws:
                identity = engine._claws[claw_id]
                identity.acceptance_filter = AcceptanceFilter(
                    capability_offer=filter_data.get("capability_offer", []),
                    domain_interests=filter_data.get("domain_interests", []),
                    fact_type_patterns=filter_data.get("fact_type_patterns", []),
                    priority_range=tuple(filter_data.get("priority_range", [0, 7])),
                    modes=[FactMode(m) for m in filter_data.get("modes", ["exclusive", "broadcast"])],
                )
            else:
                identity = ClawIdentity(
                    claw_id=claw_id,
                    name=subscription_data.get("name", "unnamed"),
                    acceptance_filter=AcceptanceFilter(
                        capability_offer=filter_data.get("capability_offer", []),
                        domain_interests=filter_data.get("domain_interests", []),
                        fact_type_patterns=filter_data.get("fact_type_patterns", []),
                        priority_range=tuple(filter_data.get("priority_range", [0, 7])),
                        modes=[FactMode(m) for m in filter_data.get("modes", ["exclusive", "broadcast"])],
                    ),
                )

            # Connect with WebSocket callback
            await engine.connect_claw(claw_id, identity, websocket_callback)

            await websocket.send_json({"status": "subscribed", "claw_id": claw_id})

            # Event loop
            while True:
                # Check for pending events
                while pending_events:
                    event = pending_events.pop(0)
                    await websocket.send_json(_event_to_dict(event))

                # Check for client messages (ping/pong or filter updates)
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=5.0,
                    )

                    if message.get("action") == "heartbeat":
                        await engine.heartbeat(claw_id)
                        await websocket.send_json({"type": "pong"})
                    elif message.get("action") == "update_filter":
                        # Update filter on the fly
                        filter_data = message.get("filter", {})
                        if claw_id in engine._claws:
                            engine._claws[claw_id].acceptance_filter = AcceptanceFilter(
                                capability_offer=filter_data.get("capability_offer", []),
                                domain_interests=filter_data.get("domain_interests", []),
                                fact_type_patterns=filter_data.get("fact_type_patterns", []),
                                priority_range=tuple(filter_data.get("priority_range", [0, 7])),
                                modes=[FactMode(m) for m in filter_data.get("modes", ["exclusive", "broadcast"])],
                            )
                            await websocket.send_json({"status": "filter_updated"})

                except asyncio.TimeoutError:
                    # No message, continue to check pending events
                    pass

        except WebSocketDisconnect:
            await engine.disconnect_claw(claw_id)
        except Exception as e:
            await engine.disconnect_claw(claw_id)
            raise

    # =============================================================================
    # Helpers
    # =============================================================================

    def _fact_to_response(fact: Fact) -> dict:
        """Convert Fact to API response dict."""
        return {
            "fact_id": fact.fact_id,
            "fact_type": fact.fact_type,
            "semantic_kind": fact.semantic_kind.value,
            "payload": fact.payload,
            "domain_tags": fact.domain_tags,
            "need_capabilities": fact.need_capabilities,
            "priority": fact.priority,
            "mode": fact.mode.value,
            "source_claw_id": fact.source_claw_id,
            "state": fact.state.value,
            "epistemic_state": fact.epistemic_state.value,
            "created_at": fact.created_at,
            "ttl_seconds": fact.ttl_seconds,
            "claimed_by": fact.claimed_by,
            "effective_priority": fact.effective_priority,
            "causation_depth": fact.causation_depth,
            "confidence": fact.confidence,
            "subject_key": fact.subject_key,
            "supersedes": fact.supersedes,
            "superseded_by": fact.superseded_by,
            "signature": fact.signature,
            "sequence_number": fact.sequence_number,
            "corroborations": fact.corroborations,
            "contradictions": fact.contradictions,
            "protocol_version": fact.protocol_version,
        }

    def _event_to_dict(event: BusEvent) -> dict:
        """Convert BusEvent to JSON dict."""
        result = {
            "event_type": event.event_type.value,
            "timestamp": event.timestamp,
        }
        if event.fact:
            result["fact"] = _fact_to_response(event.fact)
        if event.claw_id:
            result["claw_id"] = event.claw_id
        if event.detail:
            result["detail"] = event.detail
        return result

    return app
