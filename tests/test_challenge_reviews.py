"""Every hypothesis has an explicit, source-bound model review."""
from copy import deepcopy

import pytest

from tests import test_inline_bindings as fixtures

context = fixtures.context


def inputs(context):
    ctx = deepcopy(context)
    observation = ctx["factual_observations"][0]
    ctx["record"] = {"claims": [*ctx["facts"], {"claim_id": "i.one", "kind": "inference",
        "supporting_fact_ids": observation["fact_ids"]}],
        "hypotheses": [{"hypothesis_id": "h.one", "claim_id": "i.one"}]}
    envelope = {"proposal": {"reviews": [{"hypothesis_id": "h.one",
        "disposition": "no_additional_counterevidence", "rationale": "暂未发现额外反证，原因与持续性仍待核查",
        "supporting_fact_ids": observation["fact_ids"]}]}, "plans": [], "structured_bindings": [],
        "premises": [{"field_path": "reviews.0.rationale", "observation_ids": [observation["observation_id"]],
                      "pending_questions": ["后续披露能否验证该解释？"]}]}
    return ctx, envelope


def test_no_counterevidence_is_a_review_with_a_checked_rationale(context):
    from tradingagents.research.challenge_reviews import compile_reviews, replay_reviews
    ctx, envelope = inputs(context)
    receipt = compile_reviews(envelope, ctx, {"challenges": []})
    reviews = replay_reviews(receipt, ctx, {"challenges": []})
    assert len(reviews) == 1
    assert reviews[0]["hypothesis_id"] == "h.one"
    assert reviews[0]["rationale"].startswith("解释假设：")
    assert receipt["proof"]["fields"][0]["premise"]["observations"]
    tampered = deepcopy(receipt)
    tampered["proposal"]["reviews"][0]["rationale"] = "一切风险已排除"
    with pytest.raises(ValueError):
        replay_reviews(tampered, ctx, {"challenges": []})


@pytest.mark.parametrize("damage", ["empty", "duplicate", "wrong_hypothesis", "unsupported_challenged"])
def test_empty_or_inconsistent_reviews_cannot_complete_challenge(context, damage):
    from tradingagents.research.challenge_reviews import compile_reviews
    ctx, envelope = inputs(context)
    item = envelope["proposal"]["reviews"][0]
    if damage == "empty":
        envelope["proposal"]["reviews"] = []
    elif damage == "duplicate":
        envelope["proposal"]["reviews"].append(deepcopy(item))
    elif damage == "wrong_hypothesis":
        item["hypothesis_id"] = "h.unknown"
    else:
        item["disposition"] = "challenged"
    with pytest.raises(ValueError):
        compile_reviews(envelope, ctx, {"challenges": []})
