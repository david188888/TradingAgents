"""Reject native local input defects before constructing an execution adapter."""

from dataclasses import replace

import pytest

from tradingagents.execution.models import AnalysisRequest, HoldingContext


def holding(thesis=None, facts_as_of="2026-07-18"):
    return HoldingContext(ticker="600519.SS", quantity=100, average_cost=1500,
        cash=None, total_account_value=None, currency=None, facts_as_of=facts_as_of,
        original_thesis=thesis, source="user_provided")


@pytest.mark.parametrize("thesis", ["x" * 4001, 10, False, [], {}])
def test_native_request_rejects_invalid_thesis_at_canonical_boundary(thesis):
    with pytest.raises(ValueError, match="native original_thesis"):
        AnalysisRequest("600519.SS", "2026-07-18", research_profile="evidence_v1",
            mode="holding_review", holding_context=holding(thesis))


def test_native_request_rejects_future_holding_facts_at_canonical_boundary():
    with pytest.raises(ValueError, match="facts_as_of cannot follow"):
        AnalysisRequest("600519.SS", "2026-07-18", research_profile="evidence_v1",
            mode="holding_review", holding_context=holding("原论点", "2026-07-19"))


def test_native_request_rejects_cross_security_holding_thesis():
    with pytest.raises(ValueError, match="holding ticker must match"):
        AnalysisRequest("600519.SS", "2026-07-18", research_profile="evidence_v1",
            mode="holding_review", holding_context=replace(holding("原论点"), ticker="000001.SZ"))


def test_native_request_accepts_equivalent_holding_security_symbols():
    request = AnalysisRequest("600519", "2026-07-18", research_profile="evidence_v1",
        mode="holding_review", holding_context=replace(holding("原论点"), ticker="600519.SH"))
    assert request.holding_context.original_thesis == "原论点"


@pytest.mark.parametrize("thesis", [None, "", "x" * 4000])
def test_native_thesis_boundary_and_earlier_facts_are_valid(thesis):
    request = AnalysisRequest("600519.SS", "2026-07-18", research_profile="evidence_v1",
        mode="holding_review", holding_context=holding(thesis, "2026-07-17"))
    assert request.holding_context.original_thesis == thesis


def test_classic_request_preserves_original_context_compatibility():
    context = holding("x" * 4001, "2026-07-19")
    request = AnalysisRequest("600519.SS", "2026-07-18", mode="holding_review", holding_context=context)
    assert request.holding_context is context
