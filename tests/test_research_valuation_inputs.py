"""Tests for parsing committed bundles into typed valuation inputs."""

from __future__ import annotations

from datetime import date

from tradingagents.research.valuation import ValuationInputsV1
from tradingagents.research.valuation_inputs import parse_valuation_inputs

CUTOFF = date(2026, 8, 20)


def _valuation_bundle_ok() -> dict:
    snapshot_csv = (
        "# China A-share realtime valuation for 600519.SH\n"
        "# Source: tencent\n"
        "# Data retrieved on: 2026-08-20 14:00:00\n"
        "\n"
        "Code,Name,Price,Last Close,Change %,Amount (wan),Turnover %,PE TTM,"
        "Float Cap (yi),Market Cap (yi),PB,Limit Up,Limit Down,Is Stale,Stale Reason\n"
        '600519,贵州茅台,1500.0,1490.0,0.67,1234567.0,0.8,22.0,16600.0,18800.0,7.5,1650.0,1350.0,False,\n'
    )
    history_csv = (
        "date,code,close,peTTM,pbMRQ,psTTM,pcfNcfTTM,turn,tradestatus,isST\n"
        "2023-08-20,sh600519,1800.0,30.0,9.0,15.0,25.0,0.5,1,0\n"
        "2024-08-20,sh600519,1400.0,18.5,6.2,10.0,15.0,0.4,1,0\n"
        "2025-08-20,sh600519,1450.0,21.0,7.0,11.0,16.0,0.4,1,0\n"
        "2026-08-19,sh600519,1500.0,,7.5,12.0,17.0,0.4,1,0\n"  # missing PE dropped
    )
    return {
        "schema_version": 1,
        "ticker": "600519.SH",
        "as_of": CUTOFF.isoformat(),
        "status": "ok",
        "results": [
            {"capability": "valuation_snapshot", "route_method": "get_a_share_valuation", "status": "ok", "data": snapshot_csv},
            {"capability": "valuation_history", "route_method": "get_a_share_valuation_history", "status": "ok", "data": history_csv},
        ],
    }


def _adjusted_bundle() -> dict:
    csv_text = (
        "# Price basis: qfq\n# Adjustment source: test\n"
        "Date,Open,High,Low,Close,Volume\n"
        "2025-09-01,100.0,102.0,99.0,101.0,1000\n"
        "2025-09-02,101.0,103.0,100.0,102.0,1100\n"
    )
    return {
        "adjusted": {
            "status": "ok",
            "coverage": {"completeness": "complete"},
            "data": csv_text,
        },
        "quote_snapshot": {
            "status": "available",
            "market_price": 1500.0,
            "price_as_of": "2026-08-20",
        },
    }


def _fundamentals_bundle() -> dict:
    return {
        "ticker": "600519.SH",
        "results": [
            {
                "capability": "fundamentals_annual",
                "frequency": "annual",
                "statements": [
                    {
                        "statement": "income_statement",
                        "status": "ok",
                        "source_id": "tushare.tushare_get_income_statement",
                        "data": (
                            "# Monetary raw unit: CNY\n"
                            "# Monetary normalization formula: raw_value / 100000000\n"
                            "# report\n"
                            "ts_code,ann_date,end_date,revenue,n_income_attr_p,gross_profit\n"
                            "600519.SH,2026-04-01,2025-12-31,100000000000,86200000000,50000000000\n"
                        ),
                    },
                    {
                        "statement": "balance_sheet",
                        "status": "ok",
                        "source_id": "tushare.tushare_get_balance_sheet",
                        "data": (
                            "# Monetary raw unit: CNY\n"
                            "# Monetary normalization formula: raw_value / 100000000\n"
                            "ts_code,ann_date,end_date,total_assets,total_liab,total_hldr_eqy_exc_min_int\n"
                            "600519.SH,2026-04-01,2025-12-31,300000000000,120000000000,175000000000\n"
                        ),
                    },
                ],
            }
        ],
    }


