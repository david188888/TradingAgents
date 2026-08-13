from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tradingagents.dataflows.coverage import CoveredText, SourceCoverageV1
from tradingagents.dataflows.news_curator import (
    _filter_stale_items,
    _format_curated_news,
    _parse_date_best_effort,
)
from tradingagents.dataflows.target_context import (
    clear_target_ticker,
    set_target_ticker,
)
from tradingagents.dataflows.ticker_utils import normalize_ticker_symbol


@pytest.mark.parametrize("ticker", ("600519.SZ", "SZ600519", "688981.SZ"))
def test_normalization_rejects_explicit_market_conflicts(ticker: str) -> None:
    with pytest.raises(ValueError, match="市场标识与号段矛盾"):
        normalize_ticker_symbol(ticker)


def test_timezone_offsets_are_preserved_before_utc_conversion() -> None:
    assert _parse_date_best_effort("2026-08-13T23:30:00-05:00") == datetime(
        2026, 8, 14, 4, 30, tzinfo=timezone.utc
    )
    assert _parse_date_best_effort("2026-08-14T00:30:00+08:00") == datetime(
        2026, 8, 13, 16, 30, tzinfo=timezone.utc
    )


def test_a_share_window_uses_shanghai_market_date_and_marks_unknown() -> None:
    set_target_ticker("600519.SH", "贵州茅台")
    try:
        items = [
            {"title": "inside", "published": "2026-08-13T23:30:00+08:00"},
            {"title": "next day", "published": "2026-08-14T00:30:00+08:00"},
            {"title": "unknown", "published": ""},
        ]
        kept, stale_count = _filter_stale_items(
            items, "2026-08-13", "2026-08-13"
        )
    finally:
        clear_target_ticker()

    assert [item["title"] for item in kept] == ["inside", "unknown"]
    assert stale_count == 1
    assert kept[0]["published_time_status"] == "verified"
    assert kept[1]["published_time_status"] == "unknown"


def test_unknown_publication_time_downgrades_complete_coverage() -> None:
    coverage = SourceCoverageV1(
        capability="company_event_window",
        source_id="test.news",
        requested_start="2026-08-01",
        requested_end="2026-08-13",
        actual_start="2026-08-01",
        actual_end="2026-08-13",
        item_count=1,
        completeness="complete",
        sources=("test.news",),
        as_of="2026-08-13",
    )
    result = {
        "items": [{"title": "Undated company event", "published": ""}],
        "coverage": coverage.model_dump(mode="json"),
    }

    curated = _format_curated_news(
        "get_news",
        [("test", result)],
        [],
        start_date="2026-08-01",
        end_date="2026-08-13",
    )

    assert isinstance(curated, CoveredText)
    assert curated.coverage.completeness == "unknown"
    assert "publication_time_unknown_excluded_from_window_coverage" in (
        curated.coverage.degradations
    )
