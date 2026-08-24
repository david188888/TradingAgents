from datetime import date, datetime, timezone
from types import SimpleNamespace

from tradingagents.research.metric_provider_adapter import (
    observations_from_fundamentals_bundle,
)
from tradingagents.research.public_hash import package_sha256
from tradingagents.research.research_package import research_package_from_case

RUN_ID = "run_20260815T082000000000Z_ab12cd34"


def _bundle():
    return {
        "ticker": "600519.SS",
        "results": [
            {
                "capability": "fundamentals_annual",
                "frequency": "annual",
                "statements": [
                    {
                        "statement": "income_statement",
                        "status": "ok",
                        "source_id": "tushare.tushare_get_income_statement",
                        "data": "# Monetary raw unit: CNY\n# Monetary normalization formula: raw_value / 100000000\n# report\nts_code,ann_date,end_date,revenue,n_income_attr_p,gross_profit\n600519.SH,2025-04-01,2024-12-31,1000000000,200000000,400000000\n600519.SH,2024-04-01,2023-12-31,800000000,160000000,320000000\n",
                    },
                    {
                        "statement": "cash_flow",
                        "status": "ok",
                        "source_id": "tushare.tushare_get_cashflow",
                        "data": "# Monetary raw unit: CNY\n# Monetary normalization formula: raw_value / 100000000\nts_code,ann_date,end_date,n_cashflow_act\n600519.SH,2025-04-01,2024-12-31,250000000\n",
                    },
                    {
                        "statement": "balance_sheet",
                        "status": "ok",
                        "source_id": "tushare.tushare_get_balance_sheet",
                        "data": "# Monetary raw unit: CNY\n# Monetary normalization formula: raw_value / 100000000\nts_code,ann_date,end_date,total_assets,total_liab,total_hldr_eqy_exc_min_int\n600519.SH,2025-04-01,2024-12-31,5000000000,2000000000,3000000000\n",
                    },
                ],
            }
        ],
    }


def test_adapter_accepts_explicit_tushare_fields_and_normalizes_units():
    observations = observations_from_fundamentals_bundle(
        _bundle(),
        run_id=RUN_ID,
        entity_id="600519.SS",
        analysis_cutoff=date(2025, 12, 31),
        evidence_ref_id="evidence-1",
    )
    by_key = {(item.metric_id, item.period): item for item in observations}
    assert by_key[("revenue", "2024-12-31")].value == 10
    assert by_key[("net_income", "2024-12-31")].value == 2
    assert by_key[("operating_cash_flow", "2024-12-31")].value == 2.5
    assert by_key[("total_assets", "2024-12-31")].value == 50
    assert by_key[("equity", "2024-12-31")].value == 30
    assert by_key[("revenue", "2024-12-31")].unit == "CNY_100m"


def test_adapter_withholds_rows_without_filing_date():
    bundle = _bundle()
    for statement in bundle["results"][0]["statements"]:
        statement["data"] = (
            "ts_code,end_date,revenue,n_income_attr_p,gross_profit\n"
            "600519.SH,2024-12-31,1000000000,200000000,400000000\n"
            "600519.SH,2025-12-31,1100000000,220000000,440000000\n"
        )
    assert observations_from_fundamentals_bundle(
        bundle,
        run_id=RUN_ID,
        entity_id="600519.SS",
        analysis_cutoff=date(2025, 12, 31),
        evidence_ref_id="evidence-1",
    ) == ()


def test_adapter_discards_rows_from_another_ticker():
    bundle = _bundle()
    bundle["results"][0]["statements"][0]["data"] = (
        "# Monetary raw unit: CNY\n"
        "# Monetary normalization formula: raw_value / 100000000\n"
        "ts_code,ann_date,end_date,revenue,n_income_attr_p,gross_profit\n"
        "000001.SZ,2025-04-01,2024-12-31,999000000000,200000000,400000000\n"
    )
    observations = observations_from_fundamentals_bundle(
        bundle,
        run_id=RUN_ID,
        entity_id="600519.SS",
        analysis_cutoff=date(2025, 12, 31),
        evidence_ref_id="evidence-1",
    )
    assert not any(item.metric_id == "revenue" for item in observations)

    bundle = _bundle()
    bundle_hash = package_sha256(bundle)
    case = SimpleNamespace(
        run_id=RUN_ID,
        ticker="600519.SS",
        as_of=datetime(2025, 8, 15, tzinfo=timezone.utc),
        evidence_refs=(
            SimpleNamespace(
                ref_id=bundle_hash,
                run_id=RUN_ID,
                artifact_id="evidence-bundle:fundamentals",
                resolution_status="available",
            ),
        ),
    )
    package = research_package_from_case(
        case,
        analysis_cutoff=date(2025, 12, 31),
        fundamentals_bundle=bundle,
    )
    assert package.observations
    assert any(item.metric_id == "net_margin" for item in package.observations)
    assert any(item.metric_id == "revenue_yoy" for item in package.observations)
    assert "metrics.structured_observations_unavailable" not in package.unknowns
