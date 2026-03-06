"""
Append-only JSONL fact store.

Provides:
- Durability: facts are persisted to disk immediately
- Recoverability: full state can be reconstructed from log
- Observability: human-readable, grep-able log
- Simplicity: no external dependencies (SQLite/Redis optional later)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterator

from ..types import EpistemicState, Fact, FactState, SemanticKind


class JSONLFactStore:
    """
    Append-only store for facts.

    File format: one JSON object per line, newline-delimited.
    Each entry has: {"fact": <Fact>, "event": "publish|claim|resolve|expire", "timestamp": <float>}
    """

    def __init__(self, data_dir: str | Path = ".data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.fact_log_path = self.data_dir / "facts.jsonl"

    def append(
        self, fact: Fact, event: str = "publish", metadata: dict | None = None
    ) -> None:
        """Append a fact entry to the log (atomic append)."""
        entry = {
            "fact": self._fact_to_dict(fact),
            "event": event,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }

        with open(self.fact_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

    def read_all(self) -> Iterator[tuple[Fact, str, dict]]:
        """
        Read all entries from the log, yielding (fact, event, metadata).
        Used for state recovery on startup.
        """
        if not self.fact_log_path.exists():
            return

        with open(self.fact_log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    fact = self._dict_to_fact(entry["fact"])
                    yield fact, entry.get("event", "publish"), entry.get("metadata", {})
                except (json.JSONDecodeError, KeyError) as e:
                    # Skip corrupted lines, log if needed
                    continue

    def query(
        self,
        fact_type: str | None = None,
        state: FactState | None = None,
        source_claw_id: str | None = None,
        limit: int = 100,
    ) -> list[Fact]:
        """Query facts from the log (reconstructs state by replaying)."""
        facts: dict[str, Fact] = {}

        for fact, event, _ in self.read_all():
            if event == "publish":
                facts[fact.fact_id] = fact
            elif event in ("claim", "resolve", "expire"):
                if fact.fact_id in facts:
                    facts[fact.fact_id].state = fact.state
                    facts[fact.fact_id].claimed_by = fact.claimed_by
                    facts[fact.fact_id].resolved_at = fact.resolved_at

        # Apply filters
        results = []
        for f in facts.values():
            if fact_type and f.fact_type != fact_type:
                continue
            if state and f.state != state:
                continue
            if source_claw_id and f.source_claw_id != source_claw_id:
                continue
            results.append(f)

        return sorted(results, key=lambda x: x.created_at, reverse=True)[:limit]

    def _fact_to_dict(self, fact: Fact) -> dict:
        """Convert Fact to serializable dict."""
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
            "causation_chain": fact.causation_chain,
            "causation_depth": fact.causation_depth,
            "subject_key": fact.subject_key,
            "supersedes": fact.supersedes,
            "created_at": fact.created_at,
            "ttl_seconds": fact.ttl_seconds,
            "schema_version": fact.schema_version,
            "confidence": fact.confidence,
            "content_hash": fact.content_hash,
            "signature": fact.signature,
            "protocol_version": fact.protocol_version,
            "state": fact.state.value,
            "epistemic_state": fact.epistemic_state.value,
            "claimed_by": fact.claimed_by,
            "resolved_at": fact.resolved_at,
            "effective_priority": fact.effective_priority,
            "sequence_number": fact.sequence_number,
            "superseded_by": fact.superseded_by,
            "corroborations": fact.corroborations,
            "contradictions": fact.contradictions,
        }

    def _dict_to_fact(self, data: dict) -> Fact:
        """Convert dict back to Fact."""
        from ..types import FactMode

        fact = Fact(
            fact_id=data["fact_id"],
            fact_type=data["fact_type"],
            semantic_kind=SemanticKind(data.get("semantic_kind", "observation")),
            payload=data["payload"],
            domain_tags=data.get("domain_tags", []),
            need_capabilities=data.get("need_capabilities", []),
            priority=data.get("priority", 3),
            mode=FactMode(data.get("mode", "exclusive")),
            source_claw_id=data.get("source_claw_id", ""),
            causation_chain=data.get("causation_chain", []),
            causation_depth=data.get("causation_depth", 0),
            subject_key=data.get("subject_key", ""),
            supersedes=data.get("supersedes", ""),
            created_at=data.get("created_at", 0.0),
            ttl_seconds=data.get("ttl_seconds", 300),
            schema_version=data.get("schema_version", "1.0"),
            confidence=data.get("confidence", 1.0),
            content_hash=data.get("content_hash", ""),
            signature=data.get("signature", ""),
            protocol_version=data.get("protocol_version", "1.0.0"),
            state=FactState(data.get("state", "created")),
            epistemic_state=EpistemicState(data.get("epistemic_state", "asserted")),
            claimed_by=data.get("claimed_by"),
            resolved_at=data.get("resolved_at"),
            effective_priority=data.get("effective_priority"),
            sequence_number=data.get("sequence_number", 0),
            superseded_by=data.get("superseded_by", ""),
            corroborations=data.get("corroborations", []),
            contradictions=data.get("contradictions", []),
        )
        return fact

    def compact(self, live_facts: dict[str, "Fact"]) -> int:
        """
        Compact the JSONL log by rewriting only entries for facts still in memory.

        Writes to a temp file, then atomically replaces the original.
        Returns the number of stale entries removed.
        """
        if not self.fact_log_path.exists():
            return 0

        live_ids = set(live_facts.keys())
        tmp_path = self.fact_log_path.with_suffix(".jsonl.tmp")
        kept = 0
        total = 0

        with open(self.fact_log_path, "r", encoding="utf-8") as src, \
             open(tmp_path, "w", encoding="utf-8") as dst:
            for line in src:
                total += 1
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    fact_id = entry.get("fact", {}).get("fact_id")
                    if fact_id in live_ids:
                        dst.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
                        dst.write("\n")
                        kept += 1
                except (json.JSONDecodeError, KeyError):
                    continue

        # Atomic replace
        tmp_path.replace(self.fact_log_path)

        return total - kept

    def get_stats(self) -> dict:
        """Return store statistics."""
        total_entries = 0
        if self.fact_log_path.exists():
            with open(self.fact_log_path, "r", encoding="utf-8") as f:
                total_entries = sum(1 for _ in f)

        return {
            "total_entries": total_entries,
            "data_dir": str(self.data_dir),
            "log_file": str(self.fact_log_path),
            "log_size_bytes": (
                self.fact_log_path.stat().st_size if self.fact_log_path.exists() else 0
            ),
        }
