"""Deterministic evaluation of evidence-bound transmission edges."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .metric_models import LogicEdgeV1, MetricObservationV1


def evaluate_logic_edge(
    *,
    edge_id: str,
    run_id: str,
    from_node: str,
    to_node: str,
    input_observation_ids: Sequence[str],
    observations: Mapping[str, MetricObservationV1],
    evidence_ref_ids: Sequence[str] = (),
    available_evidence_ref_ids: Sequence[str] = (),
    assumptions: Sequence[str] = (),
    missing_evidence: Sequence[str] = (),
    next_validation: str,
    invalidation: str,
    contradicted: bool = False,
) -> LogicEdgeV1:
    """Return a status without interpreting analyst prose.

    An edge is supported only when every declared input and evidence reference
    is available. Assumptions make an otherwise complete edge conditional;
    missing inputs or evidence block it. Contradiction has precedence.
    """
    ids = tuple(input_observation_ids)
    missing = list(missing_evidence)
    if len(set(ids)) != len(ids):
        raise ValueError("logic edge input IDs must be unique")
    unknown_inputs = [item for item in ids if item not in observations]
    if unknown_inputs:
        missing.extend(f"missing_observation:{item}" for item in unknown_inputs)
    unavailable_inputs = [
        item
        for item in ids
        if item in observations and observations[item].availability != "available"
    ]
    missing.extend(f"unavailable_observation:{item}" for item in unavailable_inputs)
    available_refs = set(available_evidence_ref_ids)
    missing_refs = [item for item in evidence_ref_ids if item not in available_refs]
    missing.extend(f"unavailable_evidence:{item}" for item in missing_refs)
    if contradicted:
        status = "contradicted"
    elif missing:
        status = "blocked"
    elif assumptions:
        status = "conditional"
    else:
        status = "supported"
    return LogicEdgeV1(
        edge_id=edge_id,
        run_id=run_id,
        from_node=from_node,
        to_node=to_node,
        status=status,
        input_observation_ids=ids,
        evidence_ref_ids=tuple(dict.fromkeys(evidence_ref_ids)),
        assumptions=tuple(dict.fromkeys(assumptions)),
        missing_evidence=tuple(dict.fromkeys(missing)),
        next_validation=next_validation,
        invalidation=invalidation,
    )
