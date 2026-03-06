# Claw Fact Bus Protocol Specification v0.1

> A CAN-Bus inspired, Event-Driven fact bus for AI agent (claw) cluster coordination.

---

## 1. Design Philosophy

### 1.1 Core Axiom

**Facts, not commands.** The bus carries statements about reality. A claw never tells another claw what to do; it states what has happened, what exists, or what is needed. The responding claw acts on its own judgment.

```
✅  "file auth.py modified, diff: +23 -5, domain: authentication"
✅  "user requested code review for PR #42"
✅  "claw-B claimed fact-0x3A1"
❌  "claw-B, go review auth.py"       ← command, forbidden
```

### 1.2 Architectural Lineage

| Source | What we take |
|--------|-------------|
| **CAN Bus** (ISO 11898) | Content-addressed messaging, broadcast + local filtering, priority arbitration, error state machine (TEC/REC), no central master |
| **EDA** (Event-Driven Architecture) | Event sourcing (immutable append-only log), schema registry, idempotent consumption, saga/choreography patterns |

### 1.3 Design Principles

1. **Content addresses, not destination addresses** — A fact's type and tags describe WHAT it is, not WHO should handle it.
2. **Broadcast medium, local filtering** — All facts are visible to all claws. Each claw decides what it cares about via acceptance filters.
3. **No central orchestrator** — Workflow emerges from the choreography of facts, not from a conductor.
4. **Atomic and immutable** — A fact, once published, cannot be modified. New facts can supersede old ones.
5. **Fail-safe degradation** — Misbehaving claws are progressively isolated, never crash the bus.

---

## 2. Protocol Entities

### 2.1 Fact

The atomic unit of communication. Analogous to a CAN frame.

| Field | Type | Description |
|-------|------|-------------|
| `fact_id` | string | Globally unique identifier (UUID hex, 16 chars) |
| `fact_type` | string | Dot-notation taxonomy (e.g. `code.review.needed`) |
| `payload` | object | The fact data. Schema determined by `fact_type` + `schema_version` |
| `domain_tags` | string[] | Content domain tags (e.g. `["python", "auth"]`) |
| `need_capabilities` | string[] | Capabilities needed to handle this fact |
| `priority` | int 0-7 | Lower = higher priority (CAN convention). See §4.1 |
| `mode` | enum | `exclusive` (one handler) or `broadcast` (all matching) |
| `source_claw_id` | string | Publisher's claw ID |
| `causation_chain` | string[] | Ordered list of ancestor fact IDs |
| `causation_depth` | int | Length of causation chain |
| `created_at` | float | Unix timestamp of creation |
| `ttl_seconds` | int | Time to live. Default 300s. After expiry → dead letter |
| `schema_version` | string | Schema version for this fact_type |
| `confidence` | float 0-1 | Publisher's self-assessed confidence |
| `content_hash` | string | SHA256 of canonical JSON payload |

Bus-managed fields (not set by publisher):

| Field | Type | Description |
|-------|------|-------------|
| `state` | enum | `created → published → matched → claimed → processing → resolved → dead` |
| `claimed_by` | string? | Claw ID that claimed (exclusive mode only) |
| `resolved_at` | float? | Timestamp of resolution |
| `effective_priority` | int? | Priority after aging adjustment |

### 2.2 Claw Identity

An agent's presence on the bus. Analogous to a CAN ECU.

| Field | Type | Description |
|-------|------|-------------|
| `claw_id` | string | Unique identifier (UUID hex, 12 chars) |
| `name` | string | Human-readable name |
| `description` | string | What this claw does |
| `acceptance_filter` | AcceptanceFilter | Determines which facts this claw receives |
| `max_concurrent_claims` | int | Max exclusive facts processable simultaneously |
| `state` | enum | `active`, `degraded`, `isolated`, `offline` |
| `transmit_error_counter` | int | TEC (CAN-style error counter) |
| `reliability_score` | float 0-1 | Derived from TEC. Used in arbitration |

### 2.3 Acceptance Filter

CAN-style mask/filter registers in software.

