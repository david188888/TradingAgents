"""Public V7 investment gates and support validation, without live retrieval."""

from tradingagents.agents.schemas._research_dialogue import excluded_support
from tradingagents.research.native_versions import UNIFIED_DIMENSIONS


def stance_ceiling(record, dimensions):
    if record.schema_version == 'research-record-v2':
        from tradingagents.research.search_effective import unreviewed_roles
        latest = {}
        for calculation in record.revision_calculations:
            latest[(calculation.field, calculation.period, calculation.operation)] = calculation
        if (unreviewed_roles(record) or any(c.status == 'conflict' for c in latest.values())
                or any(g.priority == 'critical' for g in record.search_gaps)
                or any(r.new_risks for r in record.search_reviews)):
            return 'no_favorable'
    by_name = {d.dimension: d for d in dimensions}
    from tradingagents.research.native_versions import COMPANY_RESEARCH_POLICY
    cautious = COMPANY_RESEARCH_POLICY in record.limitations
    from tradingagents.research.report_delivery import delivery_enabled
    delivery = delivery_enabled(record)
    if by_name["operating_quality"].status == "unresolved" or not by_name["operating_quality"].claim_ids:
        return "no_favorable" if delivery else "insufficient_evidence"
    if by_name["valuation"].status == "unresolved" or not by_name["valuation"].claim_ids or record.valuation is None:
        return "no_favorable" if cautious or delivery else "insufficient_evidence"
    claims = {c.claim_id: c for c in record.claims}
    valuation_sources = {e for dimension in dimensions for cid in dimension.claim_ids
                         for e in claims[cid].evidence_ids}
    # A range elsewhere in the record is not support for a conclusion that only
    # cites the quote. Require the saved anchor inputs to be cited as well.
    anchor_inputs_cited = set(record.valuation.input_evidence_ids) <= valuation_sources
    if any(c.severity == "critical" for c in record.challenges):
        return "no_favorable"
    if record.valuation.assessment.synthesis.reference_low_yi is None or not anchor_inputs_cited:
        return "no_favorable"
    return "conditional"


