from __future__ import annotations

import pytest

from tradingagents.agents.utils import market_data_validation_tools as tools
from tradingagents.research.horizon_policy import build_data_window_plan


@pytest.mark.unit
def test_a_share_adjusted_price_policy_declares_wind_qfq_source_first():
    capability = build_data_window_plan("medium", "2026-08-13", market="a_share").capability_index()[
        "adjusted_price_history"
    ]
    source_ids = tuple(
        source_id
        for group in capability.required_source_groups
        for source_id in group.source_ids
    )

    assert source_ids[:3] == (
        "wind.stock_kline_qfq_daily",
        "tushare.qfq_daily",
        "akshare.qfq_daily",
    )
    assert tools._ADJUSTED_SOURCE_BY_VENDOR["wind"] == "wind.stock_kline_qfq_daily"