| Field | Type | Description |
|-------|------|-------------|
| `capability_offer` | string[] | What this claw can do (e.g. `["review", "python"]`) |
| `domain_interests` | string[] | What domains it subscribes to |
| `fact_type_patterns` | string[] | Glob patterns (e.g. `code.*`, `deploy.*.completed`) |
| `priority_range` | (int, int) | Accepted priority range (low, high) |
| `modes` | enum[] | Which fact modes it accepts |

---

## 3. Matching Protocol

### 3.1 Filter Evaluation

A fact reaches a claw if and only if ALL of the following pass:

```
Gate 0: claw.state ∈ {active, degraded}                     (not isolated/offline)
Gate 1: fact.effective_priority ∈ claw.filter.priority_range (priority mask)
Gate 2: fact.mode ∈ claw.filter.modes                       (mode compatibility)
Gate 3: AT LEAST ONE content match:
        a) fact.need_capabilities ∩ claw.capability_offer ≠ ∅
        b) fact.domain_tags ∩ claw.domain_interests ≠ ∅
        c) fact.fact_type matches any claw.fact_type_patterns (glob)
```

Special case: a claw with empty filters (no capabilities, no domains, no patterns) is a **monitor node** — it receives all facts. Useful for logging, dashboards, debugging.

### 3.2 Match Scoring

When a fact matches multiple claws, a composite score determines preference:

```
score = (capability_overlap × 10 + domain_overlap × 5 + type_hit × 3) × reliability_score
```

### 3.3 Arbitration

| Mode | Behavior |
|------|----------|
| `broadcast` | All matched claws receive the fact. No arbitration needed. |
| `exclusive` | Highest-scoring claw wins. Ties broken by: reliability → claw_id (deterministic). |

---

## 4. Priority and Aging

### 4.1 Priority Levels

Mirroring CAN's convention (J1939 3-bit priority field):

| Value | Name | Use case |
|-------|------|----------|
| 0 | CRITICAL | System failures, data loss prevention |
| 1 | HIGH | User-facing blocking tasks |
| 2 | ELEVATED | Important but not blocking |
| 3 | NORMAL | Default for most facts |
| 4 | LOW | Background tasks |
| 5 | BACKGROUND | Housekeeping, optimization |
| 6 | IDLE | Best-effort work |
| 7 | BULK | Batch processing, can wait indefinitely |

### 4.2 Aging Mechanism

To prevent starvation of low-priority facts:

- Every `aging_interval` seconds (default 30s), an unclaimed fact's `effective_priority` improves by 1.
- Aging floor: `HIGH` (priority 1). Facts never age into `CRITICAL` — that level is reserved for genuine emergencies.
- Example: a `BULK` (7) fact unclaimed for 150s → effective priority becomes `ELEVATED` (2).

---

## 5. Reliability and Fault Confinement

### 5.1 Error State Machine

Directly modeled after CAN ISO 11898-1 §6.7:

```
              TEC < 128                TEC ≥ 128              TEC ≥ 256
  ┌─────────────────────┐    ┌─────────────────────┐    ┌──────────────────┐
  │       ACTIVE         │───▶│      DEGRADED        │───▶│     ISOLATED      │
  │                      │    │                      │    │                  │
  │  Normal operation    │◀───│  Facts marked low-   │◀───│  Cannot publish  │
  │                      │    │  confidence (≤0.3)   │    │  Facts dropped   │
  └─────────────────────┘    └─────────────────────┘    └──────────────────┘
         ▲                                                        │
         └────────────────────────────────────────────────────────┘
                      Recovery: TEC drops below thresholds
                      (requires sustained clean heartbeats)
```

### 5.2 Error Counter Rules

| Event | TEC Change | CAN Equivalent |
|-------|-----------|----------------|
| Fact contradicted by another claw | +8 | Transmit error |
| Fact rejected by schema validation | +8 | Form error |
| Fact expired without resolution | +2 | Stuff error |
| Rate limit exceeded | +1 | Overload frame |
| Fact corroborated by another claw | -1 | Successful transmit |
| Fact successfully resolved | -1 | Successful transmit |
| Successful heartbeat | -1 | Recessive bit detection |

TEC floor is 0 (never goes negative).

### 5.3 Recovery Protocol