def test_parse_full_bundles_produces_typed_inputs() -> None:
    inputs = parse_valuation_inputs(
        run_id="run-test-2",
        ticker="600519.SH",
        analysis_cutoff=CUTOFF,
        valuation_bundle=_valuation_bundle_ok(),
        adjusted_price_bundle=_adjusted_bundle(),
        fundamentals_bundle=_fundamentals_bundle(),
    )
    assert isinstance(inputs, ValuationInputsV1)
    assert inputs.snapshot is not None
    assert inputs.snapshot.price == 1500.0
    assert inputs.snapshot.pe_ttm == 22.0
    assert inputs.snapshot.pb == 7.5
    assert inputs.snapshot.total_market_cap_yi == 18800.0

    assert [item.value for item in inputs.pe_history] == [30.0, 18.5, 21.0]
    assert len(inputs.pb_history) == 4

    net = inputs.net_income_annual
    assert net is not None and net.metric_id == "net_income"
    assert net.value_yi == 862.0 and net.period == "2025-12-31"
    equity = inputs.equity_annual
    assert equity is not None and equity.value_yi == 1750.0


def test_missing_bundles_degrade_without_crash() -> None:
    inputs = parse_valuation_inputs(
        run_id="run-test-2",
        ticker="600519.SH",
        analysis_cutoff=CUTOFF,
        valuation_bundle=None,
        adjusted_price_bundle=None,
        fundamentals_bundle=None,
    )
    assert inputs is None or all(
        item is None for item in (inputs.snapshot, inputs.net_income_annual)
    )


def test_unavailable_capability_rows_are_skipped() -> None:
    bundle = _valuation_bundle_ok()
    bundle["results"][0]["status"] = "unavailable"
    bundle["results"][0].pop("data")
    inputs = parse_valuation_inputs(
        run_id="run-test-2",
        ticker="600519.SH",
        analysis_cutoff=CUTOFF,
        valuation_bundle=bundle,
        adjusted_price_bundle=None,
        fundamentals_bundle=None,
    )
    assert inputs is not None and inputs.snapshot is None
    assert inputs.pe_history  # history capability still parsed


def test_wind_kline_time_match_columns_are_parsed() -> None:
    """Wind get_stock_kline renders TIME/MATCH columns; closes must survive."""
    csv_text = (
        "# Adjusted stock data for 600519.SH from 2025-08-13 to 2026-08-27\n"
        "# Source: wind (stock_data.get_stock_kline, skill 2.0.1)\n"
        "# Price basis: qfq\n"
        "\n"
        "TIME,OPEN,MATCH,HIGH,LOW,TURNOVER,VOLUME,CHANGEHANDRATE,AVPRICE\n"
        "2025-08-13T00:00:00.000+08:00,20.84,21.64,22.02,20.6,927574874,35797327,11.4011,21.39\n"
        "2025-08-14T00:00:00.000+08:00,21.5,21.1,21.8,21.0,800000000,32000000,9.8,21.3\n"
    )
    bundle = {
        "adjusted": {
            "status": "ok",
            "coverage": {"completeness": "complete"},
            "data": csv_text,
        },
        "quote_snapshot": {
            "status": "available",
            "market_price": 1500.0,
            "price_as_of": "2026-08-20",
        },
    }
    inputs = parse_valuation_inputs(
        run_id="run-test-3",
        ticker="600519.SH",
        analysis_cutoff=CUTOFF,
        valuation_bundle=None,
        adjusted_price_bundle=bundle,
        fundamentals_bundle=None,
    )
    assert inputs is not None
    assert [(day.isoformat(), value) for day, value in inputs.closing_prices] == [
        ("2025-08-13", 21.64),
        ("2025-08-14", 21.1),
    ]
    # The verified quote bounds the price window and supplies the anchor price.
    assert inputs.snapshot is None
