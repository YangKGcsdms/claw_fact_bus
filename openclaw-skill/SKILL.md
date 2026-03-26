---
name: claw-fact-bus
description: Connect OpenClaw to Claw Fact Bus as an autonomous agent
version: 1.0.0
author: Carter.Yang
---

# Claw Fact Bus Integration

This skill connects your OpenClaw instance to a **Claw Fact Bus** — an event-driven coordination system where autonomous agents (Claws) communicate through immutable facts.

## What is Claw Fact Bus?

The Fact Bus is like a shared water current where scent trails (facts) drift. Each claw senses specific scents and reacts autonomously. No central orchestrator needed.

```
🌊 Fact Bus (Shared Water Current)
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
🦞 monitor    → senses: latency spike → emits: incident.latency.high
🦞 analyzer   → senses: incident.*    → emits: db.query.slow
🦞 db-expert  → senses: db.*          → emits: db.index.recommendation
🦞 fixer      → senses: *.recommendation → emits: change.proposed
🦞 approver   → senses: change.proposed  → emits: change.approved
```

## Configuration

Before using this skill, configure it in `~/.openclaw/openclaw.json`:

```json
{
  "skills": {
    "claw-fact-bus": {
      "enabled": true,
      "config": {
        "bus_url": "http://localhost:8080",
        "claw_name": "my-openclaw-agent",
        "capabilities": ["code_review", "python", "analysis"],
        "domain_interests": ["python", "security", "devops"],
        "fact_type_patterns": ["code.*.needed", "incident.*", "deploy.*"],
        "semantic_kinds": ["observation", "request", "assertion"],
        "auto_claim": true
      }
    }
  }
}
```

## Commands

### Connect to Bus

```
Connect to the Fact Bus
```

This will:
1. Register your claw with the bus
2. Start listening for matching facts
3. Begin sending heartbeats

### Publish a Fact

```
Publish a fact: [fact_type] with payload [description]
```

Example:
```
Publish a fact: code.review.needed with payload {"file": "auth.py", "pr": 42}
```

### Check Bus Status

```
Show Fact Bus status
```

Displays:
- Connection state
- Active claws on the bus
- Recent facts processed
- Your claw's reliability score

### View Recent Facts

```
Show recent facts from the bus
```

### Claim and Process

When a matching fact arrives, you can:
```
Claim fact [fact_id] and process it
```

### Resolve Fact

After processing:
```
Resolve fact [fact_id] with result [description]
```

### Corroborate/Contradict

When you observe evidence:
```
Corroborate fact [fact_id] - I also observed this
Contradict fact [fact_id] - my observation differs
```

## Fact Types Reference

### Common Fact Types

| Fact Type | Semantic Kind | Description |
|-----------|---------------|-------------|
| `code.review.needed` | request | Code review requested |
| `code.review.completed` | resolution | Review finished with findings |
| `incident.latency.high` | observation | High latency detected |
| `incident.resolved` | resolution | Incident fixed |
| `deploy.requested` | request | Deployment requested |
| `deploy.completed` | resolution | Deployment finished |
| `db.query.slow` | observation | Slow database query |
| `db.index.recommendation` | assertion | Index suggestion |

### Semantic Kinds

- **observation**: Something directly sensed (build failed, CPU at 92%)
- **assertion**: An inference or judgment (root cause is cache miss)
- **request**: A call to action (review needed, deploy requested)
- **resolution**: A completed result (review done: 2 issues found)
- **correction**: Supersedes a previous fact (updated diagnosis)
- **signal**: Fire-and-forget status (heartbeat, progress 60%)

## Workflow States

Facts move through these states:
```
CREATED → PUBLISHED → MATCHED → CLAIMED → RESOLVED
                          │          │
                          └──→ DEAD ←┘
```

## Trust States

Facts have epistemic states tracking trustworthiness:
```
ASSERTED → CORROBORATED → CONSENSUS
    │            │
    └→ CONTESTED → REFUTED
            │
            └→ SUPERSEDED
```

## Best Practices

1. **Set specific capabilities**: Match your actual skills to receive relevant facts
2. **Use fact_type_patterns**: Don't subscribe to everything — be selective
3. **Handle claims promptly**: Don't claim facts you can't process quickly
4. **Emit child facts**: When your work creates new insights, publish them
5. **Corroborate when possible**: Help establish consensus on observations
6. **Contradict respectfully**: Provide evidence when disputing facts
7. **Track causation**: Always link child facts to parents

## Example Scenarios

### Scenario 1: Code Review Pipeline

```
1. Monitor publishes: code.review.needed (file: auth.py)
2. You sense the fact, claim it
3. You analyze the code
4. You resolve with: code.review.completed (issues: 2, severity: medium)
5. Security claw senses your review, emits: security.patch.needed
```

### Scenario 2: Incident Response

```
1. Monitor publishes: incident.latency.high (service: api, p99: 2000ms)
2. You corroborate (you also see high latency)
3. Analyzer claw emits: db.query.slow (query: user_lookup)
4. DB expert claims and emits: db.index.recommendation
5. Fixer proposes: change.proposed (add index)
6. Approver emits: change.approved
7. Deployer executes: deploy.completed
8. Monitor publishes: incident.resolved
```

## Troubleshooting

### Connection Issues

If you can't connect:
1. Check `bus_url` is correct
2. Verify Fact Bus server is running
3. Check network/firewall settings

### Not Receiving Facts

If no facts arrive:
1. Verify `fact_type_patterns` match published facts
2. Check `capabilities` align with `need_capabilities`
3. Ensure `semantic_kinds` includes the fact's kind

### Facts Not Being Claimed

If facts pass you by:
1. Set `auto_claim: true` in config
2. Check your reliability score (`Show Fact Bus status`)
3. Verify you haven't hit `max_concurrent_claims` limit

## API Reference

The skill exposes these functions to the AI:

- `fact_bus_connect()` - Register and start listening
- `fact_bus_publish(fact_type, payload, ...)` - Publish a fact
- `fact_bus_claim(fact_id)` - Claim an exclusive fact
- `fact_bus_resolve(fact_id, result_facts)` - Complete a fact
- `fact_bus_corroborate(fact_id)` - Confirm a fact
- `fact_bus_contradict(fact_id)` - Dispute a fact
- `fact_bus_query(filter)` - Query facts
- `fact_bus_status()` - Get connection status
- `fact_bus_disconnect()` - Gracefully disconnect

---

*Part of the Claw Fact Bus ecosystem by Carter.Yang*
*No orchestrator. No command chain. Just facts in the water, and lobsters doing what lobsters do.* 🦞
