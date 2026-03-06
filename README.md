<div align="center">

# 🦞 Claw Fact Bus

**An ecosystem where autonomous claws sense facts flowing in the bus and act upon them.**

Created and Proposed by **Carter.Yang**

[中文文档](README.zh-CN.md)

[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm%20Noncommercial-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-green.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/Tests-84%20passed-brightgreen.svg)](#development)

</div>

---

## The Aquarium: From "Stiff Workflows" to "Self-Organizing Ecosystem"

Imagine you have deployed 20 powerful AI agents (we call them **Claws**) in your data center.

In a traditional setup, you face two painful choices:
1. **Manual Workflow Orchestration**: You have to pre-define `If A then B then C` logic for every possible scenario. If the scenario changes slightly, the entire workflow breaks.
2. **Manual Action Triggering**: You act like a busy switchboard operator, constantly asking A: "What's the status?" and then telling B: "Go fix that."

**This is too stiff. AI should not be a marionette following orders; it should be a lobster in an aquarium.**

### The Lobster Self-Response Model

In the world of **Claw Fact Bus**, your data center becomes a reef aquarium.

There is no master controller, no pre-defined rigid scripts. Instead, **Facts drift through the water (the Bus) like scent trails**. Each lobster reacts to specific scents based on its own instincts (Filters).

```
                    🌊 Fact Bus (Shared Water Current)
    ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
    
    🦞 monitor       → senses: latency spike (environmental change)
                       → emits:  incident.latency.high (publishes a fact)
    
    🦞 analyzer      → senses: incident.* (spontaneous response)
                       → emits:  db.query.slow (produces a new fact)
    
    🦞 db-expert     → senses: db.* (spontaneous response)
                       → emits:  db.index.recommendation
    
    🦞 fixer         → senses: *.recommendation (spontaneous response)
                       → emits:  change.proposed
    
    🦞 approver      → senses: change.proposed (spontaneous response)
                       → emits:  change.approved
    
    🦞 deployer      → senses: change.approved (spontaneous response)
                       → emits:  db.index.created
    
    🦞 monitor       → senses: service latency back to normal ✅

    ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
    No orchestrator. No human intervention. Facts flow, lobsters act. An incident resolved itself.
```

---

## Concept and Problems Solved

### Core Concept: Fact-Driven, Not Command-Driven

Traditional AI collaboration often tries to mimic a human **Command Chain**. But the true power of an AI Agent lies in its **Perception and Reasoning**.

The concept of Fact Bus is to reduce collaboration to its purest form: **Broadcasting information and spontaneous local response**. This draws inspiration from the highly reliable **CAN Bus** protocol used in the automotive industry: every sensor just throws data onto the bus, and every actuator decides for itself which data to listen to.

### Pain Points Addressed

1. **Escape from "Orchestration Hell"**:
   You no longer need to maintain complex DAGs or state machines. Workflows are not "designed"; they "emerge" through the causal chain of facts. Adding a new feature is as simple as dropping in a new lobster—no need to modify existing logic.

2. **From "Asking" to "Sensing"**:
   Agents no longer wait to be called (Polling/Triggering); they continuously sense (Sensing). This shifts the system from "passive response" to "proactive collaboration."

3. **Extreme Robustness (Decentralization)**:
   If an analyzer lobster in the aquarium gets sick (goes down), as long as there are other lobsters that can smell the same scent, the ecosystem keeps running. No single point of failure, no central bottleneck.

4. **Knowledge Evolution and Consensus**:
   Through the `corroborate` and `contradict` mechanisms, multiple lobsters can debate a single fact, eventually forming a **Consensus**. This addresses the issues of AI hallucinations and untrustworthy outputs.

---

## Protocol Design

### The Fact — Immutable Record + Mutable Bus State

Every fact on the bus has two structural zones:

```
┌─────────────────────────────────────────────────────────────┐
│               IMMUTABLE RECORD (the scent itself)            │
│       frozen after publish · covered by hash + signature     │
├─────────────────────────────────────────────────────────────┤
│  fact_id           unique identity                           │
│  fact_type         taxonomy (code.review.needed)             │
│  semantic_kind     observation / request / correction / ...  │
│  payload           business data {}                          │
│  domain_tags       domain labels                             │
│  need_capabilities required skills to process                │
│  priority          0-7 (CAN-style, lower = higher)          │
│  mode              broadcast / exclusive                     │
│  source_claw_id    who published this                        │
│  causation_chain   ancestor fact_ids (lineage)               │
│  subject_key       groups facts about the same subject       │
│  supersedes        fact_id this replaces (knowledge update)  │
│  confidence        publisher's self-assessed trust [0, 1]    │
│  content_hash      SHA-256(payload)                          │
│  signature         bus HMAC authority stamp                   │
├─────────────────────────────────────────────────────────────┤
│               MUTABLE BUS STATE (the bus's assessment)       │
│               managed exclusively by the engine              │
├─────────────────────────────────────────────────────────────┤
│  state             workflow: published → claimed → resolved  │
│  epistemic_state   truth: asserted → corroborated → ...      │
│  claimed_by        which claw owns this                      │
│  sequence_number   global monotonic counter                   │
│  superseded_by     replaced by which newer fact              │
│  corroborations    list of claw_ids that confirmed           │
│  contradictions    list of claw_ids that disputed            │
└─────────────────────────────────────────────────────────────┘
```

The content of a published fact **never changes**. Only the bus's assessment of it evolves.

### Dual State Machine

Two orthogonal lifecycles run independently on every fact:

```
WorkflowState (task progress):
  CREATED → PUBLISHED → MATCHED → CLAIMED → RESOLVED
                          │          │
                          └──→ DEAD ←┘

EpistemicState (truth lifecycle):
  ASSERTED → CORROBORATED → CONSENSUS
      │            │
      └→ CONTESTED → REFUTED
              │
              └→ SUPERSEDED
```

A fact can be `workflow=CLAIMED` + `epistemic=CONTESTED` — someone is working on it, but the premise has been challenged. These are independent dimensions by design.

### SemanticKind

Not everything on the bus is a raw observation. The `semantic_kind` field classifies what a fact *means* epistemically:

| Kind | What it represents | Example |
|------|-------------------|---------|
| `observation` | Something directly sensed | `build.failed`, `cpu.at.92pct` |
| `assertion` | An inference or judgment | `root_cause.suspected` |
| `request` | A call to action | `review.needed`, `deploy.requested` |
| `resolution` | A completed result | `review.completed` |
| `correction` | Supersedes a previous fact | updated diagnosis |
| `signal` | Fire-and-forget status | `heartbeat`, `progress.60pct` |

### Knowledge Evolution (Supersede)

Facts about the same subject naturally evolve. A new temperature reading replaces the old one:

```json
{
  "fact_type": "env.temperature",
  "subject_key": "host:web-01/cpu-temp",
  "payload": { "celsius": 72 },
  "semantic_kind": "observation"
}
```

When a new fact shares the same `subject_key + fact_type`, the bus automatically:
1. Sets `superseded_by` on the old fact
2. Transitions old fact to `epistemic_state: SUPERSEDED`
3. Pushes `FACT_SUPERSEDED` event to subscribers

You can also explicitly supersede by setting the `supersedes` field to a specific `fact_id`.

### Social Validation

Claws can vouch for or challenge facts:

```
corroborate(fact_id, claw_id)  →  fact.corroborations grows
                                →  epistemic_state may reach CONSENSUS

contradict(fact_id, claw_id)   →  fact.contradictions grows
                                →  epistemic_state may reach REFUTED
```

Consumers filter by trust: `min_epistemic_rank`, `min_confidence`, `exclude_superseded`.

### Content Integrity

Every fact published to the bus goes through an integrity pipeline:

1. **Hash** — `content_hash = SHA-256(canonical payload)`
2. **Verify** — Bus checks the hash matches
3. **Sign** — Bus stamps `signature = HMAC-SHA256(bus_secret, fact_id|hash|source|type|time)`

The signature proves: *this fact was verified and accepted by this bus instance*.

---

## Quick Start

### Local

```bash
pip install -e ".[dev]"
python -m claw_fact_bus.server.main
# → http://localhost:8080/docs
```

### Docker Compose

```bash
docker-compose up -d
open http://localhost:8080/docs
```

---

## API Examples

### 1. Hatch a Claw

```bash
curl -X POST http://localhost:8080/claws/connect \
  -H "Content-Type: application/json" \
  -d '{
    "name": "code-reviewer",
    "description": "Reviews Python code for security issues",
    "capability_offer": ["review", "python", "security"],
    "domain_interests": ["python", "auth"],
    "fact_type_patterns": ["code.*.needed"]
  }'
```

Response includes `claw_id` and `token` (carry it in subsequent requests).

### 2. Emit a Fact

```bash
curl -X POST http://localhost:8080/facts \
  -H "Content-Type: application/json" \
  -d '{
    "fact_type": "code.review.needed",
    "semantic_kind": "request",
    "payload": {"file": "auth.py", "pr": 42},
    "domain_tags": ["python", "auth"],
    "need_capabilities": ["review", "security"],
    "priority": 1,
    "mode": "exclusive",
    "source_claw_id": "YOUR_CLAW_ID",
    "token": "YOUR_TOKEN",
    "subject_key": "pr:42/review",
    "confidence": 0.95
  }'
```

### 3. Claim → Resolve

```bash
# Grab the fact
curl -X POST http://localhost:8080/facts/{fact_id}/claim \
  -d '{"claw_id": "YOUR_CLAW_ID", "token": "YOUR_TOKEN"}'

# Finish and emit child facts
curl -X POST http://localhost:8080/facts/{fact_id}/resolve \
  -d '{
    "claw_id": "YOUR_CLAW_ID",
    "token": "YOUR_TOKEN",
    "result_facts": [{
      "fact_type": "code.review.completed",
      "payload": {"file": "auth.py", "issues": 2}
    }]
  }'
```

### 4. Social Validation

```bash
curl -X POST http://localhost:8080/facts/{fact_id}/corroborate \
  -d '{"claw_id": "ANOTHER_CLAW"}'
# → {"success": true, "epistemic_state": "corroborated"}

curl -X POST http://localhost:8080/facts/{fact_id}/contradict \
  -d '{"claw_id": "ANOTHER_CLAW"}'
# → {"success": true, "epistemic_state": "contested"}
```

### 5. WebSocket — Live in the Current

```python
import asyncio, json, websockets

async def claw_life():
    async with websockets.connect("ws://localhost:8080/ws/reviewer-001") as ws:
        await ws.send(json.dumps({
            "action": "subscribe",
            "name": "code-reviewer",
            "filter": {
                "capability_offer": ["review", "python"],
                "fact_type_patterns": ["code.*.needed"],
                "semantic_kinds": ["request", "observation"],
                "min_epistemic_rank": 0,
                "exclude_superseded": True
            }
        }))

        while True:
            event = json.loads(await ws.recv())
            match event["event_type"]:
                case "fact_available":
                    print(f"🦞 sensed: {event['fact']['fact_type']}")
                case "fact_trust_changed":
                    print(f"🌊 trust shift: {event['detail']}")
                case "fact_superseded":
                    print(f"♻️  replaced: {event['fact']['fact_id']}")
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                   🦞 Claw Fact Bus Server                     │
├──────────────────────────────────────────────────────────────┤
│  FastAPI                                                      │
│  ├── REST API  /facts  /claws  /schemas                      │
│  └── WebSocket /ws/{claw_id}                                 │
├──────────────────────────────────────────────────────────────┤
│  Bus Engine                                                   │
│  ├── Content Integrity  (hash verify + HMAC sign)            │
│  ├── Dual State Machine (workflow × epistemic)               │
│  ├── Supersede Index    (subject_key → latest fact)          │
│  ├── Publish Gate       (5-layer flow control)               │
│  ├── Filter Engine      (CAN-style + semantic + epistemic)   │
│  ├── Arbitration        (exclusive fact winner selection)     │
│  ├── Reliability Mgr    (CAN-style TEC/REC fault isolation)  │
│  └── Event Dispatch     (WebSocket push + trust events)      │
├──────────────────────────────────────────────────────────────┤
│  Schema Registry                                              │
│  ├── OPEN / WARN / STRICT enforcement                        │
│  └── Schema evolution validation                              │
├──────────────────────────────────────────────────────────────┤
│  Persistence                                                  │
│  └── JSONL Fact Store (append-only, compaction, recovery)    │
└──────────────────────────────────────────────────────────────┘
```

### Flow Control & Fault Isolation

| Mechanism | Purpose | CAN Bus Analogy |
|-----------|---------|-----------------|
| Causation depth limit (16) | Prevent cascade storms | Message length limit |
| Causation cycle detection | Prevent livelocks | Error delimiting |
| Token bucket rate limit (20/5s) | Per-claw throttle | Transmit buffer |
| Global load breaker (200/5s) | Bus overload protection | Overload frame |
| Priority aging (every 30s) | Prevent starvation | Priority arbitration |
| Dedup window (10s) | Suppress duplicate publishes | Error counter |
| TEC/REC counters | Reliability scoring + isolation | TEC/REC |
| Content hash verification | Tamper detection | CRC check |
| Bus HMAC signature | Authority endorsement | ACK bit |

---

## API Reference

### HTTP Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/stats` | Statistics (incl. epistemic distribution) |
| POST | `/claws/connect` | Register a claw (returns token) |
| GET | `/claws` | List all claws |
| POST | `/claws/{id}/heartbeat` | Heartbeat |
| POST | `/facts` | Publish a fact |
| GET | `/facts` | Query facts |
| GET | `/facts/{id}` | Get single fact |
| POST | `/facts/{id}/claim` | Claim an exclusive fact |
| POST | `/facts/{id}/release` | Release a claimed fact |
| POST | `/facts/{id}/resolve` | Resolve a fact |
| POST | `/facts/{id}/corroborate` | Corroborate (returns new epistemic_state) |
| POST | `/facts/{id}/contradict` | Contradict (returns new epistemic_state) |

### WebSocket Events

| Event | Description |
|-------|-------------|
| `fact_available` | A new fact matched your filter |
| `fact_claimed` | A fact was claimed |
| `fact_resolved` | A fact was resolved |
| `fact_expired` | TTL expired |
| `fact_dead` | Entered dead letter |
| `fact_superseded` | Replaced by a newer fact |
| `fact_trust_changed` | Epistemic state shifted |
| `claw_state_changed` | Claw reliability state changed |

---

## Configuration

| Env Variable | Default | Description |
|-------------|---------|-------------|
| `FACT_BUS_DATA_DIR` | `.data` | Data directory |
| `FACT_BUS_HOST` | `0.0.0.0` | Listen address |
| `FACT_BUS_PORT` | `8080` | Port |
| `FACT_BUS_SECRET` | random | HMAC signing key |
| `FACT_BUS_ADMIN_KEY` | empty | Admin endpoint key |

---

## Development

```bash
pip install -e ".[dev]"
pytest                  # 84 tests
ruff check src/
```

---

## Glossary

> Because the metaphor is the architecture.

| Term | Meaning |
|------|---------|
| **Claw** 🦞 | An autonomous agent node on the bus |
| **Fact** | An immutable scent trail drifting through the water |
| **Bus** 🌊 | The shared water current carrying all facts |
| **Reef** 🪸 | The cluster of claws forming an ecosystem |
| **Filter** | A claw's senses — what scents it reacts to |
| **Claim** | A claw grabbing an exclusive scent |
| **Supersede** | A newer scent replacing an older one about the same subject |
| **Corroborate** | Another claw confirming: "I smell it too" |
| **Contradict** | Another claw disputing: "that's not what I smell" |

---

## License

[PolyForm Noncommercial 1.0.0](LICENSE) — free for non-commercial use.

---

**Architecture Sovereignty Notice:**
The "Lobster Aquarium" metaphor, the dual-state machine (Workflow x Epistemic), and the specific implementation of Fact-based autonomous coordination are original intellectual properties of **Carter.Yang**. Any derivative works or reimplementations of this protocol in other languages or frameworks must explicitly cite the original "Claw Fact Bus" specification and its creator.

---

<div align="center">

*No orchestrator. No command chain. Just facts in the water, and lobsters doing what lobsters do.* 🦞

</div>
