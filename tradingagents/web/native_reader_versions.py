"""Frozen qualification for saved native workflows; never import live source policy.

These read-only rules reproduce the released partitions/publication gate in
2994304 (v1), 8662cb8 (v2), af37428 (v3), 4f4a0eb (v4), 8735e5d (v5).
Future workflow support must add an explicit policy instead of widening these.
The initial v1 gate in a549afb is accepted only when its exact output matches.
"""

from dataclasses import dataclass

from tradingagents.agents.schemas._research_assessment import (
    DIMENSIONS_BY_MODE,
    DimensionAssessmentV1,
)


@dataclass(frozen=True)
class SavedPolicy:
    operating: frozenset[str]
    prices: frozenset[str]
    bodies: frozenset[str] = frozenset()
    valuation: frozenset[str] = frozenset()
    scoped: bool = False


FINANCIAL = frozenset({"tushare.financial_statements", "sina.financial_statements"})
PRICES = frozenset({"tushare.adjusted_daily", "tencent.qfq", "tencent.sina_adjusted_daily"})
OPERATING = FINANCIAL | {"cninfo.operating_detail"}
BODIES = frozenset({"cninfo.document_excerpt"})
VALUATION = frozenset({"tencent.valuation_snapshot", "tushare.valuation_history"})
SUPPLEMENTAL = frozenset(
    {
        "ths.dated_forecast",
        "eastmoney.dated_forecast",
        "eastmoney.peer_candidates",
        "tencent.peer_valuation",
    }
)
POLICIES = {
    "evidence-production-v1": SavedPolicy(
        frozenset({"tushare.financial_statements"}),
        frozenset({"tushare.adjusted_daily", "tencent.qfq"}),
    ),
    "evidence-production-v2": SavedPolicy(FINANCIAL, PRICES),
    "evidence-production-v3": SavedPolicy(OPERATING, PRICES, BODIES, scoped=True),
    "evidence-production-v4": SavedPolicy(OPERATING, PRICES, BODIES, VALUATION, True),
    "evidence-production-v5": SavedPolicy(OPERATING, PRICES, BODIES, VALUATION, True),
    "evidence-production-v6": SavedPolicy(OPERATING, PRICES, BODIES, VALUATION, True),
}


def _policy(record, version):
    policy = POLICIES[version]
    # v5's expanded partition was enabled by the persisted evidence-check pack.
    if version in {"evidence-production-v5", "evidence-production-v6"} and record.evidence_checks is not None:
        return SavedPolicy(
            policy.operating | {"cninfo.numeric_row.v2"},
            policy.prices,
            policy.bodies,
            policy.valuation | SUPPLEMENTAL,
            policy.scoped,
        )
    return policy


def saved_fact_views(record, version):
    policy = _policy(record, version)
    sources = {s.evidence_id: s for s in record.evidence}
    metric_sources = {
        e for m in record.metrics if m.availability == "available" for e in m.input_evidence_ids
    }
    views = {key: [] for key in ("operating_quality", "event_context", "market_context")}
    for fact in record.claims:
        if fact.kind != "fact" or any(
            sources[e].availability != "available"
            or sources[e].content is None
            or sources[e].usable_as_of is None
            for e in fact.evidence_ids
        ):
            continue
        names = {sources[e].source_name for e in fact.evidence_ids}
        if names & (policy.operating | policy.valuation):
            role = "operating_quality"
        elif names & policy.bodies:
            role = (
                "operating_quality"
                if "native_dimension:operating_quality" in fact.limitations
                else "event_context"
            )
        elif "cninfo.announcements" in names:
            role = "event_context"
        elif "user.original_thesis" in names:
            if record.mode != "holding_review":
                continue
            role = "operating_quality"
        elif names & policy.prices or set(fact.evidence_ids) & metric_sources:
            role = "market_context"
        else:
            continue
        views[role].append(fact)
    return {key: tuple(value) for key, value in views.items()}


