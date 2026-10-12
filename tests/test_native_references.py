"""Exact, reversible prompt references without changing text or closed checks."""

import pytest

from tradingagents.execution.native_references import reference_aliases, translate_references


def test_aliases_are_order_independent_reversible_and_reference_only():
    context = {"record": {"claims": [{"claim_id": "c.z"}, {"claim_id": "c.a"}],
        "evidence": [{"evidence_id": "e.saved"}]},
        "dimension_claim_ids": {"operating_quality": ["c.z"]},
        "text": "c.z", "rationale": "claim_002", "check_id": "c.z",
        "supporting_fact_ids": ["c.a", "c.z", "c.unknown"], "statement": "引用 c.a"}
    aliases = reference_aliases(context)
    assert aliases == {"c.a": "claim_001", "c.z": "claim_002", "e.saved": "evidence_001"}
    shuffled = {**context, "record": {**context["record"], "claims": list(reversed(context["record"]["claims"]))}}
    assert reference_aliases(shuffled) == aliases
    encoded = translate_references(context, aliases)
    assert encoded["dimension_claim_ids"]["operating_quality"] == ["claim_002"]
    assert encoded["supporting_fact_ids"] == ["claim_001", "claim_002", "c.unknown"]
    for key in ("text", "rationale", "check_id", "statement"):
        assert encoded[key] == context[key]
    assert translate_references(encoded, {v: k for k, v in aliases.items()}) == context


@pytest.mark.parametrize("record", [
    {"claim_id": "shared", "hypothesis_id": "shared"},
    {"claims": [{"claim_id": "claim_001"}]},
])
def test_ambiguous_or_colliding_identifiers_fail_before_dispatch(record):
    with pytest.raises(ValueError):
        reference_aliases({"record": record})
