"""V7 real durable kernel and public records, offline proposals only."""
import copy
import json
import time
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from tests.test_minimum_evidence import fixture
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.execution.budget import BudgetBucket
from tradingagents.execution.native_publication import publish_native_record
from tradingagents.graph.native_research import run_native_research
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.research.native_record import build_native_record
from tradingagents.research.native_versions import UNIFIED_BUDGET_POLICY, UNIFIED_WORKFLOW_VERSION
from tradingagents.runtime.catalyst_checkpoint import CatalystJournal
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore


@pytest.mark.parametrize("invalid", [None, "unknown_alias", "wrong_dimension", "reply_fact"])
def test_synthesis_aliases_restore_canonical_references_and_preserve_gates(tmp_path, monkeypatch, invalid):
    from tests.test_native_model import main
    from tradingagents.execution import native_model as adapter

    journal, seed = setup(tmp_path / "kernel")
    proposals = UnifiedCaller()
    run(journal, seed, proposals)
    context = next(context for stage, context in proposals.calls if stage == "synthesis")
    journal, seed = setup(tmp_path / "adapter")
    main(journal, "synthesis")
    expected = adapter.SynthesisProposalV3.model_validate(proposals("synthesis", context)).model_dump(mode="json")
    prompts = []

    def invoke(prompt):
        prompts.append(prompt)
        encoded, _ = json.JSONDecoder().raw_decode(prompt.split("Saved research context:\n", 1)[1])
        assert encoded["record"]["claims"][0]["claim_id"].startswith("claim_")
        proposal = proposals("synthesis", encoded)
        by_dimension = {item["dimension"]: item for item in proposal["dimensions"]}
        proposal["dimensions"] = [by_dimension[name] for name in context["dimension_policy"]]
        if invalid is not None and len(prompts) == 1:
            if invalid == "reply_fact":
                proposal["opposing_arguments"][0].update(
                    claim_ids=[encoded["record"]["hypotheses"][0]["claim_id"]],
                    response_ids=[encoded["record"]["dialogue"]["responses"][0]["response_id"]])
            else:
                target = proposal["dimensions"][1]
                target["claim_ids"] = (["claim_999999"] if invalid == "unknown_alias"
                    else encoded["dimension_claim_ids"]["operating_quality"][:1])
        return SimpleNamespace(content=json.dumps(proposal))

    monkeypatch.setattr(adapter, "create_llm_client", lambda **_: SimpleNamespace(
        get_llm=lambda: SimpleNamespace(invoke=invoke)))
    model = adapter.NativeModelCaller(effective_config={"llm_provider": "deepseek", "quick_think_llm": "quick",
        "deep_think_llm": "deep"}, run_id=seed.run_id, ledger=journal.ledger,
        cancelled=lambda: False, deadline=lambda: time.monotonic() + 30)
    assert model("synthesis", context) == expected
    assert len(prompts) == (1 if invalid is None else 2)
    if invalid is not None:
        assert journal.state["native.model_diagnostics"]["synthesis.main"]["detail_code"] == (
            "argument_reply_fact_reference" if invalid == "reply_fact" else "dimension_claim_reference")
        assert "claim_" in prompts[1].split("Allowed dimension claim IDs:\n")[-1]
        if invalid == "reply_fact":
            assert "Exact reply fact bindings" in prompts[1] and "response_001" in prompts[1]
    if invalid is not None:
        journal.state["results"].pop("native.adapter.synthesis")
    journal.persist()
    restored = CatalystJournal(journal.observer, journal.state["identity"], require_existing=True)
    inactive = adapter.NativeModelCaller(effective_config=model.config, run_id=seed.run_id,
        ledger=restored.ledger, cancelled=lambda: True, deadline=lambda: -1)
    before = json.dumps(restored.state, sort_keys=True)
    assert inactive.recover_cached("synthesis", context) == expected
    assert json.dumps(restored.state, sort_keys=True) == before
    assert len(prompts) == (1 if invalid is None else 2)


