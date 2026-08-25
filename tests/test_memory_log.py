"""Tests for TradingMemoryLog — read-side parsing, past-context injection, legacy removal.

The write side (store_decision / update_with_outcome / rotation) was retired
with the legacy transaction path; tests seed log files directly as text
fixtures and cover only what remains: parsing and get_past_context.
"""

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.trading_graph import TradingAgentsGraph

_SEP = TradingMemoryLog._SEPARATOR


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_log(tmp_path, filename="trading_memory.md"):
    config = {"memory_log_path": str(tmp_path / filename)}
    return TradingMemoryLog(config)


def _seed_completed(tmp_path, ticker, date, decision_text, reflection_text,
                    rating="Buy", raw="+1.0%", alpha="+0.5%", holding="5d",
                    filename="trading_memory.md"):
    """Write a completed entry directly to file, bypassing the removed write API."""
    entry = (
        f"[{date} | {ticker} | {rating} | {raw} | {alpha} | {holding}]\n\n"
        f"DECISION:\n{decision_text}\n\n"
        f"REFLECTION:\n{reflection_text}"
        + _SEP
    )
    with open(tmp_path / filename, "a", encoding="utf-8") as f:
        f.write(entry)


def _seed_pending(tmp_path, ticker, date, decision_text, filename="trading_memory.md"):
    """Write a pending entry (legacy log shape) directly to file."""
    entry = (
        f"[{date} | {ticker} | Buy | pending]\n\n"
        f"DECISION:\n{decision_text}"
        + _SEP
    )
    with open(tmp_path / filename, "a", encoding="utf-8") as f:
        f.write(entry)


# ---------------------------------------------------------------------------
# Read path: load_entries
# ---------------------------------------------------------------------------

class TestLoadEntries:

    def test_load_entries_missing_file(self, tmp_path):
        log = make_log(tmp_path)
        assert log.load_entries() == []

    def test_load_entries_empty_file(self, tmp_path):
        log = make_log(tmp_path)
        (tmp_path / "trading_memory.md").write_text("", encoding="utf-8")
        assert log.load_entries() == []

    def test_load_entries_single(self, tmp_path):
        log = make_log(tmp_path)
        _seed_completed(tmp_path, "NVDA", "2026-01-10", "Buy NVDA.", "Correct.")
        entries = log.load_entries()
        assert len(entries) == 1
        e = entries[0]
        assert e["date"] == "2026-01-10"
        assert e["ticker"] == "NVDA"
        assert e["rating"] == "Buy"
        assert e["pending"] is False
        assert e["raw"] == "+1.0%"

    def test_load_entries_multiple(self, tmp_path):
        log = make_log(tmp_path)
        _seed_completed(tmp_path, "NVDA", "2026-01-10", "Buy NVDA.", "Correct.")
        _seed_completed(tmp_path, "AAPL", "2026-01-11", "Buy AAPL.", "Correct.")
        _seed_completed(
            tmp_path, "MSFT", "2026-01-12",
            "Executive Summary: complex situation.", "Mixed.",
            rating="Overweight",
        )
        entries = log.load_entries()
        assert len(entries) == 3
        assert [e["ticker"] for e in entries] == ["NVDA", "AAPL", "MSFT"]

    def test_decision_content_preserved(self, tmp_path):
        log = make_log(tmp_path)
        _seed_completed(tmp_path, "NVDA", "2026-01-10", "Buy NVDA at open.", "Correct.")
        assert log.load_entries()[0]["decision"] == "Buy NVDA at open."

    def test_reflection_content_preserved(self, tmp_path):
        log = make_log(tmp_path)
        _seed_completed(tmp_path, "NVDA", "2026-01-10", "Buy NVDA.", "Thesis played out.")
        assert log.load_entries()[0]["reflection"] == "Thesis played out."

    def test_legacy_pending_entry_parses(self, tmp_path):
        """Pending entries written by earlier versions still parse."""
        log = make_log(tmp_path)
        _seed_pending(tmp_path, "NVDA", "2026-01-10", "Buy NVDA.")
        entries = log.load_entries()
        assert len(entries) == 1
        assert entries[0]["pending"] is True
        assert entries[0]["raw"] is None

    def test_decision_with_markdown_separator(self, tmp_path):
        """LLM decision containing '---' must not corrupt the entry."""
        log = make_log(tmp_path)
        _seed_completed(
            tmp_path, "NVDA", "2026-01-10",
            "Rating: Buy\n\n---\n\nRisk: elevated volatility.",
            "Correct.",
        )
        entries = log.load_entries()
        assert len(entries) == 1
        assert "Risk: elevated volatility" in entries[0]["decision"]


# ---------------------------------------------------------------------------
# get_past_context
# ---------------------------------------------------------------------------

