"""Review completeness is mechanical; its economic meaning stays unverified."""
from copy import deepcopy

from tradingagents.agents.schemas._challenge_review import HypothesisReviewsV1
from tradingagents.agents.schemas._verification_plan import canonical_sha256

POLICY = "hypothesis-review-coverage-v1"


class ChallengeReviewError(ValueError):
    code = "challenge_review_coverage"


def review_schema(schema, context):
    value = deepcopy(schema)
    addition = HypothesisReviewsV1.model_json_schema()
    value.setdefault("$defs", {}).update(addition["$defs"])
    ids = [h["hypothesis_id"] for h in context["record"]["hypotheses"]]
    value["$defs"]["HypothesisReviewV1"]["properties"]["hypothesis_id"]["enum"] = ids
    value["properties"]["reviews"] = {**addition["properties"]["reviews"], "minItems": len(ids), "maxItems": len(ids)}
    value.setdefault("required", []).append("reviews")
    return value


def split_reviews(envelope):
    value = deepcopy(envelope)
    if "reviews" not in value["proposal"]:
        raise ChallengeReviewError("challenge review coverage invalid")
    reviews = {"proposal": {"reviews": value["proposal"].pop("reviews")}}
    for kind in ("premises", "plans", "structured_bindings"):
        reviews[kind] = [b for b in value.get(kind, []) if b["field_path"].startswith("reviews.")]
        value[kind] = [b for b in value.get(kind, []) if not b["field_path"].startswith("reviews.")]
    return value, reviews


def _coverage(proposal, context, challenges):
    ids = {h["hypothesis_id"] for h in context["record"]["hypotheses"]}
    rows = proposal["reviews"]
    targeted = {c["hypothesis_id"] for c in challenges["challenges"]}
    if len(rows) != len(ids) or {r["hypothesis_id"] for r in rows} != ids:
        raise ChallengeReviewError("challenge review coverage invalid")
    for row in rows:
        if (row["disposition"] == "challenged") != (row["hypothesis_id"] in targeted):
            raise ChallengeReviewError("challenge review coverage invalid")


def compile_reviews(envelope, context, challenges):
    from tradingagents.research.numeric_narrative import (
        compile_numeric_stage,
        numeric_validation_context,
    )
    _coverage(envelope["proposal"], context, challenges)
    proposal, proof = compile_numeric_stage("challenge_review", envelope, context, HypothesisReviewsV1)
    return {"policy": POLICY, "context_sha256": canonical_sha256(numeric_validation_context(context)),
            "challenges_sha256": canonical_sha256(challenges), "proposal": proposal, "proof": proof}


def replay_reviews(receipt, context, challenges):
    from tradingagents.research.numeric_narrative import (
        numeric_validation_context,
        validate_numeric_stage,
    )
    if (not isinstance(receipt, dict) or receipt.get("policy") != POLICY
            or receipt.get("context_sha256") != canonical_sha256(numeric_validation_context(context))
            or receipt.get("challenges_sha256") != canonical_sha256(challenges)):
        raise ChallengeReviewError("challenge review receipt invalid")
    proposal = HypothesisReviewsV1.model_validate(receipt["proposal"]).model_dump(mode="json")
    _coverage(proposal, context, challenges)
    validate_numeric_stage("challenge_review", proposal, receipt["proof"], context, HypothesisReviewsV1)
    return proposal["reviews"]


def require_reviews(journal, stage, context, proposal):
    if stage == "challenge" and journal.state["identity"].get("research_delivery_policy") is not None:
        return replay_reviews(journal.ledger.cached_result("native.challenge_reviews"), context, proposal)
    return []