@pytest.mark.parametrize("alias_version", [None, 1])
def test_existing_synthesis_prompt_keeps_saved_reference_format(tmp_path, monkeypatch, alias_version):
    import hashlib

    from tests.test_native_model import main
    from tradingagents.execution import native_model as adapter

    journal, seed = setup(tmp_path / "kernel")
    proposals = UnifiedCaller()
    run(journal, seed, proposals)
    context = next(context for stage, context in proposals.calls if stage == "synthesis")
    journal, seed = setup(tmp_path / "adapter")
    main(journal, "synthesis")
    model = adapter.NativeModelCaller(effective_config={"llm_provider": "deepseek", "quick_think_llm": "quick",
        "deep_think_llm": "deep"}, run_id=seed.run_id, ledger=journal.ledger,
        cancelled=lambda: False, deadline=lambda: time.monotonic() + 30)
    journal.put("native.binding_guidance.synthesis", 1)
    if alias_version is not None:
        journal.put("native.reference_aliases.synthesis", alias_version)
    old_prompt = model._prompt("synthesis", context)
    journal.put("native.prompt.synthesis", hashlib.sha256(old_prompt.encode()).hexdigest())
    prompts = []
    def invoke(prompt):
        prompts.append(prompt)
        return SimpleNamespace(content=json.dumps(proposals("synthesis", model._model_context("synthesis", context))))
    monkeypatch.setattr(adapter, "create_llm_client", lambda **_: SimpleNamespace(get_llm=lambda: SimpleNamespace(invoke=invoke)))
    model("synthesis", context)
    assert prompts == [old_prompt]
    assert journal.state.get("native.reference_aliases.synthesis") == alias_version
    assert "This applies to maintained replies too" not in old_prompt


class UnifiedCaller:
    def __init__(self, *, challenge=True, disposition="maintained", fail_reply=False, challenge_count=1, hypothesis_count=1):
        self.calls = []
        self.challenge_count, self.hypothesis_count = challenge_count, hypothesis_count
        self.challenge, self.disposition, self.fail_reply = challenge, disposition, fail_reply

    def __call__(self, stage, context):
        self.calls.append((stage, copy.deepcopy(context)))
        if stage in {"operating_quality", "event_context", "market_context"}:
            fact = next((f for f in context["facts"] if "收入" in f["statement"]), context["facts"][0])
            return {"hypotheses": [{"statement": "经营改善仍有条件", "supporting_fact_ids": [fact["claim_id"]],
                "conditions": [{"condition_role": "invalidation", "text": "下一期收入持续下降"}],
                "alternative_explanation": "一次性贡献"} for _ in range(self.hypothesis_count)]}
        if stage == "challenge":
            if not self.challenge:
                return {"challenges": []}
            return {"challenges": [{"hypothesis_id": h["hypothesis_id"], "statement": "持续性不足", "severity": "critical",
                "risk_type": "operations", "proposed_test": "下一期财报复核"}
                for h in context["record"]["hypotheses"][:self.challenge_count]]}
        if stage.startswith("response_"):
            if self.fail_reply:
                raise TimeoutError("offline reply unavailable")
            assert "record" not in context
            return {"responses": [{"challenge_id": cid, "hypothesis_id": hid, "disposition": self.disposition,
                "rationale": "承认尚有不确定性", "supporting_fact_ids": context["allowed_facts_by_challenge"][cid][:1]}
                for cid, hid in context["assigned"].items()]}
        record = context["record"]
        return {"judgement": "基于现有资料偏谨慎", "next_check": "下一期经营披露", "investment_stance": "unfavorable",
            "dimensions": [{"dimension": name, "status": "conditional" if context["dimension_claim_ids"][name] else "unresolved",
                "judgement": "有条件的判断", "claim_ids": context["dimension_claim_ids"][name][:1], "limitations": ["范围有限"]}
                for name in context["dimension_policy"]],
            "opposing_arguments": [{"rationale": "经营仍有待核查", "claim_ids": [record["claims"][0]["claim_id"]]}],
            "adjudications": [{"challenge_id": r["challenge_id"], "response_id": r["response_id"],
                "disposition": r["disposition"], "rationale": "保留该分歧，不把回复当作验证"} for r in record["dialogue"]["responses"]],
            "challenge_assessments": [{"challenge_id": c["challenge_id"], "rationale": "经济问题仍未解决"} for c in record["challenges"]]}


def setup(tmp_path, *, full=False):
    snapshot = RunSnapshot.create(ticker="600803", analysis_date="2026-10-05", metadata={
        "research_profile": "evidence_v1", "native_workflow_version": UNIFIED_WORKFLOW_VERSION})
    store = RunStore(tmp_path)
    store.create_run(snapshot)
    observer = DurableRunObserver(store, snapshot.run_id, development_assertions=False)
    identity = {"workflow_version": UNIFIED_WORKFLOW_VERSION, "focus_budget_policy": UNIFIED_BUDGET_POLICY,
                "ticker": snapshot.ticker, "mode": "company_research", "cutoff": snapshot.analysis_date}
    journal = CatalystJournal(observer, identity)
    draft, context = fixture()
    if full:
        from tests.test_native_record import fixture as native_fixture
        from tests.test_price_statistics_context import context as prices
        from tradingagents.research.price_statistics import build_price_statistics
        bars, provenance = prices(30)
        provenance["input_sha256"] = "a" * 64
        extra_draft, extra_context = native_fixture(extra=(("price_history", "tushare.adjusted_daily",
            {"bars":bars,"provenance":provenance,"computed_statistics":build_price_statistics(bars,provenance)},None),))
        extras = extra_draft.evidence[2:]
        draft = draft.model_copy(update={"evidence":(*draft.evidence,*extras),
            "capabilities":(*draft.capabilities,*[c for c in extra_draft.capabilities if c.capability in {"event_coverage", "price_history"}])})
        context.update({e["evidence_id"]:extra_context[e["evidence_id"]] for e in extras})
    payload = draft.model_dump(mode="json")
    payload["run_id"] = snapshot.run_id
    for evidence in payload["evidence"]:
        evidence["run_id"] = snapshot.run_id
        evidence["ticker"] = snapshot.ticker
    seed = build_native_record(type(draft).model_validate(payload), context, mode="company_research",
                               include_valuation=True, include_minimum=True)
    return journal, seed


