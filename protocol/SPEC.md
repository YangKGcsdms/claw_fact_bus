# Claw Fact Bus Protocol Specification v1.0

> A fact-driven coordination protocol for autonomous AI agent clusters.

Created and Proposed by **Carter.Yang**

中文版本: [SPEC.zh-CN.md](SPEC.zh-CN.md)

---

The key words "MUST", "MUST NOT", "SHOULD", "SHOULD NOT", "MAY", and "OPTIONAL"
in this document are to be interpreted as described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

---

## 0. Overview

### 0.1 What This Protocol Is

Claw Fact Bus is a **coordination protocol** for clusters of autonomous AI agents.

Its single sentence: **agents share facts, not commands.**

Each agent publishes immutable statements about what has happened, what exists, or what is needed. Other agents react on their own judgment. No orchestrator decides who does what. Workflow emerges from the causal chain of facts.

### 0.2 Two Implementation Surfaces

The protocol has exactly two implementation surfaces:

```
┌──────────────────────────────────────────────────────┐
│                    Claw Fact Bus                      │
│                                                      │
│  ┌─────────────┐       facts / events       ┌──────┐ │
│  │    Bus       │◀──────────────────────────▶│ Node │ │
│  │ (server)    │                            │(claw)│ │
│  └─────────────┘                            └──────┘ │
│                                                      │
│  Bus: stores facts, enforces protocol invariants,    │
│       dispatches events, arbitrates claims.          │
│                                                      │
│  Node: connects with an identity and filter,         │
│        senses events, publishes / claims / resolves. │
└──────────────────────────────────────────────────────┘
```

**Bus** — the shared communication medium. There is one bus per cluster. It stores facts, enforces all protocol invariants, evaluates filters, arbitrates exclusive claims, and pushes events to connected nodes. The reference implementation is `claw_fact_bus`.

**Node (Claw)** — any agent connected to the bus. There are many nodes per cluster. A node declares its identity and acceptance filter on connect, then participates by publishing, claiming, resolving, and validating facts. Nodes are decoupled from each other; they only interact with the bus. The reference node implementation for OpenClaw agents is `claw_fact_bus_plugin`.

This document specifies what both surfaces MUST and SHOULD do. §11 covers the Bus. §12 covers the Node.

### 0.3 Scope

This specification covers:

- Protocol entities: Fact, Claw, AcceptanceFilter, Bus (§2)
- Matching and arbitration protocol (§3)
- Priority model (§4)
- Fact lifecycle and state machine (§5)
- Bus operations and sequences (§6)
- Safety guardrails (§7)
- Event catalog (§8)
- Wire format (§9)
- Extension catalog (§10)
- **Bus implementation responsibilities** (§11)
- **Node implementation responsibilities** (§12)

Out of scope: distributed bus deployment, cross-bus federation, transport binding (see §1.4).

---

## 1. Philosophical Foundation

### 1.1 Core Axiom

**Facts, not commands.**

The bus carries statements about reality. A claw never tells another claw what to do; it states what has happened, what exists, or what is needed. The responding claw acts on its own judgment.

```
✅  "file auth.py modified, diff: +23 -5, domain: authentication"
✅  "user requested code review for PR #42"
✅  "claw-B claimed fact-0x3A1"
❌  "claw-B, go review auth.py"       ← command, forbidden
```

**Why not commands?** In an AI agent cluster, no single agent has global knowledge or guaranteed reliability. Command-based coordination requires the sender to know the receiver's state, capabilities, and availability — assumptions that break in a dynamic, failure-prone environment. Fact-based coordination decouples the "what happened" from the "who should respond", allowing the system to self-organize as agents join, leave, or fail.

### 1.2 The AI Matrix Thesis

Human organizations align through OKR hierarchies because human communication is lossy, slow, and bandwidth-limited. AI agents can process raw facts directly and maintain causal chains without fidelity loss.

Therefore: **in an AI matrix organization, facts serve as both the coordination medium and the organizational structure.** Causal chains of facts are the AI equivalent of the human org chart — they are not designed top-down but emerge from agents reacting to reality.

### 1.3 Axioms

These are non-negotiable properties that define the system's identity. Removing any one of them produces a fundamentally different system.

1. **Facts, not commands** — The bus carries statements about reality, never directives.
2. **Facts are immutable** — A published fact's content cannot be modified. Only the bus's assessment of it evolves. New facts may supersede older facts.
3. **Broadcast medium, local filtering** — All facts exist in a shared global fact space and are globally addressable. The bus delivers facts to claws whose declared filters match. Each claw declares what it cares about. There is no central orchestrator.
4. **Facts are contestable** — Any claw may corroborate or contradict any other claw's fact. The bus records these actions but does not adjudicate truth. Consumers decide what to trust.
5. **Causal chains are the organizational structure** — Facts reference their parents, forming emergent workflows without pre-designed orchestration.
6. **Fail-safe degradation** — Misbehaving claws are progressively isolated. No single claw failure can crash the bus.

### 1.4 Non-Goals

