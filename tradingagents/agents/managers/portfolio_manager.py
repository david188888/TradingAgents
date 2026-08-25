"""Portfolio Manager: closes each learning run with the research-review verdict.

The legacy Trader/risk-debator transaction path has been retired; the graph
wires Research Manager straight into this node.  The learning path is a
deterministic state transform (no LLM call): it records the research-only
verdict, the holding-review summary when applicable, and promotes the typed
public output for the Reader.
"""

from __future__ import annotations

from collections.abc import Mapping

from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.research import build_holding_review_summary, holding_review_quote_from_bundle


def create_portfolio_manager(llm):
    def portfolio_manager_node(state: AgentState) -> dict:
        return _learning_review_result(state)

    return portfolio_manager_node


def _learning_review_result(state: Mapping[str, object]) -> dict:
    """Close the learning-only public modes with a research review verdict."""
    mode = state.get("mode")
    evidence_status = str(state.get("evidence_status") or "unknown")
    holding = state.get("holding_context")
    analysis_date = str(
        state.get("trade_date")
        or (holding.get("facts_as_of") if isinstance(holding, Mapping) else "")
    )
    holding_summary = (
        build_holding_review_summary(
            holding,
            analysis_date=analysis_date,
            **holding_review_quote_from_bundle(state.get("adjusted_price_bundle")),
        )
        if mode == "holding_review" and isinstance(holding, Mapping)
        else None
    )
    holding_line = (
        "\n\n持仓复盘输入已记录；请结合证据复查原始逻辑、风险暴露、失效条件与下一次验证。"
        if mode == "holding_review" and isinstance(holding, Mapping)
        else ""
    )
    final_review = (
        "## 研究结论\n\n"
        "本次输出仅用于公司研究与学习复盘，不构成交易指令；系统不生成订单、"
        "买卖数量、目标仓位或执行时间。\n\n"
        f"证据状态：{evidence_status}。请结合分析师报告、风险讨论和后续验证条件持续复核。"
        f"{holding_line}"
    )
    risk_state = state["risk_debate_state"]
    updated_risk_state = {
        "judge_decision": final_review,
        "history": risk_state["history"],
        "aggressive_history": risk_state["aggressive_history"],
        "conservative_history": risk_state["conservative_history"],
        "neutral_history": risk_state["neutral_history"],
        "latest_speaker": "Judge",
        "current_aggressive_response": risk_state["current_aggressive_response"],
        "current_conservative_response": risk_state["current_conservative_response"],
        "current_neutral_response": risk_state["current_neutral_response"],
        "risk_signals": risk_state.get("risk_signals", []),
        "count": risk_state["count"],
    }
    result = {
        "risk_debate_state": updated_risk_state,
        "final_trade_decision": final_review,
        "evidence_status": evidence_status,
        "allowed_actions": [],
        "clamp_events": [],
        "execution_outcome": None,
        "holding_review_summary": holding_summary,
    }
    if holding_summary is not None:
        result["reader_public_output"] = {
            "kind": "portfolio",
            "value": {
                "kind": "learning_holding_review",
                "holding_review": holding_summary,
            },
        }
    return result