def run(journal, seed, caller):
    return run_native_research(seed, caller=caller, ledger=journal.ledger, minimum=True,
                               valuation=True, scoped=True, independent=True, unified=True)


@pytest.mark.parametrize("disposition", ["maintained", "revised", "withdrawn"])
def test_one_targeted_reply_four_dimensions_and_durable_replay(tmp_path, disposition):
    journal, seed = setup(tmp_path)
    caller = UnifiedCaller(disposition=disposition)
    result = run(journal, seed, caller)
    assert [s for s, _ in caller.calls] == ["operating_quality", "challenge", "response_operating_quality", "synthesis"]
    assert [d.dimension for d in result.assessment.dimensions] == ["operating_quality", "valuation", "catalyst_delivery", "market_context"]
    assert result.dialogue.responses[0].disposition == disposition
    assert result.assessment.adjudications[0].response_id == result.dialogue.responses[0].response_id
    assert result.assessment.challenge_assessments[0].economic_outcome == "unresolved"
    assert result.assessment.forward_window_calendar_days is None
    restored = CatalystJournal(journal.observer, journal.state["identity"], require_existing=True)
    assert run(restored, seed, lambda *_: pytest.fail("must reuse saved stages")) == result
    assert restored.ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 4
    publish_native_record(journal.observer, record=result, ledger=journal.ledger,
                          publication_authorizer=lambda j: j.put("publication_authorized", True))


def test_zero_challenge_zero_reply_and_missing_reply_is_partial(tmp_path):
    journal, seed = setup(tmp_path / "zero")
    result = run(journal, seed, UnifiedCaller(challenge=False))
    assert not result.dialogue.responses and not result.assessment.adjudications
    assert journal.ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 3
    journal, seed = setup(tmp_path / "failure")
    result = run(journal, seed, UnifiedCaller(fail_reply=True))
    assert result.dialogue.responses[0].status == "unavailable"
    assert result.assessment.completeness == "partial" and result.assessment.quality == "LOW_CONFIDENCE"


def test_public_gates_reject_retracted_support_fake_conditions_and_favorable(tmp_path):
    journal, seed = setup(tmp_path)
    result = run(journal, seed, UnifiedCaller(disposition="withdrawn"))
    payload = result.model_dump(mode="json")
    inference = result.hypotheses[0].claim_id
    for update in ({"key_claim_ids": [inference]}, {"investment_stance": "favorable"},
                   {"change_conditions": [{"hypothesis_id": result.hypotheses[0].hypothesis_id,
                       "invalidation_index": 0, "text": "invented condition"}]}):
        with pytest.raises(ValidationError):
            ResearchRecordV1.model_validate({**payload, "assessment": {**payload["assessment"], **update}})
    assert "dialogue" not in seed.model_dump()


@pytest.mark.parametrize("full,hypothesis_count,reply_calls", [(False,3,1),(True,1,3)])
def test_multiple_challenges_share_one_reply_per_targeted_specialist(tmp_path,full,hypothesis_count,reply_calls):
    journal,seed=setup(tmp_path,full=full)
    caller=UnifiedCaller(challenge_count=3,hypothesis_count=hypothesis_count)
    result=run(journal,seed,caller)
    assert len(result.challenges)==len(result.dialogue.responses)==3
    calls=[(stage,context) for stage,context in caller.calls if stage.startswith("response_")]
    assert len(calls)==reply_calls
    for _stage,context in calls:
        assert "record" not in context and "research_question" not in context
        assert all(h["hypothesis_id"] in context["assigned"].values() for h in context["hypotheses"])
    assert journal.ledger.consumed(BudgetBucket.MAIN_ANALYSIS)==(8 if full else 4)