The following are explicitly outside the scope of this protocol:

- **Consensus** — The bus does not determine truth. It provides evidence (corroborations, contradictions, confidence) for consumers to judge.
- **Distributed bus deployment** — Replication, partitioning, and fault tolerance of the bus itself are implementation concerns.
- **Cross-bus federation** — Communication between separate bus instances is reserved for future extension.
- **Transport binding** — This specification is transport-agnostic. Bindings for HTTP, WebSocket, Unix socket, etc. are separate documents.

### 1.5 Architectural Lineage

| Source | What we take |
|--------|-------------|
| **CAN Bus** (ISO 11898) | Content-addressed messaging, broadcast + local filtering, priority arbitration, error state machine, no central master |
| **EDA** (Event-Driven Architecture) | Event sourcing (immutable append-only log), idempotent consumption, choreography patterns |
| **Scientific method** | Peer review (corroborate/contradict), confidence reporting, knowledge supersession |

### 1.6 Design Rationale

| Decision | Rationale |
|----------|-----------|
| Facts, not commands | AI agents lack global knowledge; decoupling "what happened" from "who responds" enables self-organization |
| Immutable facts | Enables audit, replay, deduplication, and causal reasoning; mutable facts would break all four |
| Broadcast + filter | No orchestrator bottleneck; each agent's filter is its "sensory apparatus" |
| Exclusive / broadcast modes | Fundamental semantic difference: "one handler" vs "shared awareness" — not an optimization |
| Corroborate / contradict in core | AI output is inherently unreliable; without protocol-level contestability, trust can only be handled privately, breaking interoperability |
| Content hash | Tamper detection for the immutable record; SHA-256 for security, not speed |
| JSON wire format | Human-readable, debuggable, universally supported; performance-sensitive deployments MAY use binary encodings |

---

## 2. Protocol Entities

### 2.1 Fact

The atomic unit of communication. Analogous to a CAN frame.

A Fact has two structural zones:

- **Immutable Record** — Set by the publisher, frozen after publish. Covered by `content_hash`.
- **Mutable Bus State** — Managed exclusively by the bus. Changes as the fact moves through its lifecycle.

#### Immutable Record Fields

| Field | Type | Requirement | Description |
|-------|------|:-----------:|-------------|
| `fact_id` | string | MUST | Globally unique identifier |
| `fact_type` | string | MUST | Dot-notation taxonomy (e.g. `code.review.needed`) |
| `payload` | object | MUST | The fact data. Schema determined by `fact_type` |
| `source_claw_id` | string | MUST | Publisher's claw ID |
| `created_at` | float | MUST | Unix timestamp of creation |
| `mode` | enum | MUST | `exclusive` (one handler) or `broadcast` (all matching) |
| `priority` | int 0-7 | MUST | Lower = higher priority (CAN convention). See §4 |
| `ttl_seconds` | int | MUST | Time to live. After expiry → dead |
| `parent_fact_id` | string | OPTIONAL | Direct causal parent. Empty for root facts |
| `causation_depth` | int | MUST | Depth in causal chain. 0 for root facts. Bus MUST enforce a maximum |
| `confidence` | float 0-1 | OPTIONAL | Publisher's self-assessed certainty. Absent = unspecified (not "certain") |
| `content_hash` | string | MUST | SHA-256 of canonical JSON payload |
| `domain_tags` | string[] | OPTIONAL | Content domain tags (e.g. `["python", "auth"]`) |
| `need_capabilities` | string[] | OPTIONAL | Capabilities needed to handle this fact |

#### Mutable Bus State Fields

| Field | Type | Description |
|-------|------|-------------|
| `state` | enum | Protocol lifecycle state (see §5) |
| `claimed_by` | string? | Claw ID that claimed (exclusive mode only) |
| `resolved_at` | float? | Timestamp of resolution |
| `corroborations` | string[] | Claw IDs that have corroborated this fact |
| `contradictions` | string[] | Claw IDs that have contradicted this fact |

Implementations MAY track additional bus-internal state (e.g. `effective_priority`, `matched` flag) but these are not part of the protocol-visible state.

### 2.2 Claw

An agent's presence on the bus. Analogous to a CAN ECU. A Claw may be an AI agent or a human operator — the protocol makes no distinction.

| Field | Type | Requirement | Description |
|-------|------|:-----------:|-------------|
| `claw_id` | string | MUST | Unique identifier |
| `name` | string | MUST | Human-readable name |
| `description` | string | OPTIONAL | What this claw does |
| `acceptance_filter` | Filter | MUST | Declares what facts this claw wants to receive |
| `max_concurrent_claims` | int | SHOULD | Max exclusive facts processable simultaneously |
| `state` | enum | MUST | `active`, `degraded`, `isolated`, `offline` |

Implementations MAY maintain additional per-claw metadata (e.g. reliability scores, error counters) as described in the Fault Confinement Extension.

### 2.3 Acceptance Filter

A claw's declaration of what facts it wants to receive. Content-based, not destination-based.

A bus MUST support content-based filtering over fact attributes. The following filter dimensions are RECOMMENDED:

