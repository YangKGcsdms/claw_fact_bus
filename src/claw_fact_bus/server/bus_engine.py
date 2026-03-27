"""
Bus Core Engine.

Implements the complete fact bus lifecycle:
  - Content integrity verification (hash check on every publish)
  - Bus authority signature (HMAC stamp)
  - Dual state machine (workflow × epistemic)
  - Supersede mechanism for knowledge evolution
  - Corroboration/contradiction that directly affects fact trust
  - Formal workflow state transitions
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Callable, Optional

from ..filter import MatchResult, arbitrate, evaluate_filter
from ..flow_control import PublishGate, apply_aging
from ..persistence.jsonl_store import JSONLFactStore
from ..reliability import ErrorEvent, ReliabilityManager
from ..schema import SchemaRegistry, get_common_schemas
from ..types import (
    BusEvent,
    BusEventType,
    ClawIdentity,
    ClawState,
    EpistemicState,
    EpistemicStateMachine,
    Fact,
    FactMode,
    FactState,
    InvalidStateTransition,
    Priority,
    SemanticKind,
    WorkflowStateMachine,
)

logger = logging.getLogger("claw_fact_bus.engine")

EventCallback = Callable[[str, BusEvent], None]

MAX_EVENT_RETRIES = 3


class BusEngine:
    """
    Central bus engine implementing the Fact Bus protocol.

    All mutating public methods are async and protected by asyncio.Lock.
    """

    def __init__(self, data_dir: str | Path = ".data") -> None:
        data_path = Path(data_dir)

        # Concurrency
        self._fact_lock = asyncio.Lock()
        self._claw_lock = asyncio.Lock()

        # Bus identity & signing
        self._bus_secret = os.environ.get(
            "FACT_BUS_SECRET", secrets.token_hex(32)
        )
        self._sequence_counter: int = 0

        # Persistence
        self._store = JSONLFactStore(data_path)

        # Registries
        self._facts: dict[str, Fact] = {}
        self._claws: dict[str, ClawIdentity] = {}
        self._claw_connections: dict[str, EventCallback] = {}

        # Indexes
        self._active_claims: dict[str, int] = defaultdict(int)
        self._subject_index: dict[str, str] = {}  # subject_key -> latest fact_id

        # Auth
        self._claw_tokens: dict[str, str] = {}

        # Protocol components
        self._publish_gate = PublishGate()
        self._reliability = ReliabilityManager()

        # Event dispatch
        self._event_callbacks: list[EventCallback] = []
        self._background_tasks: set[asyncio.Task] = set()

        # Per-claw activity log (bounded ring buffer per claw)
        self._claw_activity: dict[str, deque[dict]] = defaultdict(
            lambda: deque(maxlen=200)
        )

        # Schema
        self._schema_registry = SchemaRegistry(data_path / "schemas")
        self._register_common_schemas()

        # Recovery
        self._recover_from_store()
        self._start_background_tasks()

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def _register_common_schemas(self) -> None:
        for schema in get_common_schemas():
            self._schema_registry.register(schema)

    def _recover_from_store(self) -> None:
        recovered = 0
        for fact, event, _ in self._store.read_all():
            if event == "publish":
                self._facts[fact.fact_id] = fact
                if fact.subject_key:
                    self._subject_index[f"{fact.subject_key}:{fact.fact_type}"] = fact.fact_id
            elif event in ("claim", "resolve", "expire", "dead"):
                if fact.fact_id in self._facts:
                    self._facts[fact.fact_id].state = fact.state
                    self._facts[fact.fact_id].claimed_by = fact.claimed_by
                    self._facts[fact.fact_id].resolved_at = fact.resolved_at
            elif event == "purge":
                if fact.fact_id in self._facts:
                    removed = self._facts.pop(fact.fact_id)
                    if removed.subject_key:
                        sk = f"{removed.subject_key}:{removed.fact_type}"
                        if self._subject_index.get(sk) == fact.fact_id:
                            del self._subject_index[sk]
            elif event == "causation_repair":
                if fact.fact_id in self._facts:
                    self._facts[fact.fact_id].causation_chain = list(fact.causation_chain)
                    self._facts[fact.fact_id].causation_depth = fact.causation_depth
            recovered += 1

        for fact in self._facts.values():
            if fact.claimed_by and fact.state in (FactState.CLAIMED, FactState.PROCESSING):
                self._active_claims[fact.claimed_by] += 1

        if recovered > 0:
            logger.info("Recovered %d fact events from store", recovered)

    def _start_background_tasks(self) -> None:
        for coro in (self._expiration_loop(), self._gc_loop(), self._compaction_loop()):
            task = asyncio.create_task(coro)
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _expiration_loop(self) -> None:
        while True:
            await asyncio.sleep(10)
            expired_count = 0
            async with self._fact_lock:
                for fact in list(self._facts.values()):
                    if fact.state in (FactState.PUBLISHED, FactState.MATCHED) and fact.is_expired():
                        await self._mark_dead_unlocked(fact, "ttl_expired")
                        expired_count += 1
            if expired_count > 0:
                logger.info("Expired %d facts", expired_count)

    GC_INTERVAL_SECONDS = 60
    GC_RETAIN_RESOLVED_SECONDS = 600
    GC_RETAIN_DEAD_SECONDS = 3600
    GC_MAX_FACTS = 10_000
    COMPACTION_INTERVAL_SECONDS = 3600

    def _gc_collect_candidates(self, now: float) -> list[str]:
        """Return fact_ids eligible for GC (same rules as background GC)."""
        to_delete: list[str] = []
        for fid, fact in self._facts.items():
            if fact.state == FactState.RESOLVED:
                age = now - (fact.resolved_at or fact.created_at)
                if age > self.GC_RETAIN_RESOLVED_SECONDS:
                    to_delete.append(fid)
            elif fact.state == FactState.DEAD:
                age = now - fact.created_at
                if age > self.GC_RETAIN_DEAD_SECONDS:
                    to_delete.append(fid)

        remaining = len(self._facts) - len(to_delete)
        if remaining > self.GC_MAX_FACTS:
            delete_set = set(to_delete)
            terminal = sorted(
                ((fid, f) for fid, f in self._facts.items()
                 if f.state in (FactState.RESOLVED, FactState.DEAD) and fid not in delete_set),
                key=lambda x: x[1].created_at,
            )
            overflow = remaining - self.GC_MAX_FACTS
            to_delete.extend(fid for fid, _ in terminal[:overflow])
        return to_delete

    async def _gc_loop(self) -> None:
        while True:
            await asyncio.sleep(self.GC_INTERVAL_SECONDS)
            now = time.time()
            to_delete: list[str] = []
            async with self._fact_lock:
                to_delete = self._gc_collect_candidates(now)
                for fid in to_delete:
                    del self._facts[fid]
            if to_delete:
                logger.info("GC collected %d facts", len(to_delete))

    async def _compaction_loop(self) -> None:
        while True:
            await asyncio.sleep(self.COMPACTION_INTERVAL_SECONDS)
            try:
                async with self._fact_lock:
                    removed = self._store.compact(self._facts)
                if removed > 0:
                    logger.info("Log compaction removed %d stale entries", removed)
            except Exception:
                logger.exception("Log compaction failed")

    # -------------------------------------------------------------------------
    # Bus Signing
    # -------------------------------------------------------------------------

    def _next_sequence(self) -> int:
        self._sequence_counter += 1
        return self._sequence_counter

    def _compute_signature(self, fact: Fact) -> str:
        """Bus authority HMAC over immutable record fields."""
        message = (
            f"{fact.fact_id}|{fact.content_hash}|{fact.source_claw_id}"
            f"|{fact.fact_type}|{fact.created_at}"
        )
        return hmac.new(
            self._bus_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()

    def _verify_signature(self, fact: Fact) -> bool:
        if not fact.signature:
            return True  # unsigned fact
        return hmac.compare_digest(fact.signature, self._compute_signature(fact))

    # -------------------------------------------------------------------------
    # Claw Management
    # -------------------------------------------------------------------------

    def generate_claw_token(self, claw_id: str) -> str:
        token = secrets.token_hex(24)
        self._claw_tokens[claw_id] = hashlib.sha256(token.encode()).hexdigest()
        return token

    def verify_claw_token(self, claw_id: str, token: str) -> bool:
        if claw_id not in self._claw_tokens:
            return False
        expected = self._claw_tokens[claw_id]
        provided = hashlib.sha256(token.encode()).hexdigest()
        return secrets.compare_digest(expected, provided)

    async def connect_claw(
        self, claw_id: str, identity: ClawIdentity, event_callback: EventCallback
    ) -> ClawIdentity:
        async with self._claw_lock:
            identity.claw_id = claw_id
            identity.connected_at = time.time()
            identity.last_heartbeat = time.time()
            identity.state = ClawState.ACTIVE
            self._claws[claw_id] = identity
            self._claw_connections[claw_id] = event_callback
            self._reliability.record_event(identity, ErrorEvent.HEARTBEAT_OK)
        self._record_activity(claw_id, "connect")
        await self._replay_recent_facts(claw_id)
        return identity

    async def disconnect_claw(self, claw_id: str) -> None:
        async with self._claw_lock:
            if claw_id in self._claws:
                self._claws[claw_id].state = ClawState.OFFLINE
                del self._claws[claw_id]
            self._claw_connections.pop(claw_id, None)
            self._claw_tokens.pop(claw_id, None)
        self._record_activity(claw_id, "disconnect")

    async def heartbeat(self, claw_id: str) -> ClawState:
        async with self._claw_lock:
            if claw_id not in self._claws:
                return ClawState.OFFLINE
            claw = self._claws[claw_id]
            claw.last_heartbeat = time.time()
            self._reliability.record_event(claw, ErrorEvent.HEARTBEAT_OK)
            return claw.state

    # -------------------------------------------------------------------------
    # Fact Lifecycle
    # -------------------------------------------------------------------------

    async def publish_fact(self, fact: Fact) -> tuple[bool, str, Optional[str]]:
        """
        Publish a fact onto the bus.

        Publish pipeline:
          1. Compute content hash
          2. Verify integrity (hash matches payload)
          3. Reliability gate (claw health)
          4. Flow control gates
          5. Schema validation
          6. Accept: assign sequence, sign, set states
          7. Handle supersede (if subject_key or supersedes set)
          8. Persist
          9. Dispatch to matching claws
        """
        # Step 1-2: Integrity
        fact.compute_content_hash()
        if not fact.verify_content_hash():
            return False, "content integrity check failed", None

        async with self._fact_lock:
            # Step 3: Reliability gate
            if fact.source_claw_id and fact.source_claw_id in self._claws:
                claw = self._claws[fact.source_claw_id]
                ok, reason = self._reliability.should_accept_publication(claw, fact)
                if not ok:
                    self._reliability.record_event(claw, ErrorEvent.SCHEMA_VIOLATION)
                    return False, reason, None

            # Step 4: Flow control
            ok, reason = self._publish_gate.check(fact)
            if not ok:
                if fact.source_claw_id in self._claws:
                    self._reliability.record_event(
                        self._claws[fact.source_claw_id], ErrorEvent.RATE_EXCEEDED
                    )
                return False, reason, None

            # Step 5: Schema validation
            schema_ok, schema_errors = self._schema_registry.validate_fact(
                fact.fact_type, fact.payload, fact.schema_version
            )
            if not schema_ok:
                if fact.source_claw_id in self._claws:
                    self._reliability.record_event(
                        self._claws[fact.source_claw_id], ErrorEvent.SCHEMA_VIOLATION
                    )
                return False, f"schema validation failed: {'; '.join(schema_errors)}", None

            # Step 6: Accept — sign and stamp
            WorkflowStateMachine.transition(fact, FactState.PUBLISHED)
            fact.effective_priority = fact.priority
            fact.sequence_number = self._next_sequence()
            fact.signature = self._compute_signature(fact)
            fact.epistemic_state = EpistemicState.ASSERTED

            self._facts[fact.fact_id] = fact

            # Step 7: Supersede
            self._handle_supersede(fact)

            # Step 8: Persist
            self._store.append(fact, "publish")

        # Step 9: Dispatch (outside lock)
        self._record_activity(fact.source_claw_id, "publish", fact.fact_id, fact.fact_type)
        await self._dispatch_fact(fact)
        return True, "ok", fact.fact_id

    def _handle_supersede(self, new_fact: Fact) -> None:
        """Handle fact supersession (caller must hold _fact_lock)."""
        target_id: str | None = None

        # Explicit supersede
        if new_fact.supersedes and new_fact.supersedes in self._facts:
            target_id = new_fact.supersedes

        # Auto-supersede by subject_key
        elif new_fact.subject_key:
            idx_key = f"{new_fact.subject_key}:{new_fact.fact_type}"
            old_id = self._subject_index.get(idx_key)
            if old_id and old_id in self._facts and old_id != new_fact.fact_id:
                old_fact = self._facts[old_id]
                if old_fact.state not in (FactState.RESOLVED, FactState.DEAD):
                    target_id = old_id
            self._subject_index[idx_key] = new_fact.fact_id

        if target_id:
            old_fact = self._facts[target_id]
            old_fact.superseded_by = new_fact.fact_id
            EpistemicStateMachine.recompute(old_fact)
            self._store.append(old_fact, "supersede", {"superseded_by": new_fact.fact_id})

    async def claim_fact(self, fact_id: str, claw_id: str) -> tuple[bool, str]:
        async with self._fact_lock:
            if fact_id not in self._facts:
                return False, "fact not found"
            fact = self._facts[fact_id]

            if fact.mode != FactMode.EXCLUSIVE:
                return False, "fact is not exclusive mode"

            if fact.state not in (FactState.PUBLISHED, FactState.MATCHED):
                if fact.claimed_by == claw_id:
                    return True, "already claimed by you"
                if fact.claimed_by:
                    return False, f"already claimed by {fact.claimed_by}"
                return False, f"fact is {fact.state.value}"

            if claw_id in self._claws:
                claw = self._claws[claw_id]
                current_claims = self._active_claims.get(claw_id, 0)
                if current_claims >= claw.max_concurrent_claims:
                    return False, (
                        f"claw already has {current_claims} active claims "
                        f"(max {claw.max_concurrent_claims})"
                    )

            WorkflowStateMachine.transition(fact, FactState.CLAIMED)
            fact.claimed_by = claw_id
            self._active_claims[claw_id] = self._active_claims.get(claw_id, 0) + 1
            self._store.append(fact, "claim", {"claimer": claw_id})

        self._record_activity(claw_id, "claim", fact_id, fact.fact_type)
        await self._notify_claimed(fact, claw_id)
        return True, "ok"

    async def resolve_fact(
        self,
        fact_id: str,
        claw_id: str,
        result_facts: Optional[list[Fact]] = None,
    ) -> tuple[bool, str]:
        async with self._fact_lock:
            if fact_id not in self._facts:
                return False, "fact not found"
            fact = self._facts[fact_id]

            if fact.claimed_by != claw_id:
                return False, f"not claimed by you (claimed by {fact.claimed_by})"

            WorkflowStateMachine.transition(fact, FactState.RESOLVED)
            fact.resolved_at = time.time()

            if self._active_claims.get(claw_id, 0) > 0:
                self._active_claims[claw_id] -= 1

            self._store.append(fact, "resolve", {"resolver": claw_id})

            if claw_id in self._claws:
                self._reliability.record_event(self._claws[claw_id], ErrorEvent.FACT_RESOLVED)

        self._record_activity(claw_id, "resolve", fact_id, fact.fact_type)

        if result_facts:
            for child in result_facts:
                child = fact.derive_child(
                    fact_type=child.fact_type,
                    payload=child.payload,
                    source_claw_id=claw_id,
                    domain_tags=child.domain_tags,
                    need_capabilities=child.need_capabilities,
                    priority=child.priority,
                    mode=child.mode,
                    semantic_kind=child.semantic_kind,
                )
                await self.publish_fact(child)

        return True, "ok"

    async def corroborate_fact(self, fact_id: str, claw_id: str) -> tuple[bool, str]:
        """
        Corroborate a fact. Directly affects fact's epistemic state.

        Returns (success, new_epistemic_state).
        """
        async with self._fact_lock:
            if fact_id not in self._facts:
                return False, "fact not found"
            fact = self._facts[fact_id]

            if claw_id == fact.source_claw_id:
                return False, "cannot corroborate your own fact"

            if claw_id in fact.corroborations:
                return True, fact.epistemic_state.value

            fact.corroborations.append(claw_id)
            old_state = fact.epistemic_state
            EpistemicStateMachine.recompute(fact)

            # TEC reward to source claw
            if fact.source_claw_id in self._claws:
                self._reliability.record_event(
                    self._claws[fact.source_claw_id], ErrorEvent.CORROBORATION
                )

            self._store.append(fact, "corroborate", {
                "by": claw_id, "epistemic_state": fact.epistemic_state.value
            })

        if fact.epistemic_state != old_state:
            await self._notify_trust_changed(fact, old_state)

        return True, fact.epistemic_state.value

    async def contradict_fact(self, fact_id: str, claw_id: str) -> tuple[bool, str]:
        """
        Contradict a fact. Directly affects fact's epistemic state.

        Returns (success, new_epistemic_state).
        """
        async with self._fact_lock:
            if fact_id not in self._facts:
                return False, "fact not found"
            fact = self._facts[fact_id]

            if claw_id == fact.source_claw_id:
                return False, "cannot contradict your own fact"

            if claw_id in fact.contradictions:
                return True, fact.epistemic_state.value

            fact.contradictions.append(claw_id)
            old_state = fact.epistemic_state
            EpistemicStateMachine.recompute(fact)

            if fact.source_claw_id in self._claws:
                self._reliability.record_event(
                    self._claws[fact.source_claw_id], ErrorEvent.CONTRADICTION
                )

            self._store.append(fact, "contradict", {
                "by": claw_id, "epistemic_state": fact.epistemic_state.value
            })

        if fact.epistemic_state != old_state:
            await self._notify_trust_changed(fact, old_state)

        return True, fact.epistemic_state.value

    async def release_fact(self, fact_id: str, claw_id: str) -> tuple[bool, str]:
        async with self._fact_lock:
            if fact_id not in self._facts:
                return False, "fact not found"
            fact = self._facts[fact_id]
            if fact.claimed_by != claw_id:
                return False, "not claimed by you"

            if self._active_claims.get(claw_id, 0) > 0:
                self._active_claims[claw_id] -= 1

            WorkflowStateMachine.transition(fact, FactState.PUBLISHED)
            fact.claimed_by = None

        self._record_activity(claw_id, "release", fact_id, fact.fact_type)
        await self._dispatch_fact(fact)
        return True, "ok"

    # -------------------------------------------------------------------------
    # Query
    # -------------------------------------------------------------------------

    def query_facts(
        self,
        fact_type: Optional[str] = None,
        state: Optional[FactState] = None,
        source_claw_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[Fact]:
        results = []
        for fact in self._facts.values():
            if fact_type and fact.fact_type != fact_type:
                continue
            if state and fact.state != state:
                continue
            if source_claw_id and fact.source_claw_id != source_claw_id:
                continue
            results.append(fact)
        return sorted(results, key=lambda x: x.created_at, reverse=True)[:limit]

    def get_stats(self) -> dict:
        return {
            "facts": {
                "total": len(self._facts),
                "by_state": self._count_by_state(),
                "by_epistemic": self._count_by_epistemic(),
            },
            "claws": {
                "connected": len(self._claws),
                "by_state": self._count_claws_by_state(),
            },
            "schemas": self._schema_registry.get_stats(),
            "store": self._store.get_stats(),
            "protocol_version": "2.0.0",
        }

    def _count_by_state(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for f in self._facts.values():
            counts[f.state.value] += 1
        return dict(counts)

    def _count_by_epistemic(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for f in self._facts.values():
            counts[f.epistemic_state.value] += 1
        return dict(counts)

    def _count_claws_by_state(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for c in self._claws.values():
            counts[c.state.value] += 1
        return dict(counts)

    def _record_activity(self, claw_id: str, action: str, fact_id: str = "", detail: str = "") -> None:
        self._claw_activity[claw_id].append({
            "action": action,
            "fact_id": fact_id,
            "detail": detail,
            "timestamp": time.time(),
        })

    def get_claw_activity(self, claw_id: str, limit: int = 50) -> list[dict]:
        entries = list(self._claw_activity.get(claw_id, []))
        return entries[-limit:][::-1]

    # -------------------------------------------------------------------------
    # Admin: cleanup, causation repair, storage
    # -------------------------------------------------------------------------

    def _unlink_subject_index(self, fact: Fact) -> None:
        if fact.subject_key:
            sk = f"{fact.subject_key}:{fact.fact_type}"
            if self._subject_index.get(sk) == fact.fact_id:
                del self._subject_index[sk]

    def _delete_fact_unlocked(self, fact_id: str) -> tuple[bool, str]:
        if fact_id not in self._facts:
            return False, "fact not found"
        fact = self._facts.pop(fact_id)
        if fact.claimed_by and fact.state in (FactState.CLAIMED, FactState.PROCESSING):
            if self._active_claims.get(fact.claimed_by, 0) > 0:
                self._active_claims[fact.claimed_by] -= 1
        self._unlink_subject_index(fact)
        self._store.append(fact, "purge", {"reason": "admin"})
        return True, "ok"

    async def admin_delete_fact(self, fact_id: str) -> tuple[bool, str]:
        async with self._fact_lock:
            return self._delete_fact_unlocked(fact_id)

    def find_broken_chains(self) -> list[dict]:
        """Facts whose causation_chain references missing ancestor fact_ids."""
        out: list[dict] = []
        for fid, fact in self._facts.items():
            missing = [a for a in fact.causation_chain if a not in self._facts]
            if missing:
                out.append({
                    "fact_id": fid,
                    "missing_ancestors": missing,
                    "causation_chain": list(fact.causation_chain),
                })
        return out

    def find_orphan_facts(self) -> list[dict]:
        """Alias: facts with broken upstream chain (same as find_broken_chains)."""
        return self.find_broken_chains()

    async def repair_causation_chains(self, fact_id: str | None = None) -> dict:
        """Drop missing ids from causation_chain; persist as causation_repair events."""
        async with self._fact_lock:
            to_touch: list[Fact] = []
            if fact_id:
                if fact_id in self._facts:
                    to_touch = [self._facts[fact_id]]
            else:
                for f in self._facts.values():
                    if any(a not in self._facts for a in f.causation_chain):
                        to_touch.append(f)
            repaired: list[str] = []
            for fact in to_touch:
                new_chain = [a for a in fact.causation_chain if a in self._facts]
                if new_chain != fact.causation_chain:
                    fact.causation_chain = new_chain
                    fact.causation_depth = len(new_chain)
                    self._store.append(fact, "causation_repair", {})
                    repaired.append(fact.fact_id)
            return {"repaired": repaired, "count": len(repaired)}

    async def admin_cleanup_facts(
        self,
        fact_states: list[str] | None,
        older_than_seconds: float | None,
        keep_most_recent: int,
        dry_run: bool,
    ) -> dict:
        """
        Delete facts matching state filter (default: resolved+dead), optional age,
        and keep the ``keep_most_recent`` newest matches (by created_at).
        """
        if not fact_states:
            state_filter = {FactState.RESOLVED.value, FactState.DEAD.value}
        else:
            state_filter = set(fact_states)
        async with self._fact_lock:
            now = time.time()
            candidates: list[tuple[str, Fact]] = []
            for fid, fact in self._facts.items():
                if fact.state.value not in state_filter:
                    continue
                if older_than_seconds is not None:
                    if now - fact.created_at < older_than_seconds:
                        continue
                candidates.append((fid, fact))
            candidates.sort(key=lambda x: x[1].created_at, reverse=True)
            if keep_most_recent > 0:
                to_delete = candidates[keep_most_recent:]
            else:
                to_delete = candidates
            ids = [fid for fid, _ in to_delete]
            if dry_run:
                return {
                    "dry_run": True,
                    "count": len(ids),
                    "fact_ids": ids,
                }
            deleted: list[str] = []
            for fid in ids:
                ok, _ = self._delete_fact_unlocked(fid)
                if ok:
                    deleted.append(fid)
            return {"dry_run": False, "count": len(deleted), "deleted": deleted}

    async def admin_run_gc(self) -> dict:
        """Run the same in-memory GC as the background loop (no purge log entries)."""
        async with self._fact_lock:
            now = time.time()
            to_delete = self._gc_collect_candidates(now)
            for fid in to_delete:
                del self._facts[fid]
        return {"removed": len(to_delete), "fact_ids": to_delete}

    async def admin_compact_store(self) -> dict:
        async with self._fact_lock:
            removed = self._store.compact(self._facts)
        return {"stale_entries_removed": removed}

    # -------------------------------------------------------------------------
    # Internal: Dispatch and Notifications
    # -------------------------------------------------------------------------

    async def _dispatch_fact(self, fact: Fact) -> None:
        matched_claws: list[tuple[ClawIdentity, MatchResult]] = []

        for claw in list(self._claws.values()):
            match = evaluate_filter(fact, claw)
            if match.matched:
                matched_claws.append((claw, match))

        if not matched_claws:
            return

        async with self._fact_lock:
            if fact.state == FactState.PUBLISHED:
                WorkflowStateMachine.transition(fact, FactState.MATCHED)

        if fact.mode == FactMode.EXCLUSIVE:
            winners = arbitrate(fact, [c for c, _ in matched_claws])
            winner_ids = {c.claw_id for c in winners}
            ordered = (
                [(c, m) for c, m in matched_claws if c.claw_id in winner_ids]
                + [(c, m) for c, m in matched_claws if c.claw_id not in winner_ids]
            )
        else:
            ordered = matched_claws

        for claw, _ in ordered:
            await self._send_event(
                claw.claw_id,
                BusEvent(event_type=BusEventType.FACT_AVAILABLE, fact=fact),
            )

    async def _notify_claimed(self, fact: Fact, claimed_by: str) -> None:
        for claw in list(self._claws.values()):
            if claw.claw_id == claimed_by:
                continue
            match = evaluate_filter(fact, claw)
            if match.matched:
                await self._send_event(
                    claw.claw_id,
                    BusEvent(
                        event_type=BusEventType.FACT_CLAIMED,
                        fact=fact, claw_id=claimed_by,
                    ),
                )

    async def _notify_trust_changed(self, fact: Fact, old_state: EpistemicState) -> None:
        """Notify interested claws when a fact's epistemic state changes."""
        for claw in list(self._claws.values()):
            match = evaluate_filter(fact, claw)
            if match.matched:
                await self._send_event(
                    claw.claw_id,
                    BusEvent(
                        event_type=BusEventType.FACT_TRUST_CHANGED,
                        fact=fact,
                        detail=f"{old_state.value} -> {fact.epistemic_state.value}",
                    ),
                )

    async def _replay_recent_facts(self, claw_id: str) -> None:
        if claw_id not in self._claws:
            return
        claw = self._claws[claw_id]
        recent_facts = sorted(
            [f for f in self._facts.values() if f.state in (FactState.PUBLISHED, FactState.MATCHED)],
            key=lambda x: x.created_at, reverse=True,
        )[:50]
        for fact in reversed(recent_facts):
            match = evaluate_filter(fact, claw)
            if match.matched:
                apply_aging(fact)
                await self._send_event(
                    claw_id,
                    BusEvent(event_type=BusEventType.FACT_AVAILABLE, fact=fact),
                )

    async def _mark_dead(self, fact: Fact, reason: str) -> None:
        async with self._fact_lock:
            await self._mark_dead_unlocked(fact, reason)

    async def _mark_dead_unlocked(self, fact: Fact, reason: str) -> None:
        if fact.claimed_by and self._active_claims.get(fact.claimed_by, 0) > 0:
            self._active_claims[fact.claimed_by] -= 1

        WorkflowStateMachine.transition(fact, FactState.DEAD, force=True)
        self._store.append(fact, "dead", {"reason": reason})

        for claw in list(self._claws.values()):
            match = evaluate_filter(fact, claw)
            if match.matched:
                await self._send_event(
                    claw.claw_id,
                    BusEvent(event_type=BusEventType.FACT_DEAD, fact=fact, detail=reason),
                )

        if fact.source_claw_id in self._claws:
            self._reliability.record_event(
                self._claws[fact.source_claw_id], ErrorEvent.FACT_EXPIRED
            )

    async def _send_event(self, claw_id: str, event: BusEvent) -> None:
        if claw_id not in self._claw_connections:
            return
        callback = self._claw_connections[claw_id]
        last_err = None
        for attempt in range(MAX_EVENT_RETRIES):
            try:
                callback(claw_id, event)
                return
            except Exception as e:
                last_err = e
                if attempt < MAX_EVENT_RETRIES - 1:
                    await asyncio.sleep(0.05 * (attempt + 1))
        logger.warning(
            "Failed to deliver %s to claw %s after %d attempts: %s",
            event.event_type.value, claw_id, MAX_EVENT_RETRIES, last_err,
        )

    def register_event_callback(self, callback: EventCallback) -> None:
        self._event_callbacks.append(callback)

    def unregister_event_callback(self, callback: EventCallback) -> None:
        if callback in self._event_callbacks:
            self._event_callbacks.remove(callback)