A claw in `isolated` state must accumulate enough `-1` events (via heartbeats) to bring TEC below 128 before returning to `active`. This requires at minimum 128 consecutive successful heartbeats — mirroring CAN's bus-off recovery requirement.

---

## 6. Flow Control and Storm Protection

### 6.1 Defense 1: Causation Depth Breaker

- Every fact carries `causation_depth` (incremented from parent).
- **Hard limit: 16.** Any fact with `causation_depth > 16` is rejected by the bus.
- Rationale: Prevents infinite cascade chains (A produces fact → B reacts → C reacts → ...).

### 6.2 Defense 2: Causation Cycle Detection

- Every fact carries `causation_chain` (ordered list of ancestor fact IDs).
- Before accepting a fact, the bus checks for cycles: if the fact's own ID appears in its chain, reject.
- Combined with depth limit, this prevents livelocks.

### 6.3 Defense 3: Deduplication Window

- Key: `(source_claw_id, fact_type, content_hash)`
- Window: 10 seconds (configurable).
- If the same key appears within the window, the duplicate is silently dropped.

### 6.4 Defense 4: Per-Claw Rate Limiting

- Token bucket algorithm per claw.
- Default: capacity 20, refill rate 5/second.
- Exceeding the limit: fact is rejected, claw TEC +1.

### 6.5 Defense 5: Global Bus Load Breaker

- Sliding window: 5 seconds (configurable).
- Threshold: 200 facts per window.
- When exceeded, **emergency mode** engages: only facts with priority ≤ HIGH (1) are accepted.
- Emergency mode disengages when load drops below threshold.

### 6.6 Check Execution Order

All checks run in sequence on every `PUBLISH`. Ordered by computational cost (cheapest first):

```
1. Causation depth check         O(1)
2. Causation cycle detection     O(chain_length)
3. Deduplication window          O(1) amortized
4. Per-claw rate limit           O(1)
5. Global bus load breaker       O(1) amortized
6. Reliability gate              O(1)
7. Schema validation             O(payload_size)
```

---

## 7. Bus Operations

### 7.1 Operation Catalog

| OpCode | Direction | Description |
|--------|-----------|-------------|
| `CONNECT` | claw → bus | Join the bus with a ClawIdentity |
| `DISCONNECT` | claw → bus | Leave the bus gracefully |
| `HEARTBEAT` | claw → bus | Prove liveness, contributes to TEC recovery |
| `PUBLISH` | claw → bus | Emit a fact onto the bus |
| `CLAIM` | claw → bus | Claim an exclusive fact for processing |
| `RELEASE` | claw → bus | Release a claimed fact (can't/won't process) |
| `RESOLVE` | claw → bus | Mark a fact as resolved, optionally emit result facts |
| `QUERY` | claw → bus | Read facts by filter (read-only) |
| `SUBSCRIBE` | claw → bus | Register for push notifications on matching facts |
| `CORROBORATE` | claw → bus | Confirm another claw's fact as valid |
| `CONTRADICT` | claw → bus | Dispute another claw's fact as invalid |

### 7.2 PUBLISH Sequence

```
Claw                                Bus
  │                                  │
  │──── PUBLISH(fact) ──────────────▶│
  │                                  │── compute content_hash
  │                                  │── run PublishGate checks (§6.6)
  │                                  │── run ReliabilityManager gate
  │                                  │── validate schema
  │                                  │── if all pass:
  │                                  │     set state = PUBLISHED
  │                                  │     append to fact log
  │                                  │     run acceptance filters for all claws
  │                                  │     notify matched claws (FACT_AVAILABLE event)
  │◀─── ACK(fact_id) ───────────────│
  │                                  │
```

### 7.3 CLAIM Sequence (Exclusive Facts Only)

```
Claw                                Bus
  │                                  │
  │──── CLAIM(fact_id) ─────────────▶│
  │                                  │── check fact.mode == EXCLUSIVE
  │                                  │── check fact.state == PUBLISHED or MATCHED
  │                                  │── check claw concurrent claims < max
  │                                  │── CAS: set claimed_by = claw_id
  │                                  │      (atomic, first writer wins)
  │                                  │── set state = CLAIMED
  │                                  │── notify other matched claws (FACT_CLAIMED event)
  │◀─── ACK(success=true) ──────────│
  │                                  │
```

