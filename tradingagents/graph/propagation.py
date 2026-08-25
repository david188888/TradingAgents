# TradingAgents/graph/propagation.py

from typing import Any

from tradingagents.agents.utils.agent_states import (
    InvestDebateState,
    RiskDebateState,
)


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(self, max_recur_limit=100):
        """Initialize with configuration parameters."""
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self,
        company_name: str,
        trade_date: str,
        asset_type: str = "stock",
        past_context: str = "",
        instrument_context: str = "",
        analysis_cutoff: dict[str, Any] | None = None,
        portfolio_context: dict[str, Any] | None = None,
        observation_context=None,
        horizon: str = "medium",
        mode: str = "company_research",
        holding_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create the initial state for the agent graph.

        ``instrument_context`` is the deterministic ticker-identity string
        resolved once at run start (see
        ``TradingAgentsGraph.resolve_instrument_context``). When empty, agents
        fall back to ticker-only context via
        ``get_instrument_context_from_state``.
        """
        state = {
            "messages": [("human", company_name)],
            "company_of_interest": company_name,
            "asset_type": asset_type,
            "mode": mode,
            "horizon": horizon,
            "holding_context": holding_context,
            "portfolio_context": portfolio_context,
            "instrument_context": instrument_context,
            "analysis_cutoff": dict(analysis_cutoff or {}),
            "trade_date": str(trade_date),
            "past_context": past_context,
            "investment_debate_state": InvestDebateState(
                {
                    "bull_history": "",
                    "bear_history": "",
                    "history": "",
                    "current_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "aggressive_history": "",
                    "conservative_history": "",
                    "neutral_history": "",
                    "history": "",
                    "latest_speaker": "",
                    "current_aggressive_response": "",
                    "current_conservative_response": "",
                    "current_neutral_response": "",
                    "risk_signals": [],
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "market_report": "",
            "adjusted_price_bundle": "",
            "fundamentals_report": "",
            "fundamentals_prefetch_bundle": "",
            "sentiment_report": "",
            "a_share_supplement_bundle": "",
            "news_report": "",
            "news_window_bundle": "",
            "methodology_reports": {},
            "canonical_company_profile": {},
            "evidence_status": "",
            "evidence_gate_fault": None,
            "evidence_report": "",
            "evidence_ledger": {},
            "evidence_ledger_artifact_id": None,
            "research_dossier": {},
            "clamp_events": [],
            "execution_outcome": None,
            "holding_review_summary": None,
            "context_compaction_facts": [],
        }
        if observation_context is not None:
            from tradingagents.observability.graph_tasks import observe_initial_input

            return observe_initial_input(state, observation_context)
        return state

    def get_graph_args(self, callbacks: list | None = None) -> dict[str, Any]:
        """Get arguments for the graph invocation.

        Args:
            callbacks: Optional list of callback handlers for tool execution tracking.
                       Note: LLM callbacks are handled separately via LLM constructor.
        """
        config = {"recursion_limit": self.max_recur_limit}
        if callbacks:
            config["callbacks"] = callbacks
        return {
            "stream_mode": "values",
            "config": config,
        }
