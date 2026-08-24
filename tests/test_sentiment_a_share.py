"""Tests for A-share vs non-A-share sentiment analyst routing."""

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.agents.analysts.sentiment_analyst import create_sentiment_analyst
from tradingagents.agents.schemas import SentimentBand, SentimentReport


def _structured_llm(captured: dict):
    report = SentimentReport(
        overall_band=SentimentBand.NEUTRAL,
        overall_score=5.0,
        confidence="medium",
        narrative="neutral",
    )
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: (
        captured.__setitem__("prompt", prompt) or report
    )
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


def _state(ticker: str):
    return {
        "company_of_interest": ticker,
        "trade_date": "2026-07-23",
        "asset_type": "stock",
        "messages": [],
        "horizon": "medium",
        "a_share_supplement_bundle": (
            '{"status":"partial","results":['
            '{"capability":"northbound_flow","status":"ok","data":"flow"},'
            '{"capability":"margin_financing","status":"ok","data":"margin"},'
            '{"capability":"insider_trades","status":"ok","data":"insider"},'
            '{"capability":"hot_list","status":"unavailable"}]}'
        ),
    }


@pytest.mark.unit
class TestSentimentAnalystRouting:
    @patch("tradingagents.agents.analysts.sentiment_analyst.fetch_stocktwits_messages")
    @patch("tradingagents.agents.analysts.sentiment_analyst.fetch_reddit_posts")
    @patch("tradingagents.agents.utils.news_data_tools.route_to_vendor")
    def test_a_share_uses_capital_flow_sources(
        self, mock_news_route, mock_reddit, mock_stocktwits
    ):
        mock_news_route.return_value = "news data"
        captured = {}
        analyst = create_sentiment_analyst(_structured_llm(captured))
        analyst(_state("600519.SH"))

        prompt = str(captured["prompt"])
        # A-share prompt has capital-flow blocks, not Reddit/StockTwits data
        assert "northbound_flow" in prompt
        assert "Margin financing" in prompt
        assert "Insider trades" in prompt
        assert "<start_of_stocktwits>" not in prompt
        assert "<start_of_reddit>" not in prompt
        assert "r/wallstreetbets" not in prompt
        # reality_gap instructed to stay null for A-share
        assert "Leave null" in prompt or "leave null" in prompt.lower()
        assert "a_share_supplement_bundle" in prompt
        assert '"capability":"margin_financing"' in prompt
        assert '"capability":"hot_list","status":"unavailable"' in prompt

    @patch("tradingagents.agents.analysts.sentiment_analyst.fetch_stocktwits_messages")
    @patch("tradingagents.agents.analysts.sentiment_analyst.fetch_reddit_posts")
    @patch("tradingagents.agents.utils.news_data_tools.route_to_vendor")
    def test_us_share_uses_reddit_stocktwits(
        self, mock_news_route, mock_reddit, mock_stocktwits
    ):
        mock_news_route.return_value = "news data"
        mock_reddit.return_value = "reddit data"
        mock_stocktwits.return_value = "stocktwits data"
        captured = {}
        analyst = create_sentiment_analyst(_structured_llm(captured))
        analyst(_state("AAPL"))

        prompt = str(captured["prompt"])
        assert "StockTwits" in prompt
        assert "Reddit" in prompt
        assert "Northbound" not in prompt
        assert mock_reddit.called
        assert mock_stocktwits.called

    @patch("tradingagents.agents.analysts.sentiment_analyst.fetch_stocktwits_messages")
    @patch("tradingagents.agents.analysts.sentiment_analyst.fetch_reddit_posts")
    @patch("tradingagents.agents.utils.news_data_tools.route_to_vendor")
    def test_a_share_bundle_is_lower_priority_assistant_evidence(
        self, mock_news_route, mock_reddit, mock_stocktwits
    ):
        mock_news_route.return_value = "news data"
        captured = {}
        analyst = create_sentiment_analyst(_structured_llm(captured))
        analyst(_state("600519.SH"))

        messages = captured["prompt"]
        system = "\n".join(str(message.content) for message in messages if message.type == "system")
        assistant = "\n".join(str(message.content) for message in messages if message.type == "ai")
        assert '"capability":"margin_financing"' not in system
        assert '"capability":"margin_financing"' in assistant

    @patch("tradingagents.agents.analysts.sentiment_analyst.fetch_stocktwits_messages")
    @patch("tradingagents.agents.analysts.sentiment_analyst.fetch_reddit_posts")
    @patch("tradingagents.agents.utils.news_data_tools.route_to_vendor")
    def test_a_share_partial_bundle_still_produces_report(
        self, mock_news_route, mock_reddit, mock_stocktwits
    ):
        mock_news_route.return_value = "news data"
        captured = {}
        analyst = create_sentiment_analyst(_structured_llm(captured))
        result = analyst(_state("600519.SH"))

        assert result["sentiment_report"] is not None
        prompt = str(captured["prompt"])
        assert '"status":"partial"' in prompt
        assert '"capability":"hot_list","status":"unavailable"' in prompt