### 7.4 RESOLVE Sequence

```
Claw                                Bus
  │                                  │
  │──── RESOLVE(fact_id,             │
  │       result_facts=[...]) ──────▶│
  │                                  │── verify claw == fact.claimed_by
  │                                  │── set state = RESOLVED
  │                                  │── set resolved_at = now
  │                                  │── for each result_fact:
  │                                  │     set causation_chain from parent
  │                                  │     run PUBLISH sequence
  │                                  │── claw.TEC -= 1 (successful resolution)
  │◀─── ACK ────────────────────────│
  │                                  │
```

---

## 8. Fact Lifecycle

Complete state machine:

```
                  publish
  CREATED ──────────────▶ PUBLISHED
                              │
                    filter    │    (no match)
                    match     │──────────────▶ ttl expires ──▶ DEAD
                              ▼
                           MATCHED
                              │
              ┌───────────────┼───────────────┐
              │ exclusive     │               │ broadcast
              ▼               │               ▼
           CLAIMED            │          (all claws
              │               │           process
              ▼               │           directly)
          PROCESSING          │               │
              │               │               │
              ▼               │               ▼
           RESOLVED ◀─────────┘          RESOLVED
              │
              └──▶ may emit child facts (causation chain extends)
```

Dead letter triggers:
- TTL expiration with no claim
- Processing timeout (claim held too long without resolution)
- Explicit failure reported by claiming claw
- All matched claws release without processing

---

## 9. Wire Format

All bus communication uses a uniform envelope (`BusMessage`):

```json
{
  "message_id": "a1b2c3d4e5f6g7h8",
  "op": "publish",
  "claw_id": "abc123def456",
  "timestamp": 1709712000.0,
  "fact": { "...fact fields..." },
  "success": true,
  "error": null
}
```

Serialization: JSON over the transport layer (file, socket, or HTTP — transport-agnostic).

---

## 10. Implementation Phases

| Phase | Scope | Transport |
|-------|-------|-----------|
| **0** (this document) | Protocol specification, core types | N/A |
| **1** | Single-machine bus, file-based fact log | File system (JSONL) |
| **2** | Reliability scoring, flow control, dead letter | File system |
| **3** | Real-time pub/sub, concurrent claws | Unix domain socket |
| **4** | Distributed bus, network transport | TCP / WebSocket |

---

## Appendix A: Comparison with CAN Bus

| Aspect | CAN Bus | Claw Fact Bus |
|--------|---------|---------------|
| Frame / Message unit | CAN Frame (8-64 bytes) | Fact (JSON object) |
| Addressing | Message ID (content-based) | fact_type + tags (content-based) |
| Filtering | Hardware mask + filter registers | AcceptanceFilter (capabilities, domains, patterns) |
| Arbitration | Bitwise on message ID | Score-based on match quality + reliability |
| Error handling | TEC/REC counters, 3-state machine | TEC counter, 3-state machine (active/degraded/isolated) |
| Flow control | Overload frames | Rate limiter + load breaker + depth limit |
| Topology | Single bus, no master | Single bus, no orchestrator |
| Delivery | Broadcast | Broadcast (all) or Exclusive (one) |
| Ordering | By priority (arbitration) | By priority (with aging) |
| Real-time guarantee | Hard real-time (deterministic) | Soft real-time (best-effort with priority) |

## Appendix B: Glossary

| Term | Definition |
|------|-----------|
| **Claw** | An AI agent node connected to the fact bus |
| **Fact** | An immutable statement about reality, the atomic unit on the bus |
| **Bus** | The shared communication medium connecting all claws |
| **Acceptance Filter** | A claw's declaration of what facts it wants to receive |
| **TEC** | Transmit Error Counter, tracks a claw's reliability |
| **Arbitration** | The process of selecting which claw handles an exclusive fact |
| **Causation Chain** | The lineage of ancestor facts that led to the current fact |
| **Dead Letter** | A fact that could not be processed (expired, failed, unclaimed) |
| **Aging** | Automatic priority boost for unclaimed facts to prevent starvation |
| **Monitor Node** | A claw with empty filters that receives all facts (for observability) |
