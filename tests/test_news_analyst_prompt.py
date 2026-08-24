"""Guard deterministic company-news prefetch and analyst tool visibility."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import Runnable

import tradingagents.agents.analysts.news_analyst as na
from tradingagents.agents.utils.news_data_tools import get_news
from tradingagents.graph.trading_graph import TradingAgentsGraph


@pytest.mark.unit
def test_get_news_takes_ticker_not_query():
    arg_names = set(get_news.args.keys())
    assert "ticker" in arg_names
    assert "query" not in arg_names


@pytest.mark.unit
def test_news_analyst_exposes_only_macro_supplement_tools(monkeypatch):
    class RecordingLLM(Runnable):
        bound_tools = ()
        prompt_messages = ()

        def bind_tools(self, tools):
            self.bound_tools = tuple(tool.name for tool in tools)
            return self

        def invoke(self, _input, config=None, **kwargs):
            self.prompt_messages = tuple(_input.messages)
            return AIMessage(content="draft", tool_calls=[])

    monkeypatch.setattr(na, "emit_methodology_artifact", lambda *_a, **_k: None)
    monkeypatch.setattr(na, "finalize_role_report", lambda *_a, **_k: ("draft", None))
    llm = RecordingLLM()
    node = na.create_news_analyst(llm)

    node(
        {
            "trade_date": "2026-07-31",
            "company_of_interest": "000338.SZ",
            "messages": [HumanMessage(content="analyze")],
            "horizon": "long",
            "news_window_bundle": '{"horizon":"long"}',
            "a_share_supplement_bundle": '{"cls_telegraph":{"status":"ok"}}',
        }
    )

    assert llm.bound_tools == (
        "get_global_news",
        "get_macro_indicators",
        "search_macro_series",
        "get_macro_series",
    )
    system_messages = [
        message.content
        for message in llm.prompt_messages
        if message.type == "system"
    ]
    assistant_messages = [
        message.content
        for message in llm.prompt_messages
        if message.type == "ai"
    ]
    assert '{"horizon":"long"}' not in "\n".join(system_messages)
    assert '{"horizon":"long"}' in "\n".join(assistant_messages)
    assert '{"cls_telegraph":{"status":"ok"}}' not in "\n".join(system_messages)
    assert '{"cls_telegraph":{"status":"ok"}}' in "\n".join(assistant_messages)


@pytest.mark.unit
def test_news_tool_executor_respects_wind_feature_flag():
    disabled = TradingAgentsGraph._create_tool_nodes(
        type("Config", (), {"config": {"wind_enabled": False}})()
    )["news"]
    enabled = TradingAgentsGraph._create_tool_nodes(
        type("Config", (), {"config": {"wind_enabled": True}})()
    )["news"]

    assert set(disabled.tools_by_name) == {
        "get_global_news",
        "get_macro_indicators",
    }
    assert set(enabled.tools_by_name) == {
        "get_global_news",
        "get_macro_indicators",
        "search_macro_series",
        "get_macro_series",
    }
