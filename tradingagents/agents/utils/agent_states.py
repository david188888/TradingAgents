from typing import Annotated, Any, Literal

from langgraph.graph import MessagesState
from typing_extensions import TypedDict


def merge_observation_commits(
    left: dict[str, dict[str, Any]] | None,
    right: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Preserve distinct task commit tokens across parallel graph writes."""
    merged = dict(left or {})
    for graph_task_id, commit in (right or {}).items():
        existing = merged.get(graph_task_id)
        if existing is not None and existing != commit:
            raise ValueError(f"conflicting observation commit for task {graph_task_id}")
        merged[graph_task_id] = commit
    return merged


# Researcher team state
class InvestDebateState(TypedDict):
    bull_history: Annotated[str, "Bullish Conversation history"]  # Bullish Conversation history
    bear_history: Annotated[str, "Bearish Conversation history"]  # Bullish Conversation history
    history: Annotated[str, "Conversation history"]  # Conversation history
    current_response: Annotated[str, "Latest response"]  # Last response
    judge_decision: Annotated[str, "Final judge decision"]  # Last response
    count: Annotated[int, "Length of the current conversation"]  # Conversation length


class ReaderPublicOutput(TypedDict):
    """Typed public output promoted to a Reader artifact after commit."""

    kind: Literal["research", "trader", "portfolio", "risk"]
    value: dict[str, Any]


# Risk management team state
class RiskDebateState(TypedDict):
    aggressive_history: Annotated[
        str, "Aggressive Agent's Conversation history"
    ]  # Conversation history
    conservative_history: Annotated[
        str, "Conservative Agent's Conversation history"
    ]  # Conversation history
    neutral_history: Annotated[str, "Neutral Agent's Conversation history"]  # Conversation history
    history: Annotated[str, "Conversation history"]  # Conversation history
    latest_speaker: Annotated[str, "Analyst that spoke last"]
    current_aggressive_response: Annotated[
        str, "Latest response by the aggressive analyst"
    ]  # Last response
    current_conservative_response: Annotated[
        str, "Latest response by the conservative analyst"
    ]  # Last response
    current_neutral_response: Annotated[
        str, "Latest response by the neutral analyst"
    ]  # Last response
    risk_signals: Annotated[
        list[dict[str, Any]],
        "Latest typed public signal from each risk analyst; never private reasoning",
    ]
    judge_decision: Annotated[str, "Judge's decision"]
    count: Annotated[int, "Length of the current conversation"]  # Conversation length


class AgentState(MessagesState):
    _observation_commits: Annotated[
        dict[str, dict[str, Any]],
        merge_observation_commits,
    ]
    company_of_interest: Annotated[str, "Company that we are interested in trading"]
    instrument_context: Annotated[str, "Deterministic ticker identity resolved at run start"]
    trade_date: Annotated[str, "What date we are trading at"]
    analysis_cutoff: Annotated[
        dict[str, Any],
        "Verified market-time analysis cutoff resolved before time-sensitive fetches",
    ]
    mode: Annotated[str, "Research mode: company_research or holding_review"]
    horizon: Annotated[str, "Investment horizon: short, medium, or long"]
    asset_type: Annotated[str, "Asset type: stock (default) or crypto"]
    portfolio_context: Annotated[
        dict[str, Any] | None, "Non-secret portfolio facts for PM constraints"
    ]
    holding_context: Annotated[
        dict[str, Any] | None,
        "Normalized target holding facts for learning-oriented holding review",
    ]

    sender: Annotated[str, "Agent that sent this message"]

    # research step
    market_report: Annotated[str, "Report from the Market Analyst"]
    adjusted_price_bundle: Annotated[
        str,
        "Deterministically prefetched adjusted history plus separately labelled raw audit",
    ]
    sentiment_report: Annotated[str, "Report from the Sentiment Analyst"]
    a_share_supplement_bundle: Annotated[
        str,
        "Deterministically prefetched horizon-budgeted A-share supplements",
    ]
    news_report: Annotated[str, "Report from the News Researcher of current world affairs"]
    news_window_bundle: Annotated[
        str,
        "Deterministically prefetched horizon-specific news and disclosure bundle",
    ]
    fundamentals_report: Annotated[str, "Report from the Fundamentals Researcher"]
    methodology_reports: Annotated[
        dict[str, dict[str, Any]],
        "Validated public analyst methodology scorecards; no prompts or private reasoning",
    ]

    # evidence gate output; these must be declared application channels or
    # LangGraph silently drops the Evidence Steward's successful result.
    canonical_company_profile: Annotated[
        dict[str, Any], "Canonical instrument identity verified by the evidence gate"
    ]
    evidence_status: Annotated[str, "Evidence gate status"]
    evidence_gate_fault: Annotated[
        str | None, "Public fault category when the evidence gate itself fails"
    ]
    evidence_report: Annotated[str, "Evidence sufficiency and enrichment report"]
    evidence_ledger: Annotated[
        dict[str, Any], "Structured claim-evidence-criterion audit ledger without private reasoning"
    ]
    evidence_ledger_artifact_id: Annotated[
        str | None, "Durable evidence-ledger artifact when an observer is active"
    ]
    research_dossier: Annotated[
        dict[str, Any],
        "A-share-first structured chain: windows, claims, milestones, edges, profit bridge, valuation",
    ]

    # researcher team discussion step
    investment_debate_state: Annotated[
        InvestDebateState, "Current state of the debate on if to invest or not"
    ]
    investment_plan: Annotated[str, "Plan generated by the Analyst"]
    context_compaction_facts: Annotated[
        list[str],
        "Public facts retained when older debate context is compacted; never private reasoning",
    ]

    trader_investment_plan: Annotated[str, "Plan generated by the Trader"]
    reader_public_output: Annotated[
        ReaderPublicOutput,
        "Typed public output promoted to a Reader artifact after commit",
    ]
    research_case_candidate: Annotated[
        dict[str, str],
        "Public, non-prose inputs for ResearchCase assembly after a durable commit",
    ]

    # risk management team discussion step
    risk_debate_state: Annotated[RiskDebateState, "Current state of the debate on evaluating risk"]
    final_trade_decision: Annotated[str, "Final decision made by the Risk Analysts"]
    allowed_actions: Annotated[list[dict[str, Any]], "Deterministic PM action limits"]
    clamp_events: Annotated[list[dict[str, Any]], "Deterministic PM constraint audit events"]
    execution_outcome: Annotated[
        dict[str, Any] | None,
        "Single source of truth for requested versus effective execution",
    ]
    holding_review_summary: Annotated[
        dict[str, Any] | None,
        "Deterministic holding-review metrics and explicit unavailable reasons",
    ]
    feature_contributions: Annotated[
        list[dict[str, Any]],
        "Measured feature attribution inputs; never inferred from model prose",
    ]
    past_context: Annotated[
        str,
        "Memory log context injected at run start (same-ticker decisions + cross-ticker lessons)",
    ]
