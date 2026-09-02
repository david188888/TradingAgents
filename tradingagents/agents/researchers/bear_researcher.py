from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    opponent_argument_or_opening,
)
from tradingagents.evaluation.source_alignment import render_source_alignment_summary
from tradingagents.research import render_research_dossier
from tradingagents.research.delegation import bounded_public_report_text
from tradingagents.skills import (
    build_role_skill_prompt,
    build_skill_trigger_context,
    emit_methodology_artifact,
)


def _build_bear_prompt(
    *,
    target_label: str,
    instrument_context: str,
    alignment_line: str,
    market_research_report: str,
    sentiment_report: str,
    news_report: str,
    fundamentals_label: str,
    fundamentals_report: str,
    history: str,
    opposing_response: str,
    skill_prompt: str,
    language_instruction: str,
) -> str:
    """Build the bear researcher prompt, branching on opening vs rebuttal turn."""
    is_opening = not opposing_response.strip()

    # Mirror of the bull researcher: reports are static per run, so opening
    # turns embed them verbatim and rebuttals read bounded excerpts (shared
    # lens budget) instead of re-sending four full reports every turn.
    if is_opening:
        reports_section = f"""{alignment_line}Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}"""
    else:
        reports_section = f"""{alignment_line}Market research report: {bounded_public_report_text(market_research_report)}
Social media sentiment report: {bounded_public_report_text(sentiment_report)}
Latest world affairs news: {bounded_public_report_text(news_report)}
{fundamentals_label}: {bounded_public_report_text(fundamentals_report)}"""

    if is_opening:
        task_section = f"""Your task is to deliver the opening bear case against investing in the {target_label}. Present a well-reasoned argument emphasizing risks, challenges, and negative indicators.

Key points to focus on:
- Risks and Challenges: Highlight factors like market saturation, financial instability, or macro threats that could hinder performance.
- Competitive Weaknesses: Emphasize vulnerabilities such as weaker market positioning, declining innovation, or threats from competitors.
- Negative Indicators: Use evidence from financial data, market trends, or recent adverse news to support your position.
- Single speaker: Write only as the Bear Analyst. Do not fabricate dialogue for any other participant, and do not address a moderator — this is a direct exchange with the bull analyst.
- No self-label: Do not prepend a speaker label such as "Bear Analyst:" — your role is already known from context."""
        history_line = ""
        opposing_line = ""
    else:
        task_section = f"""Your task is to rebut the bull analyst's latest argument and strengthen the bear case against investing in the {target_label}.

Key points to focus on:
- Risks and Challenges: Highlight factors like market saturation, financial instability, or macro threats that could hinder performance.
- Competitive Weaknesses: Emphasize vulnerabilities such as weaker market positioning, declining innovation, or threats from competitors.
- Negative Indicators: Use evidence from financial data, market trends, or recent adverse news to support your position.
- Bull Counterpoints: Critically analyze the bull argument with specific data and sound reasoning, exposing weaknesses or over-optimistic assumptions.
- Engagement: Respond directly to the bull analyst's points. Debate effectively rather than just listing facts.
- Single speaker: Write only as the Bear Analyst. Do not fabricate dialogue for any other participant, and do not address a moderator — this is a direct exchange.
- No self-label: Do not prepend a speaker label such as "Bear Analyst:" — your role is already known from context."""
        history_line = f"Conversation history of the debate:\n{history}\n"
        opposing_line = f"Last bull analyst argument:\n{opposing_response}\n"

    return f"""You are the Bear Analyst in a direct debate with the Bull Analyst.
{task_section}

Resources available:
{instrument_context}
{reports_section}
{history_line}{opposing_line}Use the information above to deliver your argument.
""" + language_instruction + skill_prompt


def create_bear_researcher(llm):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        current_response = opponent_argument_or_opening(
            investment_debate_state.get("current_response", ""), "bull analyst"
        )
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        instrument_context = get_instrument_context_from_state(state)
        asset_type = state.get("asset_type", "stock")
        target_label = "stock" if asset_type == "stock" else "asset"
        fundamentals_label = (
            "Company fundamentals report"
            if asset_type == "stock"
            else "Asset fundamentals report (may be unavailable for crypto)"
        )
        skill_trigger_text = build_skill_trigger_context(
            market_research_report,
            sentiment_report,
            news_report,
            fundamentals_report,
            history,
            current_response,
        )
        emit_methodology_artifact("bear_researcher", trigger_text=skill_trigger_text)

        alignment_summary = render_source_alignment_summary(state.get("evidence_ledger"))
        alignment_line = (
            f"Evidence source alignment: {alignment_summary}\n"
            if alignment_summary is not None
            else ""
        )

        prompt = _build_bear_prompt(
            target_label=target_label,
            instrument_context=instrument_context,
            alignment_line=alignment_line,
            market_research_report=market_research_report,
            sentiment_report=sentiment_report,
            news_report=news_report,
            fundamentals_label=fundamentals_label,
            fundamentals_report=fundamentals_report,
            history=history,
            opposing_response=current_response,
            skill_prompt=build_role_skill_prompt(
                "bear_researcher", trigger_text=skill_trigger_text
            ),
            language_instruction=get_language_instruction(),
        )

        prompt += (
            "\nStructured research dossier (code-owned; unknown/not_assessed are not bull evidence):\n"
            + render_research_dossier(state.get("research_dossier"))
            + "\nChallenge each unsupported transmission edge instead of treating missing data as bearish.\n"
        )

        response = llm.invoke(prompt)
        raw_response = response.content

        labelled = f"Bear Analyst: {raw_response}"

        new_investment_debate_state = {
            "history": history + "\n" + labelled,
            "bear_history": bear_history + "\n" + raw_response,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": raw_response,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node
