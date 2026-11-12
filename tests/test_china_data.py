import sys
import types

import pandas as pd

from tradingagents.dataflows.china_data import (
    get_stock_tushare,
)
from tradingagents.dataflows.config import set_config


def test_get_stock_tushare_formats_daily_data_and_logs_raw(monkeypatch, tmp_path):
    calls = {}

    class FakePro:
        def daily(self, **kwargs):
            calls["daily"] = kwargs
            return pd.DataFrame(
                [
                    {
                        "ts_code": "002636.SZ",
                        "trade_date": "20260105",
                        "open": 10.0,
                        "high": 10.5,
                        "low": 9.8,
                        "close": 10.2,
                        "pre_close": 10.0,
                        "change": 0.2,
                        "pct_chg": 2.0,
                        "vol": 1000,
                        "amount": 2000,
                    }
                ]
            )

    fake_tushare = types.SimpleNamespace(
        set_token=lambda token: calls.setdefault("token", token),
        pro_api=lambda token: FakePro(),
    )

    monkeypatch.setitem(sys.modules, "tushare", fake_tushare)
    monkeypatch.setenv("TUSHARE_TOKEN", "token-test")
    set_config({"results_dir": str(tmp_path)})

    result = get_stock_tushare("002636", "2026-01-01", "2026-01-31")

    assert calls["daily"]["ts_code"] == "002636.SZ"
    assert calls["daily"]["start_date"] == "20260101"
    assert "Source: tushare" in result
    assert "2026-01-05" in result
    raw_files = list((tmp_path / "002636" / "2026-01-31" / "data").glob("tushare_get_stock_*.json"))
    assert len(raw_files) == 1
