"""
Acceptance filtering and priority arbitration.

CAN Bus analogy:
- Each ECU has hardware acceptance filters (mask + filter registers)
- Messages that don't pass the filter are silently ignored
- When two ECUs transmit simultaneously, bitwise arbitration on message ID resolves it

Filtering capabilities:
- SemanticKind filtering (observation, request, correction, ...)
- Epistemic state filtering (min trust level)
- Confidence threshold
- Superseded fact exclusion
- Subject key pattern matching
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from .types import (
    EPISTEMIC_RANK,
    AcceptanceFilter,
    ClawIdentity,
    ClawState,
    EpistemicState,
    Fact,
    FactMode,
)


@dataclass
class MatchResult:
    """Detailed result of a filter match, used for arbitration scoring."""

    matched: bool
    capability_overlap: int = 0
    domain_overlap: int = 0
    type_pattern_hit: bool = False
    score: float = 0.0


def evaluate_filter(fact: Fact, claw: ClawIdentity) -> MatchResult:
    """
    Evaluate whether a fact passes a claw's acceptance filter.

    Gate order (cheapest first):
      0. Claw health state
      1. Priority range
      2. Mode compatibility
      3. Semantic kind
      4. Epistemic state / confidence / superseded
      5. Content matching (capabilities, domains, type patterns)
      6. Subject key patterns
    """
    af = claw.acceptance_filter
    result = MatchResult(matched=False)

    # Gate 0: State check
    if claw.state in (ClawState.ISOLATED, ClawState.OFFLINE):
        return result

    # Gate 1: Priority range
    low, high = af.priority_range
    effective_priority = fact.effective_priority if fact.effective_priority is not None else fact.priority
    if not (low <= effective_priority <= high):
        return result

    # Gate 2: Mode compatibility
    if fact.mode not in af.modes:
        return result

    # Gate 3: Semantic kind
    if af.semantic_kinds and fact.semantic_kind not in af.semantic_kinds:
        return result

    # Gate 4: Epistemic gates
    if af.exclude_superseded and fact.epistemic_state == EpistemicState.SUPERSEDED:
        return result

    fact_rank = EPISTEMIC_RANK.get(fact.epistemic_state, 0)
    if fact_rank < af.min_epistemic_rank:
        return result

    if fact.confidence < af.min_confidence:
        return result

    # Gate 5: Content matching (at least one dimension must match)
    if fact.need_capabilities and af.capability_offer:
        cap_overlap = set(fact.need_capabilities) & set(af.capability_offer)
        result.capability_overlap = len(cap_overlap)

    if fact.domain_tags and af.domain_interests:
        domain_overlap = set(fact.domain_tags) & set(af.domain_interests)
        result.domain_overlap = len(domain_overlap)

    if af.fact_type_patterns:
        result.type_pattern_hit = any(
            fnmatch.fnmatch(fact.fact_type, pattern) for pattern in af.fact_type_patterns
        )

    content_matched = (
        result.capability_overlap > 0 or result.domain_overlap > 0 or result.type_pattern_hit
    )
    no_filters = (
        not af.capability_offer and not af.domain_interests and not af.fact_type_patterns
    )

    if not (content_matched or no_filters):
        return result

    # Gate 6: Subject key patterns
    if af.subject_key_patterns and fact.subject_key:
        if not any(fnmatch.fnmatch(fact.subject_key, p) for p in af.subject_key_patterns):
            return result

    result.matched = True
    if result.matched:
        result.score = _compute_match_score(result, claw)

    return result


def _compute_match_score(result: MatchResult, claw: ClawIdentity) -> float:
    """Composite match quality score for arbitration."""
    score = 0.0
    score += result.capability_overlap * 10.0
    score += result.domain_overlap * 5.0
    if result.type_pattern_hit:
        score += 3.0
    score *= claw.reliability_score
    return score


def arbitrate(fact: Fact, candidates: list[ClawIdentity]) -> list[ClawIdentity]:
    """
    Select which claw(s) should receive a fact.

    For BROADCAST: return all.
    For EXCLUSIVE: return single winner by score → reliability → claw_id.
    """
    if fact.mode == FactMode.BROADCAST:
        return candidates

    if not candidates:
        return []

    scored = []
    for claw in candidates:
        match = evaluate_filter(fact, claw)
        if match.matched:
            scored.append((match.score, claw.reliability_score, claw.claw_id, claw))

    if not scored:
        return []

    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return [scored[0][3]]
