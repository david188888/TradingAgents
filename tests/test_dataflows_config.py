"""Config isolation: get/set must not leak nested-dict references."""

import copy
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

import pytest

import tradingagents.default_config as default_config
from tradingagents.dataflows.config import (
    config_scope,
    get_config,
    merge_config,
    set_config,
)


@pytest.mark.unit
class DataflowsConfigIsolationTests(unittest.TestCase):
    def setUp(self):
        set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))

    def test_get_config_returns_deep_copy(self):
        cfg = get_config()
        cfg["data_vendors"]["core_stock_apis"] = "alpha_vantage"
        cfg["tool_vendors"]["get_stock_data"] = "alpha_vantage"

        fresh = get_config()
        self.assertEqual(
            fresh["data_vendors"]["core_stock_apis"],
            default_config.DEFAULT_CONFIG["data_vendors"]["core_stock_apis"],
        )
        self.assertNotIn("get_stock_data", fresh["tool_vendors"])

    def test_set_config_does_not_alias_caller_nested_dicts(self):
        custom = copy.deepcopy(default_config.DEFAULT_CONFIG)
        custom["data_vendors"]["core_stock_apis"] = "alpha_vantage"
        custom["tool_vendors"]["get_stock_data"] = "alpha_vantage"

        set_config(custom)

        custom["data_vendors"]["core_stock_apis"] = "yfinance"
        custom["tool_vendors"]["get_stock_data"] = "yfinance"

        fresh = get_config()
        self.assertEqual(fresh["data_vendors"]["core_stock_apis"], "alpha_vantage")
        self.assertEqual(fresh["tool_vendors"]["get_stock_data"], "alpha_vantage")

    def test_partial_nested_update_preserves_existing_defaults(self):
        set_config(
            {
                "data_vendors": {
                    "core_stock_apis": "alpha_vantage",
                }
            }
        )

        fresh = get_config()
        self.assertEqual(fresh["data_vendors"]["core_stock_apis"], "alpha_vantage")
        self.assertEqual(
            fresh["data_vendors"]["technical_indicators"],
            default_config.DEFAULT_CONFIG["data_vendors"]["technical_indicators"],
        )
        self.assertEqual(
            fresh["data_vendors"]["fundamental_data"],
            default_config.DEFAULT_CONFIG["data_vendors"]["fundamental_data"],
        )
        self.assertEqual(
            fresh["data_vendors"]["news_data"],
            default_config.DEFAULT_CONFIG["data_vendors"]["news_data"],
        )

    def test_nested_dict_updates_merge_one_level_deep(self):
        set_config({"tool_vendors": {"get_stock_data": "alpha_vantage"}})
        set_config({"tool_vendors": {"get_news": "alpha_vantage"}})

        fresh = get_config()
        self.assertEqual(fresh["tool_vendors"]["get_stock_data"], "alpha_vantage")
        self.assertEqual(fresh["tool_vendors"]["get_news"], "alpha_vantage")

    def test_concurrent_run_scopes_do_not_leak_config(self):
        barrier = threading.Barrier(2)
        original = get_config()

        def read_scoped_config(marker):
            run_config = copy.deepcopy(default_config.DEFAULT_CONFIG)
            run_config["run_marker"] = marker
            with config_scope(run_config):
                # Graph construction can call set_config; it must update only
                # this worker's scoped value, not the process-wide fallback.
                set_config({"run_marker": f"{marker}-updated"})
                barrier.wait(timeout=5)
                return get_config()["run_marker"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(read_scoped_config, ("first", "second")))

        self.assertEqual(results, ["first-updated", "second-updated"])
        self.assertEqual(get_config(), original)

    def test_partial_graph_config_inherits_defaults(self):
        merged = merge_config({"run_marker": "scoped"})

        self.assertEqual(merged["run_marker"], "scoped")
        self.assertIn("data_vendors", merged)
        self.assertEqual(get_config(), default_config.DEFAULT_CONFIG)

    def test_scoped_config_reaches_langgraph_tool_calls(self):
        from langchain_core.messages import AIMessage
        from langchain_core.tools import tool
        from langgraph.graph import END, START, MessagesState, StateGraph
        from langgraph.prebuilt import ToolNode

        @tool
        def probe() -> str:
            """Read a value bound to the current analysis run."""
            return get_config()["run_marker"]

        def call_tool(_state):
            return {
                "messages": [
                    AIMessage(
                        "",
                        tool_calls=[{"name": "probe", "args": {}, "id": "probe-1"}],
                    )
                ]
            }

        graph = StateGraph(MessagesState)
        graph.add_node("call", call_tool)
        graph.add_node("tools", ToolNode([probe]))
        graph.add_edge(START, "call")
        graph.add_edge("call", "tools")
        graph.add_edge("tools", END)

        run_config = copy.deepcopy(default_config.DEFAULT_CONFIG)
        run_config["run_marker"] = "scoped"
        with config_scope(run_config):
            result = graph.compile().invoke({"messages": [("user", "probe")]})

        self.assertEqual(result["messages"][-1].content, "scoped")
