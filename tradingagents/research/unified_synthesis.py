"""Translate bounded V7 synthesis, preserving host-owned evidence outcomes."""

from tradingagents.agents.schemas._research_dialogue import (
    ChallengeAdjudicationV1,
    JudgementConditionV1,
)
from tradingagents.research.unified_assessment import stance_ceiling


def investment_fields(record, proposal, dimensions):
    conditions = tuple(JudgementConditionV1(hypothesis_id=h.hypothesis_id,
                         invalidation_index=0, text=h.invalidation_conditions[0])
                       for h in record.hypotheses[:3])
    if proposal is None:
        return {"investment_stance": "insufficient_evidence", "supporting_arguments": (),
                "opposing_arguments": (), "change_conditions": conditions,
                "adjudications": tuple(ChallengeAdjudicationV1(challenge_id=r.challenge_id,
                    response_id=r.response_id, disposition=r.disposition,
                    rationale="综合未取得有效结果；保留原质疑与专项回应。") for r in record.dialogue.responses)}
    ceiling = stance_ceiling(record, dimensions)
    stance = proposal.investment_stance
    if ceiling == "no_favorable" and stance == "favorable":
        raise ValueError("critical economic challenge or missing anchor prohibits favorable")
    return {"investment_stance": "insufficient_evidence" if ceiling == "insufficient_evidence" else stance,
            "supporting_arguments": proposal.supporting_arguments,
            "opposing_arguments": proposal.opposing_arguments,
            "change_conditions": proposal.change_conditions or conditions,
            "adjudications": proposal.adjudications,
            "force_insufficient": ceiling == "insufficient_evidence"}