def validate_unified_assessment(record):
    assessment = record.assessment
    from tradingagents.research.report_delivery import delivery_enabled
    delivery = delivery_enabled(record)
    if delivery:
        if assessment.report_status is None or assessment.investment_stance == "insufficient_evidence":
            raise ValueError("new company reports require an explicit delivery state")
        if (assessment.report_status == "synthesized") != (assessment.investment_stance is not None):
            raise ValueError("unrated report must not manufacture an investment stance")
    elif assessment.report_status is not None or assessment.investment_stance is None:
        raise ValueError("legacy records cannot carry report delivery fields")
    if record.dialogue is None or record.mode != "company_research" or assessment.forward_window_calendar_days is not None:
        raise ValueError("V3 assessment requires unified company dialogue")
    if tuple(d.dimension for d in assessment.dimensions) != UNIFIED_DIMENSIONS:
        raise ValueError("unified research requires four dimensions")
    from tradingagents.research.native_policy import dimension_claim_ids, dimension_policy
    allowed = dimension_claim_ids(record)
    policies = dimension_policy(record, scoped=True, valuation=True)
    for dimension in assessment.dimensions:
        if not set(dimension.claim_ids) <= set(allowed[dimension.dimension]):
            raise ValueError("unified dimension uses unqualified or unrelated support")
        if dimension.status == "supported" or (dimension.status != "unresolved"
                and policies[dimension.dimension][0] == "unresolved"):
            raise ValueError("unified dimension cannot exceed its evidence ceiling")
    claims = {c.claim_id: c for c in record.claims if c.kind != "unknown"}
    replies = {r.response_id: r for r in record.dialogue.responses}
    excluded = excluded_support(record)
    positive_ids = set(assessment.key_claim_ids) | {c for d in assessment.dimensions for c in d.claim_ids}
    positive_ids.update(c for a in assessment.supporting_arguments for c in a.claim_ids)
    if excluded & positive_ids:
        raise ValueError("withdrawn or revised assertions cannot support the conclusion")
    for argument in (*assessment.supporting_arguments, *assessment.opposing_arguments):
        if len(set(argument.claim_ids)) != len(argument.claim_ids) or not set(argument.claim_ids) <= claims.keys():
            raise ValueError("investment argument contains invalid claims")
        if len(set(argument.response_ids)) != len(argument.response_ids) or not set(argument.response_ids) <= replies.keys():
            raise ValueError("investment argument contains invalid replies")
        for rid in argument.response_ids:
            reply = replies[rid]
            if reply.status != "available" or reply.disposition in {"unanswerable", "withdrawn"}:
                raise ValueError("absent or withdrawn replies cannot provide support")
            if not set(argument.claim_ids) <= set(reply.supporting_fact_ids):
                raise ValueError("revised argument must cite the reply's facts")
        if any(record_source.availability != "available" or record_source.content is None or record_source.usable_as_of is None
               for cid in argument.claim_ids for eid in claims[cid].evidence_ids
               for record_source in record.evidence if record_source.evidence_id == eid):
            raise ValueError("argument uses unqualified evidence")
    adjudications = {a.challenge_id: a for a in assessment.adjudications}
    if len(adjudications) != len(assessment.adjudications) or adjudications.keys() != {c.challenge_id for c in record.challenges}:
        raise ValueError("every challenge requires a separate adjudication")
    for cid, item in adjudications.items():
        reply = replies.get(item.response_id)
        if reply is None or reply.challenge_id != cid:
            raise ValueError("adjudication references another challenge's reply")
        if delivery and item.disposition != reply.disposition:
            raise ValueError("new report must preserve the saved reply disposition")
        if reply.disposition in {"withdrawn", "revised", "unanswerable"} and item.disposition != reply.disposition:
            raise ValueError("adjudication cannot strengthen the specialist's reply")
    hypotheses = {h.hypothesis_id: h for h in record.hypotheses}
    conditions = set()
    for condition in assessment.change_conditions:
        hypothesis = hypotheses.get(condition.hypothesis_id)
        key = (condition.hypothesis_id, condition.invalidation_index)
        if (hypothesis is None or condition.invalidation_index >= len(hypothesis.invalidation_conditions)
                or hypothesis.invalidation_conditions[condition.invalidation_index] != condition.text or key in conditions):
            raise ValueError("judgement condition does not match the public hypothesis")
        conditions.add(key)
    if hypotheses and not assessment.change_conditions:
        raise ValueError("unified judgement requires public falsifiers")
    ceiling = stance_ceiling(record, assessment.dimensions)
    if ceiling == "insufficient_evidence" and assessment.investment_stance != ceiling and not delivery:
        raise ValueError("missing operating or valuation support requires insufficient evidence")
    if ceiling == "no_favorable" and assessment.investment_stance == "favorable":
        raise ValueError("critical challenge or missing valuation anchor prohibits favorable")
    if assessment.investment_stance not in {None, "insufficient_evidence"} and not assessment.supporting_arguments and not assessment.opposing_arguments:
        raise ValueError("investment stance requires referenced reasons")
    if any(r.status == "unavailable" for r in record.dialogue.responses) and (
        assessment.completeness != "partial" or assessment.quality != "LOW_CONFIDENCE"
    ):
        raise ValueError("missing specialist replies require partial low-confidence research")
    if assessment.synthesis_sections is not None:
        from tradingagents.research.synthesis_sections import (
            UNFINISHED_ADJUDICATION,
            UNFINISHED_DIMENSION,
            UNFINISHED_JUDGEMENT,
            UNFINISHED_NEXT,
            rating_blocked,
            section_ids,
            unfinished_sections,
        )
        sections = assessment.synthesis_sections
        if not delivery or [s.section_id for s in sections.sections] != section_ids(record):
            raise ValueError("synthesis section ownership mismatch")
        missing = unfinished_sections(sections)
        if missing and (assessment.completeness != "partial" or assessment.quality != "LOW_CONFIDENCE"):
            raise ValueError("unfinished synthesis requires partial low-confidence delivery")
        if rating_blocked(record, sections) and (assessment.investment_stance is not None or assessment.report_status != "analysis_unrated"):
            raise ValueError("unfinished overall or critical adjudication prohibits rating")
        if "overall" in missing and (assessment.judgement != UNFINISHED_JUDGEMENT or assessment.next_check != UNFINISHED_NEXT
                or assessment.key_claim_ids or assessment.supporting_arguments or assessment.opposing_arguments):
            raise ValueError("unfinished overall must be host-owned")
        for item in assessment.adjudications:
            if "adjudication:" + item.challenge_id in missing and item.rationale != UNFINISHED_ADJUDICATION:
                raise ValueError("unfinished adjudication must be host-owned")
        for item in assessment.dimensions:
            if "dimension:" + item.dimension in missing and (
                    item.judgement != UNFINISHED_DIMENSION or item.status != "unresolved"
                    or item.claim_ids or item.challenge_ids or item.limitations != ("synthesis_section_unavailable",)):
                raise ValueError("unfinished dimension must be host-owned")