def test_published_v7_reader_markdown_and_absent_reply_roles_share_saved_record(tmp_path):
    from tradingagents.runtime.reports import build_markdown_from_native_record
    from tradingagents.web.reader_process_projection import (
        project_reader_agent,
        project_reader_process,
    )
    from tradingagents.web.research_record_projection import project_research_record
    journal,seed=setup(tmp_path)
    result=run(journal,seed,UnifiedCaller(disposition="revised"))
    publish_native_record(journal.observer,record=result,ledger=journal.ledger,
                          publication_authorizer=lambda j:j.put("publication_authorized",True))
    store,run_id=journal.observer.store,seed.run_id
    before=store.read_snapshot(run_id).latest_sequence
    assert project_research_record(store,run_id)["state"]=="ready"
    process=project_reader_process(store,run_id)
    assert process["availability"]=="ready",process
    reply=project_reader_agent(store,run_id,"response_operating_quality")
    assert reply["availability"]=="available",reply
    assert project_reader_agent(store,run_id,"response_event_context")["reason_code"]=="no_targeted_challenges_not_called"
    assert all(o["role_key"] not in {"response_operating_quality","response_event_context","response_market_context"} for o in process["claim_origins"])
    markdown=build_markdown_from_native_record(result,workflow_version=UNIFIED_WORKFLOW_VERSION)
    for text in (result.assessment.judgement,"投资吸引力判断","反对理由与反证","事件影响与兑现","专项回应：修正","综合裁决：修正",result.assessment.change_conditions[0].text):
        assert text in markdown
    assert store.read_snapshot(run_id).latest_sequence==before


def test_public_dimensions_and_synthesis_withdrawal_cannot_reuse_other_or_retracted_support(tmp_path):
    journal,seed=setup(tmp_path)
    result=run(journal,seed,UnifiedCaller())
    payload=result.model_dump(mode="json")
    inference=result.hypotheses[0].claim_id
    wrong=copy.deepcopy(payload)
    wrong["assessment"]["dimensions"][1]["claim_ids"]=[inference]
    with pytest.raises(ValidationError,match="unified dimension"):
        ResearchRecordV1.model_validate(wrong)
    withdrawn=copy.deepcopy(payload)
    withdrawn["assessment"]["adjudications"][0]["disposition"]="withdrawn"
    withdrawn["assessment"]["key_claim_ids"]=[inference]
    with pytest.raises(ValidationError):
        ResearchRecordV1.model_validate(withdrawn)


def test_sdk_v7_schema_validation_and_reply_effort_use_eight_shared_attempts(tmp_path, monkeypatch):
    import json

    from tests.test_native_model import CONFIG, caller, sdk
    journal,seed=setup(tmp_path,full=True)
    proposals=UnifiedCaller(challenge_count=3)
    def output():
        context,_=json.JSONDecoder().raw_decode(stub.prompts[-1].split("Saved research context:\n",1)[1])
        stage=("response_"+context["role"] if "assigned" in context else "synthesis" if context.get("record",{}).get("dialogue") is not None
               else "challenge" if "record" in context else context["view_scope"]["role"])
        return proposals(stage,context)
    stub,_=sdk(monkeypatch,[output]*8)
    config={**CONFIG,"deepseek_reasoning_effort":"high","deepseek_task_efforts":{
        "native.operating_quality":"low","native.event_context":"low","native.market_context":"low"}}
    model=caller(journal,effective_config=config)
    result=run_native_research(seed,caller=model,ledger=journal.ledger,minimum=True,valuation=True,
                               scoped=True,independent=True,unified=True,concurrency=1)
    assert len(result.dialogue.responses)==3 and all(r.status=="available" for r in result.dialogue.responses)
    assert journal.ledger.consumed(BudgetBucket.MAIN_ANALYSIS)==8
    assert journal.ledger.consumed(BudgetBucket.MODEL_ATTEMPTS)==8
    assert [factory["reasoning_effort"] for factory in stub.factories[4:7]]==["low"]*3
    assert stub.factories[-1]["reasoning_effort"]=="high"


def test_unknown_dispatched_reply_recovers_without_a_second_model_decision(tmp_path):
    class ProcessStopped(BaseException):
        pass
    class CrashReply(UnifiedCaller):
        def __call__(self,stage,context):
            if stage.startswith("response_"):
                raise ProcessStopped()
            return super().__call__(stage,context)
    journal,seed=setup(tmp_path)
    with pytest.raises(ProcessStopped):
        run(journal,seed,CrashReply())
    restored=CatalystJournal(journal.observer,journal.state["identity"],require_existing=True)
    caller=UnifiedCaller()
    result=run(restored,seed,caller)
    assert not any(stage.startswith("response_") for stage,_ in caller.calls)
    assert result.dialogue.responses[0].status=="unavailable"
    assert result.assessment.completeness=="partial"


def test_dialogue_cannot_enter_a_facts_only_seed(tmp_path):
    journal,seed=setup(tmp_path)
    payload=seed.model_dump(mode="json")
    payload["dialogue"]={"input_snapshot_id":seed.snapshots[0].snapshot_id}
    premature=ResearchRecordV1.model_validate(payload)
    with pytest.raises(ValueError,match="facts-only V0"):
        run(journal,premature,UnifiedCaller())
