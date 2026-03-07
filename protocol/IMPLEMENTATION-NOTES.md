# Claw Fact Bus — Implementation Notes

> Recommended defaults and algorithms for the reference Python implementation.
> These are NOT protocol requirements. Other implementations MAY use different values.

---

## Default Parameters

| Parameter | Value | Rationale |
|-----------|:-----:|-----------|
| Causation depth limit | 16 | Prevents cascade chains. Empirically sufficient for complex workflows |
| Dedup window | 10s | Balances duplicate suppression vs memory |
| Rate limit capacity | 20 tokens | Allows burst without flooding |
| Rate limit refill | 5/s | Sustained throughput for active claws |
| Load breaker window | 5s | Responsive without oscillation |
| Load breaker threshold | 200 facts/window | Sized for ~40 concurrent claws |
| Aging interval | 30s | Reasonable wait before priority boost |
| Aging floor | Priority 1 (HIGH) | CRITICAL reserved for genuine emergencies |
| Fact TTL default | 300s | 5 minutes, sufficient for most tasks |
| TEC degraded threshold | 128 | Mirrors CAN ISO 11898-1 |
| TEC isolated threshold | 256 | Mirrors CAN ISO 11898-1 |
| Consensus quorum | 2 corroborations | Minimal social validation |
| Refutation quorum | 2 contradictions | Minimal social validation |
| GC retain resolved | 600s | Keep resolved facts for 10 minutes |
| GC retain dead | 3600s | Keep dead facts for 1 hour |
| GC max facts | 10,000 | Memory safety |
| Compaction interval | 3600s | Hourly log compaction |
| Replay on reconnect | 50 facts | Recent unresolved facts replayed to reconnecting claws |

## Arbitration Scoring

```
score = (capability_overlap × 10 + domain_overlap × 5 + type_hit × 3)
        × reliability_score
```

Tiebreaker order: score → reliability_score → claw_id (lexicographic).

This formula weights capability match highest because it represents the strongest
signal of fitness. Domain overlap is secondary context, and type pattern hit
is the weakest signal (broadest match).

## TEC Adjustment Rules

| Event | TEC Δ |
|-------|:-----:|
| Fact contradicted | +8 |
| Schema validation failure | +8 |
| Fact expired unresolved | +2 |
| Rate limit exceeded | +1 |
| Fact corroborated | -1 |
| Fact resolved | -1 |
| Heartbeat OK | -1 |

## Content Hash Computation

```python
canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
content_hash = sha256(canonical.encode()).hexdigest()
```

## Bus Signature (Authority Stamp)

```python
message = f"{fact_id}|{content_hash}|{source_claw_id}|{fact_type}|{created_at}"
signature = hmac_sha256(bus_secret, message)
```

The signature proves a fact was verified and accepted by a specific bus instance.
It is NOT part of the core protocol — it is an implementation-level integrity feature.

## Persistence

The reference implementation uses an append-only JSONL fact store:
- Each event (publish, claim, resolve, dead, corroborate, contradict) is one line
- Periodic compaction removes entries for facts no longer in memory
- Recovery on startup replays the log to reconstruct in-memory state
