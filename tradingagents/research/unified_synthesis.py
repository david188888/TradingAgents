"""Translate bounded V7 synthesis, preserving host-owned evidence outcomes."""

from tradingagents.agents.schemas._research_dialogue import (
    ChallengeAdjudicationV1,
    JudgementConditionV1,
)
from tradingagents.research.report_delivery import delivery_enabled
from tradingagents.research.unified_assessment import stance_ceiling


def investment_fields(record, proposal, dimensions):
    conditions = tuple(JudgementConditionV1(hypothesis_id=h.hypothesis_id,
                         invalidation_index=0, text=h.invalidation_conditions[0])
                       for h in record.hypotheses[:3])
    if proposal is None:
        fields = {"investment_stance": None if delivery_enabled(record) else "insufficient_evidence", "supporting_arguments": (),
                "opposing_arguments": (), "change_conditions": conditions,
                "adjudications": tuple(ChallengeAdjudicationV1(challenge_id=r.challenge_id,
                    response_id=r.response_id, disposition=r.disposition,
                    rationale="综合未取得有效结果；保留原质疑与专项回应。") for r in record.dialogue.responses)}
        if delivery_enabled(record):
            from tradingagents.agents.schemas._research_dialogue import excluded_support
            excluded = excluded_support(record)
            retained_analysis = (any(h.claim_id not in excluded for h in record.hypotheses)
                or any(r.status == "available" and r.supporting_fact_ids and r.disposition != "unanswerable" for r in record.dialogue.responses))
            fields["report_status"] = "specialist_summary" if retained_analysis else "basic_report"
        return fields
    ceiling = stance_ceiling(record, dimensions)
    stance = proposal.investment_stance
    if ceiling == "no_favorable" and stance == "favorable":
        raise ValueError("critical economic challenge or missing anchor prohibits favorable")
    fields = {"investment_stance": "insufficient_evidence" if ceiling == "insufficient_evidence" else stance,
            "supporting_arguments": proposal.supporting_arguments,
            "opposing_arguments": proposal.opposing_arguments,
            "change_conditions": proposal.change_conditions or conditions,
            "adjudications": proposal.adjudications,
            "force_insufficient": ceiling == "insufficient_evidence"}
    if delivery_enabled(record):
        fields["investment_stance"] = None if stance == "insufficient_evidence" else stance
        fields["report_status"] = "analysis_unrated" if fields["investment_stance"] is None else "synthesized"
        fields["force_insufficient"] = False
    if proposal.synthesis_sections is not None:
        from tradingagents.research.synthesis_sections import rating_blocked
        fields["synthesis_sections"] = proposal.synthesis_sections
        if rating_blocked(record, proposal.synthesis_sections):
            fields["investment_stance"] = None
            fields["report_status"] = "analysis_unrated"
    return fields