| Dimension | Type | Description |
|-----------|------|-------------|
| `capability_offer` | string[] | What this claw can do (e.g. `["review", "python"]`) |
| `domain_interests` | string[] | What domains it subscribes to |
| `fact_type_patterns` | string[] | Glob patterns (e.g. `code.*`, `deploy.*.completed`) |
| `priority_range` | (int, int) | Accepted priority range (low, high) |
| `modes` | enum[] | Which fact modes it accepts |

Implementations MAY support additional filter dimensions (e.g. semantic kind, epistemic state, confidence threshold) as described in protocol extensions.

### 2.4 Bus

The shared communication medium. The bus is not a passive pipe — it has obligations:

| Obligation | Requirement |
|------------|:-----------:|
| MUST NOT modify a fact's immutable record fields after publish | MUST |
| MUST deliver facts to all matching claws | MUST |
| MUST enforce `exclusive` semantics (at most one claimer) | MUST |
| MUST record corroborations and contradictions | MUST |
| MUST enforce causation depth limits | MUST |
| MUST reject facts with invalid `content_hash` | MUST |
| MAY rate-limit, deduplicate, and shed load under overload | MAY |
| MAY maintain claw reliability state and isolate faulty claws | MAY |
| MAY support priority aging to prevent starvation | MAY |

---

## 3. Matching Protocol

### 3.1 Filter Evaluation

A fact reaches a claw if and only if ALL of the following pass:

```
Gate 0: claw.state ∈ {active, degraded}               (MUST: not isolated/offline)
Gate 1: fact.priority ∈ claw.filter.priority_range     (MUST: priority mask)
Gate 2: fact.mode ∈ claw.filter.modes                  (MUST: mode compatibility)
Gate 3: AT LEAST ONE content dimension matches          (MUST)
```

Gate 3 content matching SHOULD include at minimum:
- `fact.need_capabilities ∩ claw.capability_offer ≠ ∅`, OR
- `fact.domain_tags ∩ claw.domain_interests ≠ ∅`, OR
- `fact.fact_type` matches any `claw.fact_type_patterns` (glob)

A claw with empty filters (no capabilities, no domains, no patterns) SHOULD receive all facts (monitor mode).

### 3.2 Arbitration

| Mode | Behavior |
|------|----------|
| `broadcast` | All matched claws receive the fact. No arbitration. |
| `exclusive` | The bus selects at most one eligible claw. Selection MUST be deterministic given the same visible inputs. |

The specific scoring or ranking algorithm for exclusive arbitration is an implementation choice. See Implementation Notes for a recommended algorithm.

---

## 4. Priority

### 4.1 Priority Levels

Priority uses a 3-bit field (0-7), following CAN convention (lower value = higher priority):

| Value | Name | Description |
|-------|------|-------------|
| 0 | CRITICAL | System failures, data loss prevention |
| 1 | HIGH | User-facing blocking issues |
| 2 | ELEVATED | Important but not blocking |
| 3 | NORMAL | Default for most facts |
| 4 | LOW | Background tasks |
| 5 | BACKGROUND | Housekeeping, optimization |
| 6 | IDLE | Best-effort work |
| 7 | BULK | Batch processing |

### 4.2 Anti-Starvation

A bus SHOULD implement an aging mechanism to prevent low-priority facts from being permanently starved. Facts MUST NOT age into CRITICAL (priority 0) — that level is reserved for genuine emergencies.

See Implementation Notes for recommended aging parameters.

---

## 5. Fact Lifecycle

### 5.1 Protocol-Visible States

```
              PUBLISH
  ─────────────────────▶ PUBLISHED
                              │
                    ┌─────────┼─────────┐
                    │exclusive│         │broadcast
                    ▼         │         ▼
                 CLAIMED      │     (all matched
                    │         │      claws see it)
                    ▼         │         │
                 RESOLVED ◀───┘    RESOLVED
                    │
                    └──▶ may emit child facts (causal chain extends)

  Any non-terminal state ──▶ DEAD (on TTL expiry or failure)
```

| State | Description |
|-------|-------------|
| `published` | Fact accepted by the bus and visible to matching claws |
| `claimed` | One claw has taken exclusive responsibility (exclusive mode only) |
| `resolved` | Processing complete. May have produced child facts |
| `dead` | Fact could not be processed (TTL expired, all claws released, explicit failure) |

Implementations MAY track additional internal states (e.g. `matched`, `processing`) but these MUST NOT appear in protocol-level responses or events.

### 5.2 State Transitions

| From | To | Trigger |
|------|----|---------|
| — | `published` | PUBLISH accepted by bus |
| `published` | `claimed` | CLAIM by a claw (exclusive mode only) |
| `published` | `resolved` | Direct resolution (broadcast mode) |
| `published` | `dead` | TTL expiry, no match |
| `claimed` | `resolved` | RESOLVE by claiming claw |
| `claimed` | `published` | RELEASE by claiming claw (returns to pool) |
| `claimed` | `dead` | Claim timeout, claw failure |
| `dead` | `published` | Administrative redispatch (OPTIONAL) |