def _dimensions(record, proposed, version, *, initial_v1=False):
    policy = _policy(record, version)
    views = saved_fact_views(record, version)
    sources = {s.evidence_id: s for s in record.evidence}
    financial = any(
        sources[e].source_name in policy.operating
        for f in views["operating_quality"]
        for e in f.evidence_ids
    )
    thesis = any(
        s.source_name == "user.original_thesis" and s.availability == "available"
        for s in record.evidence
    )
    ceilings = {
        "operating_quality": (financial, "qualified_financial_fields_missing"),
        "valuation": (
            bool(policy.valuation) and record.valuation is not None,
            "qualified_valuation_inputs_missing",
        ),
        "market_context": (bool(views["market_context"]), "qualified_market_metrics_missing"),
        "catalyst_delivery": (bool(views["event_context"]), "qualified_event_evidence_missing"),
        "holding_thesis": (
            thesis and financial,
            "original_thesis_or_new_operating_evidence_missing",
        ),
    }
    supplied = {item.dimension: item for item in proposed}
    order = DIMENSIONS_BY_MODE[record.mode]
    if len(supplied) != len(proposed) or set(supplied) != set(order):
        raise ValueError("invalid_saved_dimensions")
    if initial_v1 and tuple(item.dimension for item in proposed) != order:
        raise ValueError("invalid_initial_v1_order")
    claims = {c.claim_id: c for c in record.claims}
    role_for = {
        "operating_quality": "operating_quality",
        "holding_thesis": "operating_quality",
        "valuation": "operating_quality",
        "market_context": "market_context",
        "catalyst_delivery": "event_context",
    }
    output = []
    for name in order:
        item = supplied[name]
        if (
            len(set(item.claim_ids)) != len(item.claim_ids)
            or not set(item.claim_ids) <= claims.keys()
        ):
            raise ValueError("invalid_saved_dimension_refs")
        available, missing = ceilings[name]
        if policy.scoped and available:
            missing = "dimension_judgement_requires_further_validation"
        if not available and not initial_v1:
            limits = (missing, *item.limitations)
            if item.claim_ids:
                limits += ("unqualified_dimension_claims_discarded",)
            output.append(
                DimensionAssessmentV1(
                    dimension=name,
                    status="unresolved",
                    judgement="合格资料或对应支撑依据不足，暂不能形成此项判断。",
                    limitations=tuple(dict.fromkeys(limits)),
                )
            )
            continue
        allowed = {f.claim_id for f in views.get(role_for[name], ())}
        if name == "valuation":
            allowed = {
                f.claim_id
                for f in views["operating_quality"]
                if all(sources[e].source_name in policy.valuation for e in f.evidence_ids)
            }
        dependencies = set(item.claim_ids)
        for cid in item.claim_ids:
            claim = claims[cid]
            if claim.kind == "unknown" or not set(claim.supporting_fact_ids or (cid,)) <= allowed:
                raise ValueError("invalid_saved_dimension_partition")
            dependencies.update(claim.supporting_fact_ids)
        names = {
            sources[e].source_name
            for cid in dependencies
            if claims[cid].kind == "fact"
            for e in claims[cid].evidence_ids
        }
        if (
            name in {"operating_quality", "holding_thesis"}
            and item.claim_ids
            and (
                not policy.operating & names
                or name == "holding_thesis"
                and "user.original_thesis" not in names
            )
        ):
            raise ValueError("invalid_saved_operating_support")
        relevant = []
        for challenge in record.challenges:
            targets = set(challenge.target_claim_ids)
            for cid in challenge.target_claim_ids:
                targets.update(claims[cid].supporting_fact_ids)
            if targets & dependencies:
                relevant.append(challenge.challenge_id)
        limits, status = list(item.limitations), item.status
        if not available or not item.claim_ids:
            status = "unresolved"
            limits.append(missing if not available else "supporting_claims_missing")
        elif status == "supported":
            status = "conditional"
            limits.append("hypothesis_requires_further_evidence")
        if relevant:
            limits.append("unresolved_challenge_dependency")
        if name == "catalyst_delivery" and available:
            limits.append(
                "company_disclosure_not_independent_delivery_verification"
                if policy.bodies & names
                else "announcement_titles_do_not_prove_delivery"
            )
        if status == "unresolved" and not limits:
            limits.append("dimension_unresolved")
        output.append(
            DimensionAssessmentV1(
                dimension=name,
                status=status,
                judgement=item.judgement
                if available and item.claim_ids
                else "合格资料或对应支撑依据不足，暂不能形成此项判断。",
                claim_ids=item.claim_ids if available else (),
                challenge_ids=tuple(relevant),
                limitations=tuple(dict.fromkeys(limits)),
            )
        )
    return tuple(output)


def saved_dimensions_match(record, proposed, version):
    if _dimensions(record, proposed, version) == record.assessment.dimensions:
        return True
    return version == "evidence-production-v1" and (
        _dimensions(record, proposed, version, initial_v1=True) == record.assessment.dimensions
    )
