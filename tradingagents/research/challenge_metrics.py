"""Deterministic F03 counts; annotated denominators never come from model output."""

from collections import Counter

from pydantic import BaseModel, ConfigDict, model_validator

from tradingagents.agents.schemas._challenge_verification import Verifiability
from tradingagents.agents.schemas._verification_plan import (
    VerificationConditionV1,
    canonical_sha256,
)


class FrozenChallengeCaseV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: str
    target_claim_id: str
    proposition: str
    severity: str
    verifiability: Verifiability
    check: VerificationConditionV1 | None = None

    @model_validator(mode="after")
    def important_case_and_check(self):
        if (self.severity not in {"material", "critical"} or not self.case_id
                or not self.target_claim_id or not self.proposition
                or (self.verifiability == "computable_now") != (self.check is not None)):
            raise ValueError("invalid frozen important challenge case")
        return self


def _rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "ratio": numerator / denominator if denominator else None,
            "basis": "counted" if denominator else "not_applicable"}


def challenge_admission_counts(checkpoint):
    """Keep repair-deleted slots visible even when final output is a legal zero."""
    from tradingagents.agents.schemas._native_stage import ChallengeCandidateV1
    results = checkpoint.get("results", {})
    first, accepted = results.get("native.challenge_candidate"), results.get("native.challenge_accepted")
    first = ChallengeCandidateV1.model_validate(first) if first is not None else None
    accepted = ChallengeCandidateV1.model_validate(accepted) if accepted is not None else None
    for candidate in (first, accepted):
        if candidate is not None and candidate.prompt_sha256 != checkpoint.get("native.prompt.challenge"):
            raise ValueError("challenge admission prompt mismatch")
    repaired = "native.challenge.repair" in results
    original = first or (accepted if not repaired else None)
    before = len(original.indices) + len(original.rejections) if original else None
    after = len(accepted.indices) if accepted else None
    return {"first_proposal_slots": before,
        "initial_rejected_items": len(original.rejections) if original else None,
        "accepted_proposals": after,
        "final_rejected_items": len(accepted.rejections) if accepted else None,
        "repair_saved": repaired,
        "repair_removed_slots": max(before - after, 0) if repaired and before is not None and after is not None else None}


def challenge_metrics(record, *, cases=None):
    if record is None or record.challenge_check_policy is None:
        return {"availability": "not_recorded", "accepted_classification_completeness": None,
                "classification_coverage": None, "task_generation_rate": None,
                "actual_execution_rate": None, "successful_result_rate": None,
                "response_dispositions": None}
    challenges = [c for c in record.challenges if c.severity in {"material", "critical"}]
    ids = {c.challenge_id for c in challenges}
    outcomes = [o for o in record.challenge_outcomes or () if o.challenge_id in ids]
    generated = [o for o in outcomes if o.state != "not_generated"]
    executed = [v for v in record.verifications if v.challenge_id in ids and v.scope == "challenge_predicate_only"]
    valid = [v for v in executed if v.result_reason == "predicate_evaluated"]
    dispositions = Counter(r.disposition for r in record.dialogue.responses if r.challenge_id in ids) if record.dialogue else Counter()
    result = {
        "availability": "recorded", "important_challenges": len(challenges),
        "accepted_classification_completeness": _rate(sum(c.test is not None and c.test.verifiability is not None for c in challenges), len(challenges)),
        "classification_coverage": None, "task_generation_rate": None,
        "actual_execution_rate": _rate(len(executed), len(generated)),
        "successful_result_rate": _rate(len(valid), len(executed)),
        "categories": dict(Counter(c.test.verifiability for c in challenges if c.test and c.test.verifiability)),
        "task_states": dict(Counter(o.state for o in outcomes)),
        "execution_reasons": dict(Counter(v.result_reason for v in executed)),
        "code_confirmed_missing_inputs": sum(i.availability in {"missing", "unqualified"}
            for o in outcomes for i in o.inputs),
        "unknown_input_availability": sum(i.availability == "availability_unknown" for o in outcomes for i in o.inputs),
        "response_dispositions": {key: dispositions[key] for key in ("maintained", "revised", "withdrawn", "unanswerable")},
        "rejected_items": sum(s.startswith("native_challenge_rejected:") for s in record.limitations),
        "challenge_stage_unavailable": "native_stage_unavailable:challenge" in record.limitations,
    }
    if cases is not None:
        cases = tuple(FrozenChallengeCaseV1.model_validate(c) for c in cases)
        keys = [(c.target_claim_id, c.proposition) for c in cases]
        if len({c.case_id for c in cases}) != len(cases) or len(set(keys)) != len(keys):
            raise ValueError("duplicate frozen challenge case")
        correct_classification, correct_task = 0, 0
        for case in cases:
            matches = [c for c in challenges if c.target_claim_ids == (case.target_claim_id,)
                       and c.proposed_test == case.proposition and c.test is not None
                       and c.test.verifiability == case.verifiability]
            correct_classification += bool(matches)
            if case.verifiability == "computable_now":
                # The public record gate validates plan/task/result binding.
                correct_task += any(c.test.check == case.check and any(
                    o.challenge_id == c.challenge_id and o.state != "not_generated" for o in outcomes)
                    for c in matches)
        result["classification_coverage"] = _rate(correct_classification, len(cases))
        result["task_generation_rate"] = _rate(correct_task, sum(c.verifiability == "computable_now" for c in cases))
        result["annotation_sha256"] = canonical_sha256({"cases": [c.model_dump(mode="json") for c in cases]})
    return result