---

## 6. Bus Operations

### 6.1 Operation Catalog

| OpCode | Direction | Description |
|--------|-----------|-------------|
| `CONNECT` | claw → bus | Join the bus with a Claw identity |
| `DISCONNECT` | claw → bus | Leave the bus gracefully |
| `HEARTBEAT` | claw → bus | Prove liveness |
| `PUBLISH` | claw → bus | Emit a fact onto the bus |
| `CLAIM` | claw → bus | Claim an exclusive fact for processing |
| `RELEASE` | claw → bus | Release a claimed fact back to the pool |
| `RESOLVE` | claw → bus | Complete processing, optionally emit child facts |
| `QUERY` | claw → bus | Read facts by filter (read-only) |
| `SUBSCRIBE` | claw → bus | Register for real-time push of matching facts |
| `CORROBORATE` | claw → bus | Confirm another claw's fact. Bus MUST append claw_id to `corroborations` |
| `CONTRADICT` | claw → bus | Dispute another claw's fact. Bus MUST append claw_id to `contradictions` |

### 6.2 PUBLISH Sequence

```
Claw                                Bus
  │                                  │
  │──── PUBLISH(fact) ──────────────▶│
  │                                  │── verify content_hash
  │                                  │── run admission checks
  │                                  │── if all pass:
  │                                  │     set state = PUBLISHED
  │                                  │     persist fact
  │                                  │     evaluate filters for all claws
  │                                  │     push FACT_AVAILABLE to matched claws
  │◀─── ACK(fact_id) ───────────────│
  │                                  │
```

Admission checks MUST include content hash verification and causation depth enforcement. Implementations MAY add rate limiting, deduplication, schema validation, and reliability gates.

### 6.3 CLAIM Sequence

```
Claw                                Bus
  │                                  │
  │──── CLAIM(fact_id) ─────────────▶│
  │                                  │── verify fact.mode == EXCLUSIVE
  │                                  │── verify fact.state == PUBLISHED
  │                                  │── verify claw concurrent claims < max
  │                                  │── atomic: set claimed_by = claw_id
  │                                  │           set state = CLAIMED
  │                                  │── push FACT_CLAIMED to other matched claws
  │◀─── ACK(success) ───────────────│
  │                                  │
```

CLAIM is atomic. When multiple claws attempt to claim the same fact, the bus MUST select at most one using deterministic criteria consistent with §3.2. Without an arbitration extension, the default selection order is first-arrival. With an arbitration extension (e.g. Advanced Arbitration), the bus SHOULD use the extension's scoring algorithm instead. If another claw has been selected, the bus MUST return failure to other claimants. A claw whose claim was rejected SHOULD NOT retry the same fact.

### 6.4 RESOLVE Sequence

```
Claw                                Bus
  │                                  │
  │──── RESOLVE(fact_id,             │
  │       result_facts=[...]) ──────▶│
  │                                  │── verify claw == fact.claimed_by
  │                                  │── set state = RESOLVED
  │                                  │── set resolved_at = now
  │                                  │── for each child fact:
  │                                  │     set parent_fact_id = fact_id
  │                                  │     set causation_depth = parent + 1
  │                                  │     run PUBLISH sequence
  │◀─── ACK ────────────────────────│
  │                                  │
```

### 6.5 CORROBORATE / CONTRADICT

A claw MUST NOT corroborate or contradict its own facts. The bus MUST reject such attempts.

The bus MUST record these actions (append claw_id to the respective list) but MUST NOT autonomously change a fact's lifecycle state based on corroboration/contradiction counts. Trust derivation is a consumer-side or extension-level concern.

---

## 7. Safety Guardrails

The bus MUST enforce certain safety invariants to prevent cascade failures and resource exhaustion.

### 7.1 Mandatory Guardrails

| Guardrail | Requirement |
|-----------|:-----------:|
| **Content integrity** — reject facts where `content_hash` does not match payload | MUST |
| **Causation depth limit** — reject facts exceeding a configured maximum depth | MUST |
| **Immutability** — never modify a fact's immutable record fields after publish | MUST |
| **Claim exclusivity** — at most one claw may claim an exclusive fact | MUST |
| **TTL enforcement** — expire facts that exceed their time to live | MUST |
| **Cross-domain propagation by derivation** — a fact's immutable fields (including `fact_type`) MUST NOT be modified to change its domain; cross-domain propagation MUST use a new derived fact with `parent_fact_id` linkage | MUST |

### 7.2 Recommended Guardrails

| Guardrail | Requirement |
|-----------|:-----------:|
| **Causation cycle detection** — reject facts whose parent chain contains a cycle | SHOULD |
| **Deduplication** — suppress duplicate publishes within a time window | SHOULD |
| **Per-claw rate limiting** — prevent a single claw from flooding the bus | SHOULD |
| **Global load shedding** — protect the bus under extreme load | MAY |
| **Claw reliability tracking** — isolate persistently faulty claws | MAY |
| **Priority aging** — boost priority of unclaimed facts to prevent starvation | MAY |
| **Schema validation** — validate payloads against registered schemas | MAY |
| **Fact archival** — compact or archive facts in terminal states (resolved, dead) beyond a configurable retention window to bound storage growth | MAY |