class TestGetPastContext:

    def test_get_past_context_empty(self, tmp_path):
        log = make_log(tmp_path)
        assert log.get_past_context("NVDA") == ""

    def test_get_past_context_pending_excluded(self, tmp_path):
        log = make_log(tmp_path)
        _seed_pending(tmp_path, "NVDA", "2026-01-10", "Buy NVDA.")
        assert log.get_past_context("NVDA") == ""

    def test_get_past_context_same_ticker(self, tmp_path):
        log = make_log(tmp_path)
        _seed_completed(
            tmp_path, "NVDA", "2026-01-05",
            "Buy NVDA — AI capex thesis intact.", "Directionally correct.",
        )
        ctx = log.get_past_context("NVDA")
        assert "Past analyses of NVDA" in ctx
        assert "Buy NVDA" in ctx

    def test_get_past_context_cross_ticker(self, tmp_path):
        log = make_log(tmp_path)
        _seed_completed(tmp_path, "AAPL", "2026-01-05", "Buy AAPL — Services growth.", "Correct.")
        ctx = log.get_past_context("NVDA")
        assert "Recent cross-ticker lessons" in ctx
        assert "Past analyses of NVDA" not in ctx

    def test_same_ticker_prioritised(self, tmp_path):
        """Same-ticker entries land in the same-ticker section; cross-ticker in theirs."""
        log = make_log(tmp_path)
        _seed_completed(tmp_path, "NVDA", "2026-01-05", "Buy NVDA.", "Momentum confirmed.")
        _seed_completed(tmp_path, "AAPL", "2026-01-06", "Sell AAPL.", "Overvalued.")
        result = log.get_past_context("NVDA")
        assert "Past analyses of NVDA" in result
        assert "Recent cross-ticker lessons" in result
        same_block, cross_block = result.split("Recent cross-ticker lessons")
        assert "NVDA" in same_block
        assert "AAPL" in cross_block

    def test_cross_ticker_reflection_only(self, tmp_path):
        """Cross-ticker entries show only the REFLECTION text, not the full DECISION."""
        log = make_log(tmp_path)
        _seed_completed(tmp_path, "AAPL", "2026-01-06", "Sell AAPL immediately.", "Overvalued correction.")
        result = log.get_past_context("NVDA")
        assert "Overvalued correction." in result
        assert "Sell AAPL immediately." not in result

    def test_n_same_limit_respected(self, tmp_path):
        """Only the n_same most recent same-ticker entries are included."""
        log = make_log(tmp_path)
        for i in range(6):
            _seed_completed(tmp_path, "NVDA", f"2026-01-{i+1:02d}", f"Buy entry {i}.", "Correct.")
        ctx = log.get_past_context("NVDA", n_same=5)
        assert "Buy entry 0" not in ctx
        assert "Buy entry 5" in ctx

    def test_n_cross_limit_respected(self, tmp_path):
        """Only the n_cross most recent cross-ticker entries are included."""
        log = make_log(tmp_path)
        for i, ticker in enumerate(["AAPL", "MSFT", "GOOG", "META"]):
            _seed_completed(tmp_path, ticker, f"2026-01-{i+1:02d}", f"Buy {ticker}.", "Correct.")
        ctx = log.get_past_context("NVDA", n_cross=3)
        assert "AAPL" not in ctx
        assert "META" in ctx

    # No-op when config is None

    def test_no_log_path_is_noop(self):
        log = TradingMemoryLog(config=None)
        assert log.load_entries() == []
        assert log.get_past_context("NVDA") == ""


# ---------------------------------------------------------------------------
# Initial-state wiring: past_context still reaches the graph
# ---------------------------------------------------------------------------

class TestPastContextInjection:

    def test_past_context_in_initial_state(self):
        propagator = Propagator()
        state = propagator.create_initial_state(
            "NVDA", "2026-01-10", past_context="some context"
        )
        assert state["past_context"] == "some context"

    def test_past_context_defaults_to_empty(self):
        propagator = Propagator()
        state = propagator.create_initial_state("NVDA", "2026-01-10")
        assert state["past_context"] == ""

    def test_learning_review_carries_state_unchanged(self):
        """The PM learning node is a deterministic transform: no LLM call."""
        llm = MagicMock()
        llm.invoke.side_effect = AssertionError("PM learning path must not call the LLM")
        pm_node = create_portfolio_manager(llm)
        state = {
            "mode": "company_research",
            "evidence_status": "OK",
            "trade_date": "2026-01-10",
            "risk_debate_state": {
                "history": "",
                "aggressive_history": "",
                "conservative_history": "",
                "neutral_history": "",
                "current_aggressive_response": "",
                "current_conservative_response": "",
                "current_neutral_response": "",
                "risk_signals": [],
                "count": 0,
            },
        }
        result = pm_node(state)
        assert "研究结论" in result["final_trade_decision"]
        assert result["execution_outcome"] is None
        llm.invoke.assert_not_called()


# ---------------------------------------------------------------------------
# Legacy removal: transaction-path APIs fully gone
# ---------------------------------------------------------------------------

class TestLegacyRemoval:

    def test_financial_situation_memory_removed(self):
        """FinancialSituationMemory must not be importable from the memory module."""
        import tradingagents.agents.utils.memory as m
        assert not hasattr(m, "FinancialSituationMemory")

    def test_bm25_not_imported(self):
        """rank_bm25 must not be present in the memory module namespace."""
        import tradingagents.agents.utils.memory as m
        assert not hasattr(m, "BM25Okapi")

    def test_write_side_removed(self):
        """The retired transaction memory write API must be gone."""
        assert not hasattr(TradingMemoryLog, "store_decision")
        assert not hasattr(TradingMemoryLog, "update_with_outcome")
        assert not hasattr(TradingMemoryLog, "batch_update_with_outcomes")
        assert not hasattr(TradingMemoryLog, "get_pending_entries")

    def test_reflection_and_signal_processing_removed(self):
        """The retired reflection chain modules must be gone."""
        with pytest.raises(ModuleNotFoundError):
            import tradingagents.graph.signal_processing  # noqa: F401
        with pytest.raises(ModuleNotFoundError):
            import tradingagents.graph.reflection  # noqa: F401

    def test_reflect_and_remember_removed(self):
        """TradingAgentsGraph must not expose reflect_and_remember."""
        assert not hasattr(TradingAgentsGraph, "reflect_and_remember")

    def test_portfolio_manager_no_memory_param(self):
        """create_portfolio_manager accepts only llm; passing memory= raises TypeError."""
        mock_llm = MagicMock()
        create_portfolio_manager(mock_llm)
        with pytest.raises(TypeError):
            create_portfolio_manager(mock_llm, memory=MagicMock())
