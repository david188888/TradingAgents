"""Code-owned questions, source partitions and dimension ceilings."""

from tradingagents.agents.schemas._research_assessment import (
    DIMENSIONS_BY_MODE,
    DimensionAssessmentV1,
)

ROLE_ORDER = ("operating_quality", "event_context", "market_context")
QUESTIONS = {
    "company_research": "公司经营质量如何，哪些证据支持判断，哪些关键问题尚未确定？",
    "catalyst_research": "未来84天哪些催化可能改变判断，其兑现条件和失效条件是什么？",
    "holding_review": "原持仓假设受到哪些新证据支持或挑战，哪些条件需要重新核查？",
}


def fact_views(record):
    sources = {source.evidence_id: source for source in record.evidence}
    metric_sources = {key for metric in record.metrics if metric.availability == "available"
                      for key in metric.input_evidence_ids}
    views = {role: [] for role in ROLE_ORDER}
    for fact in record.claims:
        if fact.kind != "fact":
            continue
        if any(sources[key].availability != "available" or sources[key].content is None
               or sources[key].usable_as_of is None for key in fact.evidence_ids):
            continue
        names = [sources[key].source_name for key in fact.evidence_ids]
        if any(name == "tushare.financial_statements" for name in names):
            views["operating_quality"].append(fact)
        elif any(name == "cninfo.announcements" for name in names):
            views["event_context"].append(fact)
        elif any(name == "user.original_thesis" for name in names):
            if record.mode == "holding_review":
                views["operating_quality"].append(fact)
        elif (set(fact.evidence_ids) & metric_sources or
              any(name in {"tushare.adjusted_daily", "tencent.qfq"} for name in names)):
            views["market_context"].append(fact)
    return {role: tuple(items) for role, items in views.items()}


def dimension_policy(record):
    views = fact_views(record)
    thesis = any(source.source_name == "user.original_thesis" and source.availability == "available"
                 for source in record.evidence)
    financial = any(any(source.source_name == "tushare.financial_statements"
                        for source in record.evidence if source.evidence_id in fact.evidence_ids)
                    for fact in views["operating_quality"])
    policies = {
        "operating_quality": ("conditional" if financial else "unresolved", "qualified_financial_fields_missing"),
        "valuation": ("unresolved", "qualified_valuation_inputs_missing"),
        "market_context": ("conditional" if views["market_context"] else "unresolved", "qualified_market_metrics_missing"),
        "catalyst_delivery": ("conditional" if views["event_context"] else "unresolved", "qualified_event_evidence_missing"),
        "holding_thesis": ("conditional" if thesis and financial else "unresolved", "original_thesis_or_new_operating_evidence_missing"),
    }
    return {name: policies[name] for name in DIMENSIONS_BY_MODE[record.mode]}


def gate_dimensions(record, proposed):
    """Propagate challenged dependencies, never permit narrative to raise a ceiling."""
    if tuple(item.dimension for item in proposed) != DIMENSIONS_BY_MODE[record.mode]:
        raise ValueError("synthesis dimensions must follow the mode's code-owned order")
    claims = {item.claim_id: item for item in record.claims}
    views = fact_views(record)
    role_for = {"operating_quality": "operating_quality", "holding_thesis": "operating_quality",
                "catalyst_delivery": "event_context", "market_context": "market_context"}
    output = []
    for item in proposed:
        if len(set(item.claim_ids)) != len(item.claim_ids) or not set(item.claim_ids) <= claims.keys():
            raise ValueError("synthesis contains an invalid claim reference")
        ceiling, missing = dimension_policy(record)[item.dimension]
        allowed_facts = {fact.claim_id for fact in views.get(role_for.get(item.dimension), ())}
        dependencies = set(item.claim_ids)
        for claim_id in item.claim_ids:
            claim = claims[claim_id]
            if claim.kind == "unknown" or not set(claim.supporting_fact_ids or (claim_id,)) <= allowed_facts:
                raise ValueError("synthesis uses facts from the wrong dimension")
            dependencies.update(claim.supporting_fact_ids)
        cited_facts = [claims[key] for key in dependencies if claims[key].kind == "fact"]
        names = {source.source_name for fact in cited_facts for source in record.evidence
                 if source.evidence_id in fact.evidence_ids}
        if item.dimension in {"operating_quality", "holding_thesis"} and item.claim_ids:
            if "tushare.financial_statements" not in names:
                raise ValueError("operating judgement requires cited financial evidence")
            if item.dimension == "holding_thesis" and "user.original_thesis" not in names:
                raise ValueError("holding judgement requires cited original thesis")
        # Challenges affect all dimensions using the targeted hypothesis/facts.
        relevant = []
        for challenge in record.challenges:
            targets = set(challenge.target_claim_ids)
            for target in challenge.target_claim_ids:
                targets.update(claims[target].supporting_fact_ids)
            if targets & dependencies:
                relevant.append(challenge.challenge_id)
        limits = list(item.limitations)
        status = item.status
        if ceiling == "unresolved" or not item.claim_ids:
            status = "unresolved"
            limits.append(missing if ceiling == "unresolved" else "supporting_claims_missing")
        elif status == "supported":
            status = "conditional"
            limits.append("hypothesis_requires_further_evidence")
        if relevant:
            limits.append("unresolved_challenge_dependency")
        if item.dimension == "catalyst_delivery" and ceiling != "unresolved":
            limits.append("announcement_titles_do_not_prove_delivery")
        if status == "unresolved" and not limits:
            limits.append("dimension_unresolved")
        output.append(DimensionAssessmentV1(dimension=item.dimension, status=status,
            judgement="合格资料或对应支撑依据不足，暂不能形成此项判断。" if ceiling == "unresolved" or not item.claim_ids else item.judgement,
            claim_ids=item.claim_ids if ceiling != "unresolved" else (),
            challenge_ids=tuple(relevant), limitations=tuple(dict.fromkeys(limits))))
    return tuple(output)