Specific parameters for all recommended guardrails are defined in Implementation Notes.

---

## 8. Events

The bus pushes the following events to subscribed claws:

| Event | Trigger | Payload |
|-------|---------|---------|
| `fact_available` | A new fact matches the claw's filter | The fact |
| `fact_claimed` | Someone claimed an exclusive fact | fact_id, claimer claw_id |
| `fact_resolved` | A fact was resolved | fact_id |
| `fact_dead` | A fact entered dead state | fact_id, reason |

Extensions MAY define additional events (e.g. `fact_trust_changed`, `fact_superseded`, `claw_state_changed`).

---

## 9. Wire Format

All bus communication uses a uniform JSON envelope:

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

Serialization: JSON. Implementations MAY support additional encodings (MessagePack, Protobuf) as transport-level optimizations, but MUST support JSON as the baseline.

---

## 10. Extensions

This core specification is designed to be extended. Extensions are independently versioned and OPTIONAL.

| Extension | Scope |
|-----------|-------|
| **Epistemic States** | Trust lifecycle (asserted → corroborated → consensus → contested → refuted), quorum rules, trust derivation |
| **Semantic Classification** | `semantic_kind` field (observation, assertion, request, resolution, correction, signal) |
| **Knowledge Evolution** | `subject_key` field, automatic and explicit supersession, `SUPERSEDED` state |
| **Schema Governance** | Schema registry, payload validation, schema versioning and evolution |
| **Fault Confinement** | TEC/REC error counters, threshold-based degradation, recovery protocol |
| **Advanced Arbitration** | Scoring formulas, reliability-weighted selection |
| **Storm Protection** | Specific parameters for rate limiting, deduplication, load shedding |

See [EXTENSIONS.md](EXTENSIONS.md) for full definitions.
See [IMPLEMENTATION-NOTES.md](IMPLEMENTATION-NOTES.md) for recommended default values.

---

## 11. Bus Implementation Responsibilities

This section specifies what a conforming **Bus** implementation MUST, SHOULD, and MAY do. The reference implementation is `claw_fact_bus` (Python / FastAPI).

### 11.1 Core Engine

| Responsibility | Requirement |
|----------------|:-----------:|
| Maintain an in-memory fact store indexed by `fact_id` | MUST |
| Enforce the WorkflowStateMachine transition table (§5) | MUST |
| Compute and verify `content_hash` on every PUBLISH | MUST |
| Sign accepted facts with a bus-authority HMAC stamp | SHOULD |
| Assign a monotonic `sequence_number` to each accepted fact | SHOULD |
| Persist every state-changing event to an append-only log | SHOULD |
| Recover in-memory state from the persisted log on startup | SHOULD |
| Compact the log periodically to bound disk growth | MAY |

### 11.2 Claw Registry

| Responsibility | Requirement |
|----------------|:-----------:|
| Accept CONNECT requests and assign a unique `claw_id` | MUST |
| Issue and verify per-claw auth tokens | MUST |
| Register each claw's `AcceptanceFilter` | MUST |
| Accept DISCONNECT requests and remove claw from registry | MUST |
| Accept HEARTBEAT requests and track liveness | MUST |
| Replay recent unresolved facts to a claw on reconnect | SHOULD |

### 11.3 Publish Admission Pipeline

The bus MUST run all mandatory checks on every PUBLISH, in this order (cheapest first):

```
1. Causation depth check      (MUST)   O(1)
2. Causation cycle detection  (SHOULD) O(depth)
3. Deduplication window       (SHOULD) O(1) amortized
4. Per-claw rate limit        (SHOULD) O(1)
5. Global load breaker        (MAY)    O(1) amortized
6. Reliability gate           (MAY)    O(1)
7. Schema validation          (MAY)    O(payload)
```

A fact that fails any check MUST be rejected with an error; the `content_hash` MUST NOT be accepted.

### 11.4 Dispatch and Arbitration

| Responsibility | Requirement |
|----------------|:-----------:|
| Evaluate `AcceptanceFilter` for every connected claw on each PUBLISH | MUST |
| Deliver `fact_available` to all matched claws (`broadcast` mode) | MUST |
| For `exclusive` mode: select at most one claw using deterministic arbitration | MUST |
| Arbitration MUST be deterministic given the same visible inputs | MUST |
| Push `fact_claimed` to other matched claws when a claim is accepted | MUST |
| Push `fact_resolved` to matched claws when a fact is resolved | MUST |
| Push `fact_dead` to matched claws when a fact expires or fails | MUST |

### 11.5 Exclusive Claim Invariant

CLAIM is atomic. The bus MUST guarantee:

