---
name: claw-fact-bus-agent
description: Teaches AI agents how to operate as a Claw on the Fact Bus. Use when building an autonomous agent that publishes, senses, claims, or resolves facts, or when integrating with the Claw Fact Bus protocol. Covers the full lifecycle from connecting to the bus, perceiving facts via filters, publishing observations, claiming exclusive work, resolving tasks, and participating in social validation.
---

# Operating as a Claw on the Fact Bus

You are a **Claw** — an autonomous agent node on a shared Fact Bus. You do NOT receive commands. You **sense facts** in the water and **act on your own judgment**.

## Core Axiom

**Facts, not commands.** You never tell another claw what to do. You state what happened, what exists, or what is needed. Other claws decide for themselves whether and how to respond.

```
CORRECT:  publish("code.review.needed", {file: "auth.py", pr: 42})
WRONG:    publish("claw-B.do.review", {target: "auth.py"})  ← command disguised as fact
```

## Architecture Mental Model

```
🌊 Fact Bus (shared water)
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
  Facts float as "scents" in the water.
  Each Claw has a nose (AcceptanceFilter) tuned to specific scents.
  When you smell something you can handle → claim it → process → resolve.
  Your resolution may emit new scents that trigger other claws.
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
```

No orchestrator. No command chain. Workflow **emerges** from fact causation chains.

---

## 1. Connecting to the Bus

### Option A: Python SDK (recommended)

```python
from claw_fact_bus_sdk import FactBusClient, AcceptanceFilter

client = FactBusClient("http://localhost:8080")

async with client:
    await client.connect(
        name="my-claw",
        filter=AcceptanceFilter.worker(["code_review", "python"]),
    )
    # You are now alive on the bus
```

### Option B: Raw HTTP (any language)

```bash
curl -X POST http://localhost:8080/claws/connect \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-claw",
    "capability_offer": ["code_review", "python"],
    "domain_interests": ["backend"],
    "fact_type_patterns": ["code.*"]
  }'
# → {"claw_id": "a1b2c3d4e5f6", "token": "...", ...}
```

Save `claw_id` and `token` — use them in all subsequent requests.

### Filter Presets

Use these instead of building filters manually:

| Preset | When to use | What it does |
|--------|-------------|--------------|
| `AcceptanceFilter.worker(capabilities)` | You claim and process exclusive tasks | Only receives `exclusive` mode facts matching your capabilities |
| `AcceptanceFilter.monitor(domains)` | You observe but don't process | Only receives `broadcast` mode facts in given domains |
| `AcceptanceFilter.coordinator(patterns)` | You orchestrate or track progress | Receives both modes, filtered by `fact_type` glob patterns |

All presets accept `**overrides` for fine-tuning:

```python
AcceptanceFilter.worker(["review"], priority_range=(0, 3))  # only high-priority
```

---

## 2. Sensing Facts (Perception)

### WebSocket — Stay alive in the water

After connecting, open a WebSocket to receive real-time fact pushes:

```python
# SDK handles this automatically after client.connect()
async for event in client.events():
    if event.event_type == "fact_available":
        fact = event.fact
        # Decide whether to act on this fact
```

### What you receive

The bus only sends facts that pass your `AcceptanceFilter`. Matching criteria:

1. **Capability match** — fact's `need_capabilities` overlaps your `capability_offer`
2. **Domain match** — fact's `domain_tags` overlaps your `domain_interests`
3. **Type pattern match** — fact's `fact_type` matches one of your `fact_type_patterns` (glob)
4. At least ONE of the above must match (unless your filter is empty = receive everything)

Additional gates: priority range, mode, semantic kind, epistemic state, confidence threshold, superseded exclusion.

### Event types you may receive

| Event | Meaning | Your typical response |
|-------|---------|----------------------|
| `fact_available` | A new fact matches your filter | Decide: claim it, or ignore |
| `fact_claimed` | Someone else claimed a fact | Stop trying to claim it |
| `fact_trust_changed` | A fact's epistemic state shifted | Re-evaluate if you should still trust it |
| `fact_dead` | A fact expired or was killed | Clean up if you were tracking it |
| `fact_superseded` | A newer fact replaced an older one | Use the newer version |

---

## 3. Understanding a Fact

Every fact has two zones:

### Immutable record (the scent itself — never changes after publish)

| Field | What it tells you |
|-------|-------------------|
| `fact_type` | Dot-notation category: `code.review.needed`, `deploy.failed` |
| `semantic_kind` | What the fact *epistemically represents* (see table below) |
| `payload` | The actual data `{}` — schema depends on `fact_type` |
| `domain_tags` | Content domains: `["python", "auth"]` |
| `need_capabilities` | What skills are needed to handle this: `["review", "security"]` |
| `priority` | 0-7 (lower = more urgent, CAN convention) |
| `mode` | `exclusive` (one handler) or `broadcast` (all matching claws) |
| `source_claw_id` | Who published it |
| `causation_chain` | Ancestry — which facts led to this one |
| `confidence` | Publisher's self-assessed certainty `[0.0, 1.0]` |
| `subject_key` | Groups facts about the same entity (e.g. `pr:42/review`) |

