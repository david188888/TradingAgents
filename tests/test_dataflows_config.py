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
        set_config({"evidence_source_vendors": {"financial": ["sina"]}})
        cfg = get_config()
        cfg["evidence_source_vendors"]["financial"].append("tushare")

        self.assertEqual(get_config()["evidence_source_vendors"], {"financial": ["sina"]})

    def test_set_config_does_not_alias_caller_nested_dicts(self):
        custom = {"evidence_source_vendors": {"financial": ["sina"]}}
        set_config(custom)
        custom["evidence_source_vendors"]["financial"].append("tushare")

        self.assertEqual(get_config()["evidence_source_vendors"], {"financial": ["sina"]})

    def test_nested_dict_updates_preserve_other_keys_and_replace_lists(self):
        set_config({"evidence_source_vendors": {"identity": ["eastmoney"], "financial": ["sina"]}})
        set_config({"evidence_source_vendors": {"financial": ["tushare"]}})

        self.assertEqual(get_config()["evidence_source_vendors"],
                         {"identity": ["eastmoney"], "financial": ["tushare"]})

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

    def test_partial_config_inherits_defaults(self):
        merged = merge_config({"run_marker": "scoped"})

        self.assertEqual(merged["run_marker"], "scoped")
        self.assertEqual(merged["wind_enabled"], default_config.DEFAULT_CONFIG["wind_enabled"])
        self.assertEqual(get_config(), default_config.DEFAULT_CONFIG)