- At most one claw holds a claim on any exclusive fact at any time.
- If two claws attempt CLAIM simultaneously, exactly one succeeds.
- The rejected claimant receives a failure response.
- The bus MUST NOT accept a RESOLVE from any claw other than the current claimer.

### 11.6 Lifecycle Enforcement

| Responsibility | Requirement |
|----------------|:-----------:|
| Run a TTL expiration loop; mark expired facts as `dead` | MUST |
| Enforce causation depth limit on every PUBLISH | MUST |
| NEVER modify a fact's immutable record fields after publish | MUST |
| Run a GC pass to evict terminal facts beyond retention window | SHOULD |

### 11.7 Trust and Reliability (Extension-Level)

These responsibilities are active when the corresponding extensions are enabled:

| Responsibility | Extension | Requirement |
|----------------|-----------|:-----------:|
| Recompute `epistemic_state` after every corroborate/contradict | Epistemic States | MUST (if enabled) |
| Push `fact_trust_changed` when epistemic state changes | Epistemic States | MUST (if enabled) |
| Handle `subject_key` auto-supersession on publish | Knowledge Evolution | MUST (if enabled) |
| Push `fact_superseded` when a fact is superseded | Knowledge Evolution | MUST (if enabled) |
| Increment/decrement TEC on error/success events | Fault Confinement | MUST (if enabled) |
| Transition claw to `degraded` / `isolated` at TEC thresholds | Fault Confinement | MUST (if enabled) |
| Lower published fact confidence when source claw is `degraded` | Fault Confinement | MUST (if enabled) |
| Validate payload against registered schema on publish | Schema Governance | MUST (if enabled) |
| Use scoring formula for exclusive arbitration | Advanced Arbitration | MUST (if enabled) |
| Apply priority aging to unclaimed facts | Storm Protection | SHOULD (if enabled) |

---

## 12. Node Implementation Responsibilities

This section specifies what a conforming **Node** (Claw) implementation MUST, SHOULD, and MAY do. The reference implementation is `claw_fact_bus_plugin` (TypeScript / OpenClaw plugin).

A node is any process — AI agent, human-operated gateway, monitoring tool, or automated script — that connects to the bus and participates in fact coordination.

### 12.1 Connection Lifecycle

| Responsibility | Requirement |
|----------------|:-----------:|
| CONNECT to the bus with a name, description, and `AcceptanceFilter` | MUST |
| Retain `claw_id` and auth token returned by the bus | MUST |
| Send HEARTBEAT at regular intervals to maintain liveness | MUST |
| Retry CONNECT with backoff if the bus is not yet reachable | SHOULD |
| Send DISCONNECT on graceful shutdown | SHOULD |
| Declare a meaningful `AcceptanceFilter` (capability, domain, or type patterns) rather than using empty monitor mode in production | SHOULD |

### 12.2 Event Subscription and Sensing

| Responsibility | Requirement |
|----------------|:-----------:|
| Open a real-time event channel (WebSocket or equivalent) after connecting | MUST |
| Receive `fact_available`, `fact_claimed`, `fact_resolved`, `fact_dead` events | MUST |
| Receive `fact_trust_changed`, `fact_superseded` events (if extensions enabled) | SHOULD |
| Reconnect the event channel automatically with exponential backoff | SHOULD |
| Restart the event channel when `claw_id` changes (e.g. after bus restart) | MUST |
| Buffer incoming events in a bounded queue for agent consumption | SHOULD |
| Warn when the event queue overflows (events are being dropped) | SHOULD |
| Expose a `sense` operation that drains buffered events and returns action hints | SHOULD |

**Event queue overflow handling**: When the queue is full, the node SHOULD drop the oldest events (FIFO eviction) and report the drop count in the next `sense` response so the agent can compensate via QUERY.

### 12.3 Publishing Facts

| Responsibility | Requirement |
|----------------|:-----------:|
| Set `fact_type` in dot-notation (`<domain>.<entity>.<event>`) | MUST |
| Set `source_claw_id` to own `claw_id` | MUST |
| Set `mode` to `exclusive` or `broadcast` based on intended semantics | MUST |
| Set `content_hash` correctly (SHA-256 of canonical payload) | MUST |
| Set `causation_chain` and `causation_depth` when publishing a child fact | MUST |
| Set `semantic_kind` to classify the fact (`observation`, `request`, `resolution`, etc.) | SHOULD |
| Set `confidence` when certainty is less than 1.0 | SHOULD |
| Set `ttl_seconds` appropriate to the urgency of the fact | SHOULD |
| NEVER publish command-shaped facts (e.g. `claw-B.do.review`) | MUST NOT |

### 12.4 Claiming and Resolving

| Responsibility | Requirement |
|----------------|:-----------:|
| Only attempt CLAIM on `exclusive`-mode facts | MUST |
| After a successful CLAIM, either RESOLVE or RELEASE the fact | MUST |
| Derive child facts via RESOLVE `result_facts` so causation chain is extended by the bus | SHOULD |
| RELEASE if unable to complete the work | MUST |
| Not retry the same fact after a failed CLAIM | MUST NOT |
| Not hold a claim indefinitely without making progress | MUST NOT |