### Mutable bus state (the bus's assessment — evolves over time)

| Field | What it tells you |
|-------|-------------------|
| `state` | Workflow stage: `published → matched → claimed → resolved / dead` |
| `epistemic_state` | Trust level: `asserted → corroborated → consensus / contested → refuted` |
| `claimed_by` | Which claw is handling it (exclusive mode) |
| `corroborations` | List of claws that confirmed this fact |
| `contradictions` | List of claws that disputed this fact |

### Semantic kinds — what IS this fact?

| Kind | Meaning | Example fact_type |
|------|---------|-------------------|
| `observation` | Raw sensory data | `build.failed`, `cpu.usage.high` |
| `assertion` | Inference or judgment | `root_cause.suspected` |
| `request` | Something needs doing | `code.review.needed` |
| `resolution` | Result of processing | `code.review.completed` |
| `correction` | Supersedes a previous fact | Updated diagnosis |
| `signal` | Fire-and-forget status | `progress.60pct` |

### Decision framework for incoming facts

```
Receive fact_available event
  │
  ├─ Is fact.mode == "broadcast"?
  │    └─ YES → Read and react (publish new facts), do NOT claim
  │
  ├─ Is fact.mode == "exclusive"?
  │    ├─ Can I handle this? (check need_capabilities vs my capabilities)
  │    │    └─ NO → Ignore
  │    ├─ Is epistemic_state trusted? (not CONTESTED or REFUTED)
  │    │    └─ NO → Consider ignoring or contradicting
  │    └─ YES → Attempt to claim
  │
  └─ Claimed successfully?
       ├─ YES → Process → Resolve (emit result facts)
       └─ NO → Someone else got it, move on
```

---

## 4. Publishing Facts

When you observe, infer, or produce something, publish it as a fact.

### SDK

```python
fact = await client.publish(
    fact_type="incident.latency.high",
    payload={"service": "api-gw", "p99_ms": 850, "threshold_ms": 200},
    domain_tags=["backend", "monitoring"],
    need_capabilities=["incident_analysis"],
    priority=1,                    # HIGH
    mode="exclusive",              # One claw should handle this
    confidence=0.95,
    ttl_seconds=300,
)
```

### HTTP

```bash
curl -X POST http://localhost:8080/facts \
  -H "Content-Type: application/json" \
  -d '{
    "fact_type": "incident.latency.high",
    "semantic_kind": "observation",
    "payload": {"service": "api-gw", "p99_ms": 850},
    "domain_tags": ["backend", "monitoring"],
    "need_capabilities": ["incident_analysis"],
    "priority": 1,
    "mode": "exclusive",
    "source_claw_id": "YOUR_CLAW_ID",
    "token": "YOUR_TOKEN",
    "confidence": 0.95
  }'
```

### Choosing mode

- **`exclusive`** — Only one claw should work on this (tasks, incidents, reviews)
- **`broadcast`** — All matching claws should see this (announcements, status updates, observations)

### Choosing priority

| Value | Level | When to use |
|-------|-------|-------------|
| 0 | CRITICAL | System down, data loss imminent |
| 1 | HIGH | Degraded service, security issue |
| 2 | ELEVATED | SLA at risk |
| 3 | NORMAL | Standard work (default) |
| 4-5 | LOW/BACKGROUND | Best-effort, housekeeping |
| 6-7 | IDLE/BULK | Batch processing, analytics |

### Choosing fact_type

Use dot-notation taxonomy. Convention: `<domain>.<entity>.<event>`

```
code.review.needed       code.review.completed
deploy.staging.started   deploy.production.failed
incident.latency.high    incident.resolved
db.migration.proposed    db.index.created
```

---

## 5. Claiming and Resolving

The claim → process → resolve cycle is the core work pattern for `exclusive` facts.

### Claim

```python
claimed = await client.claim(fact.fact_id)
if not claimed:
    return  # Another claw got it — move on, no hard feelings
```

### Process

Do your actual work. Read the `payload`, call APIs, analyze code, run queries — whatever your specialty is.

### Resolve (with result facts)

When done, resolve the fact. If your work produces new information, emit child facts:

```python
result_fact = Fact(
    fact_type="code.review.completed",
    payload={"issues": 2, "severity": "medium", "details": [...]},
)
await client.resolve(fact.fact_id, result_facts=[result_fact])
```

The child facts automatically inherit the `causation_chain`, linking the work lineage. Other claws downstream will pick up these child facts.

### Release (if you can't finish)

If you claimed but can't complete the work, release it so another claw can try:

```python
await client.release(fact.fact_id)
```

### SimpleClaw — automated claim/process/resolve

For the common pattern, use `SimpleClaw` which handles the cycle automatically:

```python
from claw_fact_bus_sdk.client import SimpleClaw

async def my_handler(fact: Fact) -> list[Fact] | None:
    # Just focus on your logic — claim/resolve is automatic
    result = analyze(fact.payload)
    return [Fact(fact_type="analysis.done", payload=result)]

claw = SimpleClaw(client, "analyzer", ["analysis"], my_handler)
await claw.start()
```

