"""Real admission, public judgement and SDK prompt boundaries, without networking."""

import copy
import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from tests.test_native_model import caller, main
from tests.test_native_valuation import valuation_fixture
from tests.test_unified_research import UnifiedCaller, run, setup
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.dataflows.native_qualification import NativeSourceUnavailable
from tradingagents.dataflows.native_valuation import qualify_snapshot
from tradingagents.execution import native_model as adapter
from tradingagents.execution.native_prompt_context import compact_synthesis_context
from tradingagents.research.native_record import build_native_record
from tradingagents.research.native_valuation import assemble_valuation
from tradingagents.research.native_versions import COMPANY_RESEARCH_POLICY


def quote(timestamp="20261013113000"):
    fields = [""] * 53
    for i, value in {1: "江淮汽车", 2: "600418", 3: "23.94", 30: timestamp,
                     37: "20", 45: "539.65", 46: "4.35"}.items():
        fields[i] = value
    return 'v_sh600418="' + "~".join(fields) + '";'


def test_intraday_quote_keeps_its_actual_timestamp_and_legacy_stays_settled():
    options = {"ts_code": "600418.SH", "last_session": "2026-10-12"}
    with pytest.raises(NativeSourceUnavailable):
        qualify_snapshot(quote(), **options)
    value = qualify_snapshot(quote(), **options, current_session="2026-10-13",
        captured_at=datetime(2026, 10, 13, 11, 31, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert value["as_of"] == "2026-10-13"
    assert value["quote_timestamp"] == "2026-10-13T11:30:00+08:00"
    assert value["quote_basis"] == "unsettled_session_snapshot"
    assert value["price"] == 23.94 and value["pe_ttm"] is None


@pytest.mark.parametrize("timestamp", ["20261013113200", "20261014110000", "20261009110000"])
def test_intraday_admission_rejects_future_and_other_dates(timestamp):
    with pytest.raises(NativeSourceUnavailable):
        qualify_snapshot(quote(timestamp), ts_code="600418.SH", last_session="2026-10-12",
            current_session="2026-10-13",
            captured_at=datetime(2026, 10, 13, 11, 31, tzinfo=ZoneInfo("Asia/Shanghai")))


def test_previous_session_history_does_not_acquire_the_intraday_date():
    draft, payloads = valuation_fixture()
    record = build_native_record(draft, payloads, mode="company_research", include_valuation=True)
    payloads = copy.deepcopy(payloads)
    snapshot = next(v for v in payloads.values() if "quote_timestamp" in v)
    history = next(v for v in payloads.values() if "rows" in v)
    snapshot.update(quote_basis="unsettled_session_snapshot", quote_captured_at="2026-09-30T16:30:00+08:00")
    history["rows"] = [r for r in history["rows"] if r["date"] < "2026-09-30"]
    history["as_of"] = history["rows"][-1]["date"]
    value = assemble_valuation(record, payloads)
    assert value.inputs.pb_history[-1].day.isoformat() == history["as_of"]
    assert value.inputs.snapshot.as_of.isoformat() == "2026-09-30"
    assert "valuation_history_precedes_quote" in value.limitations
    # No policy on a historical payload: retain the previous exact-date behavior.
    snapshot.pop("quote_basis")
    assert not assemble_valuation(record, payloads).inputs.pb_history


def test_missing_valuation_allows_caution_only_with_operating_support(tmp_path):
    journal, seed = setup(tmp_path)
    journal.put("identity", {**journal.state["identity"], "company_research_policy": COMPANY_RESEARCH_POLICY})
    seed = ResearchRecordV1.model_validate({**seed.model_dump(mode="json"), "valuation": None})
    result = run(journal, seed, UnifiedCaller(challenge=False))
    assert result.assessment.investment_stance == "unfavorable"
    assert result.assessment.opposing_arguments
    assert result.assessment.dimensions[1].status == "unresolved"
    payload = result.model_dump(mode="json")
    payload["assessment"]["investment_stance"] = "favorable"
    with pytest.raises(ValidationError):
        ResearchRecordV1.model_validate(payload)
    payload["assessment"]["investment_stance"] = "neutral"
    payload["assessment"]["dimensions"][0].update(status="unresolved", claim_ids=[])
    with pytest.raises(ValidationError):
        ResearchRecordV1.model_validate(payload)


def test_legacy_missing_valuation_still_requires_insufficient_evidence(tmp_path):
    journal, seed = setup(tmp_path)
    seed = ResearchRecordV1.model_validate({**seed.model_dump(mode="json"), "valuation": None})
    assert run(journal, seed, UnifiedCaller(challenge=False)).assessment.investment_stance == "insufficient_evidence"


def test_fresh_synthesis_schema_enumerates_each_dimension_and_preserves_sources(tmp_path, monkeypatch):
    journal, seed = setup(tmp_path / "kernel")
    proposals = UnifiedCaller(challenge=False)
    run(journal, seed, proposals)
    context = next(c for s, c in proposals.calls if s == "synthesis")
    journal, seed = setup(tmp_path / "adapter")
    journal.put("identity", {**journal.state["identity"], "company_research_policy": COMPANY_RESEARCH_POLICY})
    main(journal, "synthesis")
    prompts = []

    def invoke(prompt):
        prompts.append(prompt)
        schema = json.loads(prompt.split("Schema:\n", 1)[1].split("\nSaved research context:", 1)[0])
        encoded, _ = json.JSONDecoder().raw_decode(prompt.split("Saved research context:\n", 1)[1])
        for item in schema["properties"]["dimensions"]["items"]["oneOf"]:
            name = item["properties"]["dimension"]["const"]
            refs = item["properties"]["claim_ids"]
            if encoded["dimension_claim_ids"][name]:
                assert refs["items"]["enum"] == sorted(encoded["dimension_claim_ids"][name])
            else:
                assert refs["maxItems"] == 0
        assert all("content" not in e for e in encoded["record"]["evidence"])
        assert all("statement" in c for c in encoded["record"]["claims"])
        return SimpleNamespace(content=json.dumps(proposals("synthesis", encoded)))

    monkeypatch.setattr(adapter, "create_llm_client", lambda **_: SimpleNamespace(get_llm=lambda: SimpleNamespace(invoke=invoke)))
    model = caller(journal)
    result = model("synthesis", context)
    assert result["judgement"] == "基于现有资料偏谨慎"
    before = json.dumps(journal.state, sort_keys=True)
    assert model.recover_cached("synthesis", context) == result
    assert len(prompts) == 1 and json.dumps(journal.state, sort_keys=True) == before
    assert context["record"]["evidence"][0].get("content") is not None
    compact = compact_synthesis_context(context)
    assert compact["record"]["claims"] == context["record"]["claims"]


def test_fresh_specialist_uses_role_local_choices_and_restores_real_ids(tmp_path, monkeypatch):
    journal, seed = setup(tmp_path)
    journal.put("identity", {**journal.state["identity"], "company_research_policy": COMPANY_RESEARCH_POLICY})
    main(journal)
    context = {"facts": [{"claim_id": "fact.real", "evidence_ids": ["evidence.real"]}],
        "sources": [{"evidence_id": "evidence.real"}], "metrics": []}

    def invoke(prompt):
        schema = json.loads(prompt.split("Schema:\n", 1)[1].split("\nSaved research context:", 1)[0])
        choices = schema["$defs"]["HypothesisProposalV1"]["properties"]["supporting_fact_ids"]["items"]["enum"]
        assert choices == ["claim_001"]
        return SimpleNamespace(content=json.dumps({"hypotheses": [{"statement": "有条件的经营判断",
            "supporting_fact_ids": choices, "conditions": [{"condition_role": "invalidation", "text": "后续披露否定"}],
            "alternative_explanation": "一次性贡献"}]}))

    monkeypatch.setattr(adapter, "create_llm_client", lambda **_: SimpleNamespace(get_llm=lambda: SimpleNamespace(invoke=invoke)))
    assert caller(journal)("operating_quality", context)["hypotheses"][0]["supporting_fact_ids"] == ["fact.real"]
