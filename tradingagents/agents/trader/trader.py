"""Trader: turns the Research Manager's investment plan into a concrete transaction proposal."""

from __future__ import annotations

import functools

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import TraderProposal, render_trader_proposal
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)


def create_trader(llm):
    structured_llm = bind_structured(llm, TraderProposal, "Trader")

    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = get_instrument_context_from_state(state)
        investment_plan = state["investment_plan"]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a trading agent analyzing market data to make investment decisions. "
                    "Based on your analysis, provide a specific recommendation to buy, sell, or hold. "
                    "Anchor your reasoning in the analysts' reports and the research plan. "
                    + NO_EXTERNAL_TOOLS
                    + get_language_instruction()
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Based on a comprehensive analysis by a team of analysts, here is an investment "
                    f"plan tailored for {company_name}. {instrument_context} This plan incorporates "
                    f"insights from current technical market trends, macroeconomic indicators, and "
                    f"social media sentiment. Use this plan as a foundation for evaluating your next "
                    f"trading decision.\n\nProposed Investment Plan: {investment_plan}\n\n"
                    f"Leverage these insights to make an informed and strategic decision."
                ),
            },
        ]

        trader_plan, trader_public_output = _render_trader_plan(structured_llm, llm, messages)
        result = {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }
        if trader_public_output is not None:
            result["reader_public_output"] = {
                "kind": "trader",
                "value": trader_public_output.model_dump(mode="json"),
            }
        return result

    return functools.partial(trader_node, name="Trader")


def _render_trader_plan(structured_llm, llm, messages) -> tuple[str, TraderProposal | None]:
    if structured_llm is not None:
        try:
            proposal = structured_llm.invoke(messages)
            if not isinstance(proposal, TraderProposal):
                raise ValueError("structured output did not produce TraderProposal")
            return render_trader_proposal(proposal), proposal
        except Exception:
            pass
    return (
        invoke_structured_or_freetext(None, llm, messages, render_trader_proposal, "Trader"),
        None,
    )
