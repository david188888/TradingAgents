"""Tests for provider-specific kwargs in TradingAgentsGraph._get_provider_kwargs.

Covers the DeepSeek thinking/effort wiring (P2/P3) and the cross-provider
max_tokens cap (P4).
"""

import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph


@pytest.mark.unit
class TestDeepSeekProviderKwargs:
    def _kwargs_for(self, **overrides):
        from tradingagents.default_config import DEFAULT_CONFIG

        config = {**DEFAULT_CONFIG, "llm_provider": "deepseek", **overrides}
        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.config = config
        return TradingAgentsGraph._get_provider_kwargs(graph)

    def test_default_uses_enabled_thinking_with_high_effort(self):
        # Fork default: thinking enabled + high reasoning effort (7ac8ce5).
        kwargs = self._kwargs_for()
        assert kwargs["thinking"] == {"type": "enabled"}
        assert kwargs["reasoning_effort"] == "high"

    def test_thinking_enabled_passes_dict(self):
        kwargs = self._kwargs_for(deepseek_thinking="enabled")
        assert kwargs["thinking"] == {"type": "enabled"}

    def test_thinking_disabled_passes_nothing(self):
        kwargs = self._kwargs_for(deepseek_thinking="disabled")
        assert "thinking" not in kwargs

    def test_effort_forwarded(self):
        kwargs = self._kwargs_for(deepseek_reasoning_effort="max")
        assert kwargs["reasoning_effort"] == "max"

    def test_effort_normalized_lowercase(self):
        kwargs = self._kwargs_for(deepseek_reasoning_effort="HIGH")
        assert kwargs["reasoning_effort"] == "high"

    def test_thinking_and_effort_together(self):
        kwargs = self._kwargs_for(
            deepseek_thinking="enabled", deepseek_reasoning_effort="low"
        )
        assert kwargs["thinking"] == {"type": "enabled"}
        assert kwargs["reasoning_effort"] == "low"


@pytest.mark.unit
class TestMaxTokensProviderKwargs:
    def _kwargs_for(self, **overrides):
        from tradingagents.default_config import DEFAULT_CONFIG

        config = {**DEFAULT_CONFIG, "llm_provider": "deepseek", **overrides}
        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.config = config
        return TradingAgentsGraph._get_provider_kwargs(graph)

    def test_max_tokens_forwarded(self):
        assert self._kwargs_for(llm_max_tokens=16384)["max_tokens"] == 16384

    def test_max_tokens_string_coerced(self):
        assert self._kwargs_for(llm_max_tokens="8192")["max_tokens"] == 8192

    def test_max_tokens_none_omitted(self):
        assert "max_tokens" not in self._kwargs_for(llm_max_tokens=None)