### 12.5 Social Validation

| Responsibility | Requirement |
|----------------|:-----------:|
| CORROBORATE a fact only when independently verified | SHOULD |
| CONTRADICT a fact when evidence conflicts with its content | SHOULD |
| NEVER corroborate or contradict own facts | MUST NOT |
| Filter incoming facts by `min_epistemic_rank` before acting on them | SHOULD |

### 12.6 Reference Node Implementation: claw_fact_bus_plugin

`claw_fact_bus_plugin` is the reference OpenClaw node implementation. It maps the protocol to agent-callable tools:

| Protocol Operation | Tool |
|--------------------|------|
| Drain buffered events | `fact_bus_sense` |
| PUBLISH | `fact_bus_publish` |
| QUERY | `fact_bus_query` |
| CLAIM | `fact_bus_claim` |
| RELEASE | `fact_bus_release` |
| RESOLVE | `fact_bus_resolve` |
| CORROBORATE / CONTRADICT | `fact_bus_validate` |
| Fetch payload schema | `fact_bus_get_schema` |

**`fact_bus_sense`** is the primary event interface. It drains buffered WebSocket events and returns structured action hints per fact (`claim it`, `observe and react`, `re-evaluate trust`, etc.), guiding the agent's next decision without requiring it to understand raw protocol events.

The plugin handles connection lifecycle (CONNECT, HEARTBEAT, DISCONNECT with server notification), WebSocket management (reconnect with backoff, restart when `claw_id` changes), and event queue management (bounded buffer, overflow warning, `events_dropped` counter in `sense` response).

---

## Appendix A: Comparison with CAN Bus

| Aspect | CAN Bus | Claw Fact Bus |
|--------|---------|---------------|
| Frame / Message unit | CAN Frame (8-64 bytes) | Fact (JSON object) |
| Addressing | Message ID (content-based) | fact_type + tags (content-based) |
| Filtering | Hardware mask + filter registers | AcceptanceFilter (content-based) |
| Arbitration | Bitwise on message ID | Implementation-defined scoring |
| Error handling | TEC/REC counters, 3-state machine | 3-state machine (active/degraded/isolated), details in extension |
| Flow control | Overload frames | Rate limiter + load shedding (implementation-defined) |
| Topology | Single bus, no master | Single bus, no orchestrator |
| Delivery | Broadcast | Broadcast (all) or Exclusive (one) |
| Trust model | N/A (physical sensors) | Corroborate / contradict (AI agents are unreliable) |

## Appendix B: Glossary

| Term | Definition |
|------|-----------|
| **Claw** | An autonomous agent (AI or human) connected to the fact bus |
| **Fact** | An immutable statement about reality, the atomic coordination unit |
| **Bus** | The shared communication medium connecting all claws |
| **Acceptance Filter** | A claw's declaration of what facts it wants to receive |
| **Causation Depth** | How many ancestor facts led to this one |
| **Parent Fact** | The direct causal predecessor of a fact |
| **Corroboration** | Another claw confirming a fact's validity |
| **Contradiction** | Another claw disputing a fact's validity |
| **Dead** | A fact that could not be processed (expired, failed, unclaimed) |
| **Exclusive** | Delivery mode where at most one claw handles the fact |
| **Broadcast** | Delivery mode where all matching claws see the fact |

---

## Appendix C: Agent Decision Guide

> **Normative supplement to §12.** This appendix translates the node responsibilities in §12 into concrete decision logic an autonomous agent (**Claw**) should follow at runtime. It uses the same MUST/SHOULD language as the rest of the specification. For OpenClaw integration, use the **`claw_fact_bus_plugin`** (tools such as `fact_bus_sense`, `fact_bus_publish`, `fact_bus_claim`, `fact_bus_resolve`, `fact_bus_validate`, etc.) which implements all §12 responsibilities and exposes them as agent-callable tools.

### C.1 Core Axiom

**Facts, not commands.** A claw never tells another claw what to do. It states what happened, what exists, or what is needed. Other claws decide for themselves whether and how to respond.

```
CORRECT:  publish fact_type "code.review.needed" with payload { file, pr }
WRONG:    publish fact_type "claw-B.do.review"  ← command disguised as fact
```

### C.2 Architecture Mental Model

No central orchestrator. No command chain. Workflow **emerges** from fact causation chains.

- Facts are broadcast or routed to claws whose **AcceptanceFilter** matches.
- A claw **senses** matching facts (typically via WebSocket push), **claims** exclusive work, **processes**, and **resolves**—possibly emitting **child facts** that extend the causation chain.
- Other claws downstream react to those new facts independently.

### C.3 Connecting and Sensing

After **`POST /claws/connect`**, retain `claw_id` and `token` for authenticated operations. Open a **WebSocket** subscription (see server documentation) to receive events such as `fact_available`, `fact_claimed`, `fact_resolved`, `fact_superseded`, `fact_trust_changed`.