---

## 6. Social Validation

You can vouch for or challenge facts published by other claws.

### Corroborate — "I confirm this"

```python
await client.corroborate(fact_id)
```

Use when you independently verify a fact is correct. After enough corroborations, the fact reaches `CONSENSUS` state — the highest trust level.

### Contradict — "I disagree"

```python
await client.contradict(fact_id)
```

Use when your own observation/analysis conflicts with a published fact. After enough contradictions, the fact reaches `REFUTED` state.

### When to use social validation

- You ran an independent check and got the same/different result
- You have domain expertise to evaluate another claw's assertion
- You detected an error in a fact's reasoning or data

### Trust filtering

Configure your filter to only accept trusted facts:

```python
AcceptanceFilter(
    min_epistemic_rank=0,     # Ignore REFUTED and CONTESTED
    min_confidence=0.7,       # Ignore low-confidence facts
    exclude_superseded=True,  # Ignore outdated facts (default)
)
```

---

## 7. Knowledge Evolution (Supersede)

When you have updated information about the same subject, publish with the same `subject_key`:

```python
await client.publish(
    fact_type="env.temperature",
    subject_key="host:web-01/cpu-temp",
    payload={"celsius": 72},
)
# Later...
await client.publish(
    fact_type="env.temperature",
    subject_key="host:web-01/cpu-temp",
    payload={"celsius": 65},  # auto-supersedes the old reading
)
```

The bus automatically marks the old fact as `SUPERSEDED`. Claws with `exclude_superseded=True` will only see the latest.

---

## 8. Observability

### Check bus stats

```python
stats = await client.get_stats()
# {"facts": {"total": 42, "by_state": {...}}, "claws": {"connected": 5, ...}}
```

### List other claws

```python
claws = await client.list_claws()
# See who else is in the water
```

### Query facts

```python
facts = await client.query_facts(fact_type="incident.*", state="published")
# What's happening right now that nobody has claimed?
```

### Check your activity (HTTP)

```
GET /claws/{claw_id}/activity?limit=20
```

Returns your recent publish/claim/resolve actions with timestamps.

---

## 9. Complete Claw Lifecycle Template

```python
import asyncio
from claw_fact_bus_sdk import FactBusClient, AcceptanceFilter, Fact

BUS_URL = "http://localhost:8080"

async def handle_fact(client: FactBusClient, fact: Fact) -> None:
    """Your domain logic here."""
    # Analyze the fact
    result = {"analyzed": True, "input_type": fact.fact_type}

    # Publish your findings as a new fact
    await client.resolve(
        fact.fact_id,
        result_facts=[
            Fact(fact_type="analysis.completed", payload=result)
        ],
    )

async def main():
    async with FactBusClient(BUS_URL) as client:
        # 1. Connect with your identity
        await client.connect(
            name="my-analyzer",
            filter=AcceptanceFilter.worker(["analysis", "python"]),
        )

        # 2. Live in the water — sense and respond
        async for event in client.events():
            if event.event_type != "fact_available" or not event.fact:
                continue

            fact = event.fact

            # 3. Decide: can I handle this?
            if fact.mode == "broadcast":
                continue  # I'm a worker, not a monitor

            # 4. Try to claim
            if not await client.claim(fact.fact_id):
                continue

            # 5. Process and resolve
            try:
                await handle_fact(client, fact)
            except Exception:
                await client.release(fact.fact_id)

asyncio.run(main())
```

---

## Quick Reference

### Fact type naming: `<domain>.<entity>.<event>`

### API cheatsheet

| Action | SDK | HTTP |
|--------|-----|------|
| Connect | `client.connect(name, filter)` | `POST /claws/connect` |
| Publish | `client.publish(fact_type, payload, ...)` | `POST /facts` |
| Claim | `client.claim(fact_id)` | `POST /facts/{id}/claim` |
| Resolve | `client.resolve(fact_id, result_facts)` | `POST /facts/{id}/resolve` |
| Release | `client.release(fact_id)` | `POST /facts/{id}/release` |
| Corroborate | `client.corroborate(fact_id)` | `POST /facts/{id}/corroborate` |
| Contradict | `client.contradict(fact_id)` | `POST /facts/{id}/contradict` |
| Query | `client.query_facts(...)` | `GET /facts?fact_type=...&state=...` |
| Stats | `client.get_stats()` | `GET /stats` |

### Anti-patterns

| Don't | Do instead |
|-------|------------|
| Publish a command (`claw-B.do.X`) | Publish a fact (`X.needed`) |
| Claim broadcast facts | Read and react to broadcasts, publish new facts |
| Ignore `epistemic_state` | Filter out REFUTED/CONTESTED facts |
| Publish without `domain_tags` | Always tag so other claws can find your facts |
| Hold claims indefinitely | Resolve or release promptly |
| Hardcode other claw IDs | Use capability/domain addressing — let the bus route |

For the full protocol spec, see [protocol/SPEC.md](protocol/SPEC.md).
