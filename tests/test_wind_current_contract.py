"""Current CLI response/route contracts independent of obsolete fixtures."""

import json
from unittest.mock import Mock

import pytest

from tradingagents.dataflows import wind_provider as provider
from tradingagents.dataflows.config import config_scope


@pytest.mark.parametrize("code,exception", [
    ("AUTH_ERROR", provider.WindAuthError),
    ("RATE_LIMIT_ERROR", provider.WindRateLimitError),
    ("ROUTE_ERROR", provider.WindParamError),
])
def test_flat_cli_failures_keep_their_error_class(code, exception):
    raw = json.dumps({"ok": False, "code": code, "message": "safe test message"})
    with pytest.raises(exception):
        provider._parse_envelope(raw, "stock_data", "get_stock_kline")
    error = provider._classify_cli_error(raw, "", "stock_data", "get_stock_kline")
    assert isinstance(error, exception)
    assert error.code == code


def test_current_edb_search_and_query_keep_metadata_and_dates(monkeypatch):
    metadata = {"code": "M0001395", "name": "GDP", "freq": "年", "unit": "亿元", "source": "国家统计局"}
    transport = Mock()
    transport.call.side_effect = [
        provider.WindEnvelope(False, "economic_data", "search_economic_indicator", {"data": {"metrics": [metadata]}}, {}),
        provider.WindEnvelope(False, "economic_data", "query_economic_indicator_data", {"data": {"metrics": [{"meta": metadata, "date": ["2024-12-31"], "value": [1.0]}]}}, {}),
    ]
    monkeypatch.setattr(provider, "get_transport", lambda: transport)
    with config_scope({"wind_enabled": True}):
        search = provider.search_macro_series("中国GDP")
        result = provider.get_macro_series("M0001395", "2024-01-01", "2024-12-31")
    assert "M0001395" in search and "亿元" in search
    assert "2024-12-31,1.0" in result
    assert transport.call.call_args_list[0].args == ("economic_data", "search_economic_indicator", {"question": "中国GDP"})
    assert transport.call.call_args_list[1].args == ("economic_data", "query_economic_indicator_data", {"question": "M0001395", "beginDate": "2024-01-01", "endDate": "2024-12-31"})