The bus only delivers facts that pass the claw’s **AcceptanceFilter**. Matching uses capability offer, domain interests, fact type patterns, priority range, mode, semantic kind, epistemic rank, confidence, and supersession rules as implemented by the server (see **EXTENSIONS.md**).

**Typical event responses**

| Event | Meaning | Typical response |
|-------|---------|------------------|
| `fact_available` | New fact matches filter | Decide whether to claim (if exclusive) or react (if broadcast) |
| `fact_claimed` | Another claw owns the fact | Do not claim the same exclusive fact |
| `fact_trust_changed` | Epistemic state changed | Re-evaluate reliance; consider corroborate/contradict |
| `fact_dead` | Expired or terminated | Stop tracking |
| `fact_superseded` | Replaced by newer knowledge | Prefer the latest fact for the same subject |

### C.4 Understanding a Fact

**Immutable record** (content fixed after publish): `fact_type`, `semantic_kind`, `payload`, `domain_tags`, `need_capabilities`, `priority`, `mode`, `source_claw_id`, `causation_chain` / `causation_depth` (and `parent_fact_id` as the last chain entry), `confidence`, `subject_key`, `supersedes` (where applicable).

**Mutable bus state**: `state`, `epistemic_state`, `claimed_by`, `corroborations`, `contradictions`.

**Semantic kinds**

| Kind | Meaning | Example `fact_type` |
|------|---------|---------------------|
| `observation` | Raw data | `build.failed`, `cpu.usage.high` |
| `assertion` | Inference | `root_cause.suspected` |
| `request` | Work needed | `code.review.needed` |
| `resolution` | Outcome of processing | `code.review.completed` |
| `correction` | Supersedes prior knowledge | Updated diagnosis |
| `signal` | Status / heartbeat | `progress.60pct` |

**Decision framework (incoming fact)**

```
Receive fact_available (or equivalent)
  │
  ├─ mode == broadcast?
  │    └─ YES → Read and react (publish new facts); do NOT claim
  │
  ├─ mode == exclusive?
  │    ├─ Can I handle? (need_capabilities vs my capabilities)
  │    │    └─ NO → Ignore
  │    ├─ Is epistemic state acceptable for my policy?
  │    │    └─ If not → Ignore or contradict / publish counter-evidence
  │    └─ Attempt claim
  │
  └─ Claim succeeded?
       ├─ YES → Process → Resolve (optional child / result facts)
       └─ NO → Another claw owns it; move on
```

### C.5 Publishing, Claiming, Resolving, Releasing

- **Publish**: `POST /facts` with `source_claw_id`, `token`, payload fields per schema.
- **Claim**: `POST /facts/{id}/claim` for **exclusive** facts you will process.
- **Resolve**: `POST /facts/{id}/resolve` to close the workflow; optional **result_facts** become child facts with extended causation chain.
- **Release**: `POST /facts/{id}/release` if you cannot complete work after claiming.

**Mode**: `exclusive` = one handler; `broadcast` = all matching claws may observe and publish follow-ups without claiming.

**Priority** (0–7, lower = more urgent): use CRITICAL for outages, HIGH for degraded service, NORMAL for routine work (see **IMPLEMENTATION-NOTES** for defaults).

**Fact type naming** (convention): `<domain>.<entity>.<event>` (e.g. `code.review.needed`, `deploy.production.failed`).

### C.6 Social Validation

- **Corroborate**: `POST /facts/{id}/corroborate` when you independently confirm a fact.
- **Contradict**: `POST /facts/{id}/contradict` when your evidence conflicts.

Use filters (e.g. minimum epistemic rank, minimum confidence, exclude superseded) to ignore untrusted facts for your use case.

### C.7 Knowledge Evolution (Supersede)

Publish a new fact with the same **`subject_key`** (and compatible `fact_type` per implementation) to replace outdated readings. Superseded facts move to `epistemic_state: superseded` and should be ignored when `exclude_superseded` is true in the filter.

### C.8 Failure and Recovery

| Situation | Guidance |
|-----------|----------|
| Publish rejected (hash, depth, rate limit, schema, isolation) | Fix payload, backoff, or recover claw health per server messages |
| Claim fails | Normal under contention; do not retry the same fact indefinitely |
| Claw degraded / isolated | Often tied to reliability / TEC; heartbeats and clean behavior restore trust |
| Your fact is contradicted | Peer review; publish corrections or corroborate better evidence |

### C.9 Observability

Use **`GET /stats`**, **`GET /claws`**, **`GET /facts`** (query), and **`GET /claws/{claw_id}/activity`** as exposed by the server for debugging and dashboards.

### C.10 Anti-Patterns

| Don’t | Do instead |
|-------|------------|
| Publish command-shaped fact types | Publish needs and observations |
| Claim broadcast facts | Observe and publish derived facts |
| Ignore `epistemic_state` | Filter or re-evaluate contested/refuted facts |
| Hold claims without progress | Resolve or release promptly |
| Hardcode peer claw IDs | Use capabilities, domains, and fact types for routing |

---

*Protocol designed by Carter.Yang. Architecture Sovereignty Notice applies.*
