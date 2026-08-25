# TradingAgents/graph/trading_graph.py

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from langgraph.prebuilt import ToolNode

# Import the abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_equity_risk_metrics,
    get_fundamentals,
    get_fundamentals_research_bundle,
    get_global_news,
    get_income_statement,
    get_index_fundamentals,
    get_index_history,
    get_index_snapshot,
    get_macro_indicators,
    get_macro_series,
    get_news,
    get_verified_current_market_snapshot,
    resolve_instrument_identity,
    search_macro_series,
)
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.analysts import ANALYST_WIRE_KEYS
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.registry import validate_data_vendors
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.default_config import DEFAULT_CONFIG, validate_config
from tradingagents.execution.models import (
    AnalysisRequest,
    AnalysisResult,
    CancellationToken,
)
from tradingagents.execution.runner import AnalysisRunner
from tradingagents.llm_clients import create_llm_client
from tradingagents.llm_clients.provider_kwargs import provider_llm_kwargs
from tradingagents.reporting import write_report_tree

from .conditional_logic import ConditionalLogic
from .propagation import Propagator
from .setup import GraphSetup

logger = logging.getLogger(__name__)


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=ANALYST_WIRE_KEYS,
        debug=False,
        config: dict[str, Any] = None,
        callbacks: list | None = None,
        observation_enabled: bool = False,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
            observation_enabled: Build graph nodes with durable observation wrappers.
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []
        self.observation_enabled = observation_enabled

        self._validate_effective_config()

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        # Initialize LLMs with provider-specific thinking configuration
        llm_kwargs = provider_llm_kwargs(self.config)

        # Add callbacks to kwargs if provided (passed to LLM constructor)
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        deep_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()

        self.memory_log = TradingMemoryLog(self.config)

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config["max_debate_rounds"],
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.conditional_logic,
        )

        self.propagator = Propagator(
            max_recur_limit=self.config.get("max_recur_limit", 100),
        )

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Graph-shape-affecting run choices, kept for the checkpoint signature.
        self.selected_analysts = tuple(selected_analysts)

        # Set up the graph: keep the workflow for recompilation with a checkpointer.
        self.workflow = self.graph_setup.setup_graph(
            selected_analysts,
            observation_enabled=observation_enabled,
        )
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None

    def _validate_effective_config(self) -> None:
        """Fail fast on structurally invalid configuration before LLM/graph setup.

        Validates the merged view (defaults + provided overrides) so a partial
        caller-supplied config inherits defaults, while a bad override (unknown
        vendor, non-boolean switch, invalid round count) fails here with a
        readable message instead of surfacing deep inside an LLM or router call.
        """
        merged = dict(DEFAULT_CONFIG)
        merged.update(self.config)
        problems = validate_config(merged) + validate_data_vendors(merged)
        if problems:
            raise ValueError(
                "invalid TradingAgents configuration:\n- "
                + "\n- ".join(problems)
            )

    def _create_tool_nodes(self) -> dict[str, ToolNode]:
        """Create tool nodes, adding premium Wind tools only when enabled."""
        config = getattr(self, "config", DEFAULT_CONFIG)
        wind_enabled = bool(config.get("wind_enabled", False))
        market_tools = [get_verified_current_market_snapshot]
        news_tools = [get_global_news, get_macro_indicators]
        if wind_enabled:
            market_tools.extend(
                [
                    get_index_snapshot,
                    get_index_history,
                    get_index_fundamentals,
                    get_equity_risk_metrics,
                ]
            )
            news_tools.extend([search_macro_series, get_macro_series])

        return {
            "market": ToolNode(market_tools),
            "social": ToolNode(
                [
                    # News tools for social media analysis
                    get_news,
                ]
            ),
            "news": ToolNode(news_tools),
            "fundamentals": ToolNode(
                [
                    # Fundamental analysis tools
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                    get_fundamentals_research_bundle,
                ]
            ),
        }

    def resolve_instrument_context(self, ticker: str, asset_type: str = "stock") -> str:
        """Resolve ticker identity once and return the full instrument context.

        Company names and multi-format codes are normalised first so any entry
        point (CLI/web/API) accepts ``贵州茅台``, ``688825`` or ``SH688825`` and
        lands on the same canonical ticker.  The resolution is idempotent: an
        already-canonical ticker passes through unchanged.

        A-share tickers resolve via the local 3-tier chain (tushare/akshare/
        yfinance) so agents anchor to the correct Chinese company; non-A-share
        tickers use upstream's yfinance lookup. Both inject identity into the
        context so every agent anchors to the real company instead of
        hallucinating one from the price chart (#814). Both the propagate()
        path and the CLI call this so the resolved identity reaches the whole
        graph regardless of entry point.
        """
        from tradingagents.dataflows.company_resolution import resolve_input_to_ticker
        from tradingagents.dataflows.evidence import resolve_canonical_company_profile
        from tradingagents.dataflows.ticker_utils import is_a_share_ticker

        resolved_input = resolve_input_to_ticker(ticker)
        if resolved_input:
            ticker = resolved_input

        if is_a_share_ticker(ticker):
            profile = resolve_canonical_company_profile(ticker)
            identity = {
                "company_name": profile.get("name") or profile.get("full_name"),
                "industry": profile.get("industry"),
                "exchange": profile.get("exchange"),
            }
        else:
            identity = resolve_instrument_identity(ticker)
        # Stamp the run's target ticker in a contextvar so stateless @tool
        # functions can detect cross-ticker queries and inject a notice.
        from tradingagents.dataflows.target_context import set_target_ticker

        set_target_ticker(ticker, identity.get("company_name") or identity.get("name"))
        return build_instrument_context(ticker, asset_type, identity)

    def _run_signature(self, asset_type: str, horizon: str = "medium") -> str:
        """Graph-shape inputs that must invalidate a checkpoint if changed.

        Keyed into the checkpoint thread ID so a resume under a different analyst
        selection, debate/risk depth, or asset mode starts fresh instead of
        silently continuing the previous graph (#1089).
        """
        return "|".join([
            "analysts=" + ",".join(self.selected_analysts),
            f"debate={self.config['max_debate_rounds']}",
            f"risk={self.config['max_risk_discuss_rounds']}",
            f"asset={asset_type}",
            f"horizon={horizon}",
        ])

    def run_analysis(
        self,
        request: AnalysisRequest,
        *,
        cancellation_token: CancellationToken | None = None,
        observation_context=None,
        callbacks: list | None = None,
        state_update_sink=None,
        checkpoint_run_id: str | None = None,
        checkpoint_guard=None,
    ) -> AnalysisResult:
        """Run one analysis through the consumer-neutral execution boundary."""
        if observation_context is not None and not self.observation_enabled:
            raise ValueError("observation context requires an observed graph")
        return AnalysisRunner(self).run(
            request,
            cancellation_token=cancellation_token,
            observation_context=observation_context,
            callbacks=callbacks,
            state_update_sink=state_update_sink,
            checkpoint_run_id=checkpoint_run_id,
            checkpoint_guard=checkpoint_guard,
        )

    def save_reports(self, final_state, ticker, save_path=None) -> Path:
        """Write the markdown report tree for a completed run, like the CLI does.

        Programmatic callers get the same on-disk reports the CLI produces. Pass
        an explicit ``save_path`` or let it default under ``results_dir``.
        """
        if save_path is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = (
                Path(self.config["results_dir"])
                / "reports"
                / f"{safe_ticker_component(ticker)}_{stamp}"
            )
        return write_report_tree(final_state, ticker, save_path)

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file.

        Learning/holding-review runs skip the trader and risk nodes, so the
        trading-specific keys may be absent.  This is a debug log and must
        never raise and mark an otherwise completed run as failed.
        """
        risk_state = final_state.get("risk_debate_state") or {}
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "history": final_state["investment_debate_state"]["history"],
                "current_response": final_state["investment_debate_state"][
                    "current_response"
                ],
                "judge_decision": final_state["investment_debate_state"][
                    "judge_decision"
                ],
            },
            "risk_debate_state": {
                "aggressive_history": risk_state.get("aggressive_history", ""),
                "conservative_history": risk_state.get("conservative_history", ""),
                "neutral_history": risk_state.get("neutral_history", ""),
                "history": risk_state.get("history", ""),
                "risk_signals": risk_state.get("risk_signals", []),
                "judge_decision": risk_state.get("judge_decision", ""),
            },
            "investment_plan": final_state.get("investment_plan", ""),
            "final_trade_decision": final_state.get(
                "final_trade_decision", "(not applicable: learning mode)"
            ),
        }

        # Save to file. Reject ticker values that would escape the
        # results directory when joined as a path component.
        safe_ticker = safe_ticker_component(self.ticker)
        directory = Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_states_log_{trade_date}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.log_states_dict[str(trade_date)], f, indent=4)
