"""Local-only guard for the dataflow static registry.

Kept out of the public repo like the rest of tests/. A broken registry must
fail here before it can silently change category lookup or fallback routing.
"""

from tradingagents.dataflows.registry import (
    VENDOR_METHODS,
    get_category_for_method,
    get_vendor,
    registry_consistency_problems,
    validate_data_vendors,
)
from tradingagents.default_config import DEFAULT_CONFIG


def test_registry_is_internally_consistent():
    assert registry_consistency_problems() == []


def test_default_vendor_config_is_valid():
    assert validate_data_vendors(DEFAULT_CONFIG) == []


def test_unknown_vendor_in_category_is_detected():
    problems = validate_data_vendors({"data_vendors": {"core_stock_apis": "bogus_vendor"}})
    assert any("bogus_vendor" in problem for problem in problems)


def test_unknown_method_in_tool_vendors_is_detected():
    problems = validate_data_vendors({"tool_vendors": {"get_bogus_method": "tushare"}})
    assert any("get_bogus_method" in problem for problem in problems)


def test_known_method_vendor_pair_is_accepted():
    method = next(iter(VENDOR_METHODS))
    vendor = next(iter(VENDOR_METHODS[method]))
    problems = validate_data_vendors({"tool_vendors": {method: vendor}})
    assert problems == []


def test_interactive_qa_defaults_to_its_only_executable_vendor():
    method = "get_a_share_interactive_questions"

    assert get_category_for_method(method) == "a_share_specialty_data"
    assert get_vendor("a_share_specialty_data", method) == "akshare"
    assert tuple(VENDOR_METHODS[method]) == ("akshare",)
