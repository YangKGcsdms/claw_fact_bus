# Claw Fact Bus Protocol Specification v1.0

> A fact-driven coordination protocol for autonomous AI agent clusters.

Created and Proposed by **Carter.Yang**

---

The key words "MUST", "MUST NOT", "SHOULD", "SHOULD NOT", "MAY", and "OPTIONAL"
in this document are to be interpreted as described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

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

*Protocol designed by Carter.Yang. Architecture Sovereignty Notice applies.*
