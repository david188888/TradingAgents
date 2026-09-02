"""Memory-log lessons must be point-in-time safe in a backtest (#1251).

get_past_context previously returned every resolved lesson regardless of the run
date, so a historical run could learn from an outcome that had not happened yet.
Resolved entries record the date their outcome became known (``resolved:``),
and get_past_context(as_of=...) filters on it. Legacy entries without a
resolution date are excluded from a point-in-time query (conservative migration).

The fork retired the memory write side with the legacy transaction path, so the
entries here are seeded directly as text fixtures (mirroring the legacy log
shape the read side still parses).
"""
from __future__ import annotations

import pytest

from tradingagents.agents.utils.memory import TradingMemoryLog

_SEP = TradingMemoryLog._SEPARATOR


def _log(tmp_path):
    return TradingMemoryLog({"memory_log_path": str(tmp_path / "mem.md")})


def _seed_resolved(tmp_path, ticker, date, resolution_date, reflection,
                   decision_text="Rating: Buy\nSeed decision."):
    """Write a resolved entry directly to file, bypassing the removed write API."""
    entry = (
        f"[{date} | {ticker} | Buy | +5.0% | +2.0% | 5d | resolved:{resolution_date}]\n\n"
        f"DECISION:\n{decision_text}\n\n"
        f"REFLECTION:\n{reflection}"
        + _SEP
    )
    with open(tmp_path / "mem.md", "a", encoding="utf-8") as f:
        f.write(entry)


def _seed_legacy_resolved(tmp_path, ticker, date, reflection):
    """Write a pre-migration resolved entry: no resolution date recorded."""
    entry = (
        f"[{date} | {ticker} | Buy | +5.0% | +2.0% | 5d]\n\n"
        f"DECISION:\nRating: Buy\nSeed decision.\n\n"
        f"REFLECTION:\n{reflection}"
        + _SEP
    )
    with open(tmp_path / "mem.md", "a", encoding="utf-8") as f:
        f.write(entry)


@pytest.mark.unit
def test_resolution_date_is_stored_and_parsed(tmp_path):
    _seed_resolved(tmp_path, "NVDA", "2026-01-05", "2026-01-10", "outcome known 01-10")
    log = _log(tmp_path)
    entry = log.load_entries()[0]
    assert entry["resolved"] == "2026-01-10"
    assert "resolved:2026-01-10" in (tmp_path / "mem.md").read_text()


@pytest.mark.unit
def test_as_of_excludes_lessons_resolved_after_the_run_date(tmp_path):
    # Decision on 01-05, outcome only known on 01-10.
    _seed_resolved(tmp_path, "NVDA", "2026-01-05", "2026-01-10", "great trade")
    log = _log(tmp_path)

    # A run as-of 01-07 must NOT see it (the outcome was still in the future).
    assert log.get_past_context("NVDA", as_of="2026-01-07") == ""
    # A run as-of 01-10 (and later) sees it.
    assert "great trade" in log.get_past_context("NVDA", as_of="2026-01-10")
    assert "great trade" in log.get_past_context("NVDA", as_of="2026-02-01")


@pytest.mark.unit
def test_no_as_of_is_unfiltered_live_behavior(tmp_path):
    _seed_resolved(tmp_path, "NVDA", "2026-01-05", "2026-01-10", "great trade")
    log = _log(tmp_path)
    # Live run (no as_of): unchanged behavior, lesson is shown.
    assert "great trade" in log.get_past_context("NVDA")


@pytest.mark.unit
def test_legacy_entry_without_resolution_date_excluded_in_backtest(tmp_path):
    # Simulate a pre-migration resolved entry: no resolution_date recorded.
    _seed_legacy_resolved(tmp_path, "NVDA", "2026-01-05", "legacy lesson")
    log = _log(tmp_path)
    entry = log.load_entries()[0]
    assert entry["resolved"] is None

    # Conservative: excluded from a point-in-time query (can't prove it was known)...
    assert log.get_past_context("NVDA", as_of="2026-06-01") == ""
    # ...but still available on a live (unfiltered) run.
    assert "legacy lesson" in log.get_past_context("NVDA")


@pytest.mark.unit
def test_cross_ticker_lessons_are_also_gated(tmp_path):
    _seed_resolved(tmp_path, "AAPL", "2026-01-05", "2026-01-10", "cross lesson")
    log = _log(tmp_path)
    # Querying a different ticker as-of before resolution: no cross lesson leaks.
    assert log.get_past_context("NVDA", as_of="2026-01-07") == ""
    assert "cross lesson" in log.get_past_context("NVDA", as_of="2026-01-10")


@pytest.mark.unit
def test_memory_as_of_gates_historical_but_not_live():
    # The runner filters only for a past trade date; a current-date run passes
    # None so live behavior and legacy entries are unaffected (#1251).
    from datetime import datetime, timedelta

    from tradingagents.execution.runner import _memory_as_of

    past = "2024-01-01"
    today = datetime.now().strftime("%Y-%m-%d")
    future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    assert _memory_as_of(past) == past       # backtest -> filter on the trade date
    assert _memory_as_of(today) is None      # live -> no filter
    assert _memory_as_of(future) is None     # future-dated run -> no filter
