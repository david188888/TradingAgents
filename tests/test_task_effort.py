"""Task payloads and isolation with fake invocations; no provider requests."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tradingagents.dataflows.config import config_scope
from tradingagents.default_config import DEFAULT_CONFIG, validate_config
from tradingagents.llm_clients.provider_kwargs import provider_llm_kwargs
from tradingagents.llm_clients.task_effort import (
    DEEPSEEK_EFFORT_TASKS,
    bind_task_effort,
)

CONFIG = {"llm_provider": "deepseek", "deepseek_thinking": "enabled",
          "deepseek_reasoning_effort": "high"}


@pytest.mark.parametrize("policy", [None, [], "low", {"synthesis": "low"},
                                    {"native.synthesis": "medium"},
                                    {"native.synthesis": True}, {"native.synthesis": "MAX"}])
def test_invalid_policy_is_rejected_before_payload_creation(policy):
    config = {**DEFAULT_CONFIG, "deepseek_task_efforts": policy}
    assert any("deepseek_task_efforts" in issue for issue in validate_config(config))
    with pytest.raises(ValueError, match="deepseek_task_efforts"):
        provider_llm_kwargs(config)


@pytest.mark.parametrize("task", sorted(DEEPSEEK_EFFORT_TASKS))
@pytest.mark.parametrize("effort", ["low", "high", "max"])
def test_every_registered_task_can_override_without_mutating_config(task, effort):
    config = {**CONFIG, "deepseek_task_efforts": {task: effort}}
    before = deepcopy(config)
    assert provider_llm_kwargs(config, task=task)["reasoning_effort"] == effort
    assert provider_llm_kwargs(config)["reasoning_effort"] == "high"
    assert config == before


def test_missing_policy_retains_legacy_payload_and_default_identity():
    assert "deepseek_task_efforts" not in DEFAULT_CONFIG
    assert provider_llm_kwargs(CONFIG, task="native.synthesis") == provider_llm_kwargs(CONFIG)
    config = {"llm_provider": "deepseek"}
    assert "reasoning_effort" not in provider_llm_kwargs(config)
    assert "reasoning_effort" not in provider_llm_kwargs({**config, "deepseek_task_efforts": {}})


def test_disabled_thinking_rejects_active_policy_and_other_provider_is_inert():
    config = {**CONFIG, "deepseek_thinking": "disabled", "deepseek_task_efforts": {"native.synthesis": "max"}}
    with pytest.raises(ValueError, match="disabled thinking"):
        provider_llm_kwargs(config, task="native.synthesis")
    config["llm_provider"] = "openai"
    assert "reasoning_effort" not in provider_llm_kwargs(config, task="native.synthesis")
    llm = object()
    assert bind_task_effort(llm, config, "aux.news_cluster") is llm


def test_real_deepseek_auxiliary_binding_payload_does_not_change_shared_client():
    from tradingagents.llm_clients.openai_client import OpenAIClient

    llm = OpenAIClient("deepseek-flash", provider="deepseek", api_key="offline-placeholder",
                       thinking={"type": "enabled"}, reasoning_effort="high").get_llm()
    config = {**CONFIG, "deepseek_task_efforts": {"aux.news_cluster": "low"}}
    bound = bind_task_effort(llm, config, "aux.news_cluster")
    assert llm._get_request_payload("JSON")["reasoning_effort"] == "high"
    payload = bound.bound._get_request_payload("JSON", **bound.kwargs)
    assert payload["reasoning_effort"] == "low"
    assert payload["extra_body"]["thinking"] == {"type": "enabled"}
    assert bind_task_effort(llm, CONFIG, "aux.news_cluster") is llm


class RecordingLlm:
    def __init__(self, response, calls=None, effort="high"):
        self.response, self.calls, self.effort = response, calls if calls is not None else [], effort

    def bind(self, *, reasoning_effort):
        return RecordingLlm(self.response, self.calls, reasoning_effort)

    def invoke(self, prompt):
        self.calls.append((self.effort, prompt))
        return SimpleNamespace(content=self.response)


def test_parallel_auxiliary_tasks_are_isolated_and_unlisted_task_inherits_high():
    llm = RecordingLlm("[]")
    config = {"llm_provider": "deepseek", "deepseek_task_efforts": {"aux.news_cluster": "low"}}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(lambda task=task: bind_task_effort(llm, config, task).invoke(task))
                   for task in ("aux.news_cluster", "aux.news_coverage")]
        for future in futures:
            future.result()
    assert sorted(llm.calls) == [("high", "aux.news_coverage"), ("low", "aux.news_cluster")]
    assert llm.effort == "high"


def test_clustering_and_news_advisor_bind_distinct_real_call_tasks():
    from tradingagents.dataflows.consistency import cluster_news_by_event
    from tradingagents.dataflows.news_advisor import analyze_news_coverage

    items = [{"title": "公司发布半年度业绩公告", "source": "a", "content": "半年营业收入披露"},
             {"title": "公司披露半年度营业收入", "source": "b", "content": "半年度业绩情况"}]
    config = {**CONFIG, "deepseek_task_efforts": {"aux.news_cluster": "low"}}
    cluster = RecordingLlm("[[0,1]]")
    advisor = RecordingLlm('{"should_enrich": false, "queries": [], "gaps": []}')
    with config_scope(config):
        assert cluster_news_by_event(items, cluster) == [[0, 1]]
        analyze_news_coverage(items, {"ticker": "600519", "name": "公司"}, advisor)
    assert [call[0] for call in cluster.calls] == ["low"]
    assert [call[0] for call in advisor.calls] == ["high"]


def test_bad_auxiliary_policy_never_falls_back_to_a_successful_heuristic():
    from tradingagents.dataflows.consistency import cluster_news_by_event, create_llm_from_config
    from tradingagents.dataflows.news_advisor import analyze_news_coverage

    with config_scope({**CONFIG, "deepseek_task_efforts": {"typo": "low"}}):
        for run in (lambda: create_llm_from_config(), lambda: cluster_news_by_event([]),
                    lambda: analyze_news_coverage([], {})):
            with pytest.raises(ValueError, match="unknown task"):
                run()


def test_news_layers_keep_independent_efforts_and_deep_cache_tracks_effort(tmp_path):
    from tradingagents.dataflows.news_advisor import analyze_news_coverage

    class Layered(RecordingLlm):
        def bind(self, *, reasoning_effort):
            return Layered("", self.calls, reasoning_effort)

        def invoke(self, prompt):
            self.calls.append((self.effort, prompt))
            if "Classify the market sentiment" in prompt:
                value = '[{"i":"a","s":"+","c":0.9}]'
            elif "This deeper review was requested" in prompt:
                value = '{"conclusion":"核验公告", "evidence_gaps":[], "material_risks":[], "source_ids":["a"]}'
            else:
                value = '{"should_enrich":true,"gaps":["经营兑现"],"queries":[]}'
            return SimpleNamespace(content=value)

    items = [{"id": "a", "title": "Company wins major order",
              "content": "Detailed public order announcement with financial implications."}]
    profile = {"name": "Company", "ticker": "000001.SZ", "data_as_of": "2026-10-04"}
    config = {**CONFIG, "news_layer1_enabled": True, "news_layer2_enabled": True,
              "news_layer2_cache_dir": str(tmp_path), "deepseek_task_efforts": {
                  "aux.news_sentiment": "low", "aux.news_coverage": "low", "aux.news_deep_review": "max"}}
    model = Layered("")
    with config_scope(config):
        first = analyze_news_coverage(items, profile, model)
        assert [effort for effort, _ in model.calls] == ["low", "low", "max"]
        second = analyze_news_coverage(items, profile, model)
        assert len(model.calls) == 5  # deep review is cached
        assert second.layer2_conclusion == first.layer2_conclusion
    config["deepseek_task_efforts"]["aux.news_deep_review"] = "high"
    with config_scope(config):
        third = analyze_news_coverage(items, profile, model)
    assert [effort for effort, _ in model.calls[-3:]] == ["low", "low", "high"]
    assert third.layer2_trigger.cache_key != first.layer2_trigger.cache_key
    model.calls.clear()
    config.update(news_layer1_enabled=False, news_layer2_enabled=False)
    with config_scope(config):
        analyze_news_coverage(items, profile, model)
    assert [effort for effort, _ in model.calls] == ["low"]


@pytest.mark.parametrize("role", ["catalyst_events", "operating_delivery", "market_reaction",
                                  "independent_refutation", "synthesis"])
def test_legacy_catalyst_caller_freezes_and_dispatches_role_effort(role, monkeypatch):
    from tradingagents.execution import catalyst_runner

    config = {**CONFIG, "quick_think_llm": "deepseek-flash", "deep_think_llm": "deepseek-flash",
              "deepseek_task_efforts": {"catalyst." + role: "max"}}
    payloads = []

    def factory(**kwargs):
        payloads.append(kwargs)
        return SimpleNamespace(get_llm=lambda: RecordingLlm("{}"))

    monkeypatch.setattr(catalyst_runner, "create_llm_client", factory)
    caller = catalyst_runner.ProductionModelCaller(SimpleNamespace(effective_config=config),
                                                    None, None, None, lambda: None, lambda: 30)
    config["deepseek_task_efforts"]["catalyst." + role] = "low"
    caller._invoke(role, "offline")
    assert payloads[0]["reasoning_effort"] == "max"
    assert payloads[0]["max_retries"] == 0


def test_classic_graph_routes_role_and_compaction_clients_without_invoke(tmp_path, monkeypatch):
    from tradingagents.graph import setup, trading_graph

    factories, roles = [], {}

    def factory(**kwargs):
        llm = MagicMock(name="offline_llm")
        factories.append((kwargs, llm))
        return SimpleNamespace(get_llm=lambda: llm)

    def analyst(role):
        def create(llm, **kwargs):
            roles[role] = llm
            return lambda state: {}
        return create

    for role, name in {"market": "create_market_analyst", "social": "create_sentiment_analyst",
                       "news": "create_news_analyst", "fundamentals": "create_fundamentals_analyst",
                       "bull": "create_bull_researcher", "bear": "create_bear_researcher",
                       "research_manager": "create_research_manager"}.items():
        monkeypatch.setattr(setup, name, analyst(role))
    monkeypatch.setattr(trading_graph, "create_llm_client", factory)
    monkeypatch.setattr(trading_graph, "TradingMemoryLog", lambda config: MagicMock())
    config = {**DEFAULT_CONFIG, "data_cache_dir": str(tmp_path / "cache"),
              "results_dir": str(tmp_path / "results"), "deepseek_task_efforts": {
                  "classic.social": "low", "classic.research_manager": "max",
                  "aux.context_compaction": "low"}}
    with config_scope(config):
        graph = trading_graph.TradingAgentsGraph(config=config)
    assert len(factories) == 5  # global quick/deep + exactly three overrides
    payloads = {id(llm): kwargs for kwargs, llm in factories}
    assert payloads[id(roles["social"])]["reasoning_effort"] == "low"
    assert payloads[id(roles["research_manager"])]["reasoning_effort"] == "max"
    for role in ("market", "news", "fundamentals", "bull", "bear"):
        assert roles[role] is graph.quick_thinking_llm
    assert payloads[id(graph.graph_setup._llm_for("context_compaction"))]["reasoning_effort"] == "low"
    config["deepseek_task_efforts"]["classic.social"] = "max"
    assert graph.config["deepseek_task_efforts"]["classic.social"] == "low"
    for _, llm in factories:
        llm.invoke.assert_not_called()
