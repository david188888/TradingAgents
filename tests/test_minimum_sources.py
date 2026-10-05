"""Optional V5 branches retain qualified inputs under shared controls."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from tests.test_minimum_evidence import documents, forecast
from tradingagents.dataflows.minimum_sources import MinimumEvidenceSources
from tradingagents.execution.budget import BudgetBucket, BudgetLedger
from tradingagents.execution.models import AnalysisCancelled
from tradingagents.research.catalyst_evidence_policy import catalyst_evidence_policy_v1
from tradingagents.research.evidence_freeze import CapabilityStatus, FreezeInputs
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict


def inputs():
    return FreezeInputs("bounded", "600803", datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(), catalyst_evidence_policy_v1())


def sources(fetch, config=None):
    return MinimumEvidenceSources(SimpleNamespace(effective_config=config or {}, ticker="600803"), "bounded", None, fetch)


def test_zero_remaining_optional_budget_preserves_existing_evidence():
    ledger = BudgetLedger("bounded", limits={BudgetBucket.DATA_CAPABILITY_CALLS: 0})
    def fetch(key, operation):
        ledger.reserve_or_raise(BudgetBucket.DATA_CAPABILITY_CALLS, stage="optional", logical_call_id=key)
        pytest.fail("exhausted budget dispatched an operation")
    collector, frozen = sources(fetch), inputs()
    collector.context = {"report": {"Title": "新奥股份2026年半年度报告", "Published": "2026-08-29", "Announcement ID": "1225526373"}}
    collector.evidence(frozen, "fundamentals", "sina.financial_statements", {"saved": True})
    before = frozen.evidence.copy()
    collector.last_session = "2026-09-30"
    collector._documents(frozen, "600803.SH", {"name": "新奥股份"})
    collector._valuation(frozen, "600803.SH", {"name": "新奥股份"})
    collector._forecasts(frozen, "600803.SH", {"name": "新奥股份"})
    assert frozen.evidence == before
    assert all(c.status == CapabilityStatus.UNAVAILABLE for c in frozen.capabilities)
    assert ledger.consumed(BudgetBucket.DATA_HTTP_ATTEMPTS) == 0


@pytest.mark.parametrize("error", [AnalysisCancelled("cancelled"), TimeoutError("deadline"), CatalystCheckpointConflict("response unknown")])
def test_optional_branch_never_converts_run_control_failure_to_provider_fallback(error):
    calls = []
    def fetch(key, operation):
        calls.append(key)
        raise error
    collector = sources(fetch)
    with pytest.raises(type(error)):
        collector._forecasts(inputs(), "600803.SH", {"name": "新奥股份"})
    assert len(calls) == 1


def test_optional_feed_stops_after_one_adequate_dated_source_and_respects_exclusions(monkeypatch):
    calls = []
    collector = sources(lambda key, operation: (calls.append(key), [forecast()])[1])
    frozen = inputs()
    collector._forecasts(frozen, "600803.SH", {"name": "新奥股份"})
    assert len(calls) == 1 and calls[0].endswith("ths")
    assert len(frozen.evidence) == 1
    config = {"evidence_source_exclusions": ["ths", "eastmoney"], "evidence_source_vendors": {"forecasts": ["ths", "eastmoney"]}}
    collector = sources(lambda *_: pytest.fail("excluded source dispatched"), config)
    collector._forecasts(inputs(), "600803.SH", {"name": "新奥股份"})
    assert config["evidence_source_exclusions"] == ["ths", "eastmoney"]


def test_actual_prefixed_report_uses_v2_durable_key_and_partial_body(monkeypatch):
    calls = []
    collector = sources(lambda key, operation: (calls.append(key), operation())[1])
    collector.context = {"report": {"Title": "新奥股份2026年半年度报告", "Published": "2026-08-29", "Announcement ID": "1225526373"}}
    monkeypatch.setattr(collector, "_document_get", lambda *_: documents()[0])
    frozen = inputs()
    collector._documents(frozen, "600803.SH", {"name": "新奥股份"})
    assert calls == ["native-public-sources-v1.document.v5.1225526373"]
    assert any(e["source_name"] == "cninfo.numeric_row.v2" for e in frozen.evidence)
    assert all(e["source_tier"] == "official" for e in frozen.evidence)
    assert next(c for c in frozen.capabilities if c.capability == "announcement_bodies").status == CapabilityStatus.PARTIAL


@pytest.mark.parametrize("config", [{"evidence_source_vendors": []}, {"evidence_source_vendors": {"forecasts": ["yahoo"]}},
    {"evidence_source_vendors": {"peers": ["eastmoney", "eastmoney"]}}, {"evidence_source_exclusions": "ths"}])
def test_invalid_supplemental_configuration_rejects_before_transport(config):
    with pytest.raises(ValueError, match="invalid_native_source_configuration"):
        sources(lambda *_: pytest.fail("invalid config dispatched"), config)
