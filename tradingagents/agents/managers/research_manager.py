"""Research Manager: turns the bull/bear debate into a structured investment plan for the trader."""

from __future__ import annotations

from tradingagents.agents.schemas import (
    LearningResearchSummary,
    ResearchPlan,
    render_learning_research_summary,
    render_research_plan,
)
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.observability.errors import ObservationError
from tradingagents.research import render_research_dossier
from tradingagents.research.delegation import (
    ResearchDelegationError,
    ResearchDelegationExecutor,
    ResearchDelegationRequest,
    build_default_report_lens_context,
    build_default_report_lens_delegation,
    render_delegation_results,
)


def create_research_manager(
    llm,
    *,
    delegation_executor: ResearchDelegationExecutor | None = None,
    use_default_report_lenses: bool = False,
):
    """Create the research judge with optional bounded read-only fan-out.

    A caller may inject a small allowlist of read-only tools.  The normal graph
    instead enables ``use_default_report_lenses``: code-owned, deterministic
    fan-out over already-published analyst reports.  It adds no recursive
    agent, arbitrary tool choice, or additional model turn.  Both paths make
    one structured decision, then append only public findings to the hand-off
    consumed by Trader and PM.
    """
    structured_llm = bind_structured(llm, ResearchPlan, "Research Manager")

    def research_manager_node(state) -> dict:
        if state.get("mode") in {"company_research", "holding_review"}:
            return _learning_research_result(state, llm)
        instrument_context = get_instrument_context_from_state(state)
        history = state["investment_debate_state"].get("history", "")
        report_lens_context = (
            build_default_report_lens_context(state) if use_default_report_lenses else ""
        )

        investment_debate_state = state["investment_debate_state"]

        evidence_status = state.get("evidence_status", "")
        evidence_report = state.get("evidence_report", "")
        evidence_confidence_line = _extract_confidence_line(evidence_report)
        conviction_cap = _conviction_cap_for_evidence(evidence_status, evidence_confidence_line)

        delegation_instruction = ""
        if delegation_executor is not None:
            tool_names = ", ".join(delegation_executor.allowed_tool_names)
            delegation_instruction = (
                "\nYou may request up to three independent read-only evidence lookups in "
                f"delegation_tasks. The only permitted tool names are: {tool_names}. "
                "Each lookup must answer a distinct factual subquestion. Do not request "
                "delegation by a child, and never include private reasoning, prompts, or "
                "raw traces in a task.\n"
            )

        prompt = f"""As the Research Manager and debate facilitator, your role is to critically evaluate this round of debate and deliver a clear, actionable investment plan for the trader.

{instrument_context}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction in the bull thesis; recommend taking or growing the position
- **Overweight**: Constructive view; recommend gradually increasing exposure
- **Hold**: Balanced view; recommend maintaining the current position
- **Underweight**: Cautious view; recommend trimming exposure
- **Sell**: Strong conviction in the bear thesis; recommend exiting or avoiding the position

Commit to a clear stance whenever the debate's strongest arguments warrant one; reserve Hold for situations where the evidence on both sides is genuinely balanced.
{conviction_cap}

Present your verdict under your own identity as the Research Manager. Do not style yourself as a "Moderator" or address a moderator — there is no moderator role; you are the judge of this debate.

---

**Structured Research Dossier (code-owned):**
{render_research_dossier(state.get("research_dossier"))}

Rules: unknown/not_assessed is not bear evidence; industry/comparable evidence cannot prove subject-company orders; earnings uplift and multiple rerating are separate decisions.

---

**Debate History:**
{history}
{report_lens_context}""" + delegation_instruction + NO_EXTERNAL_TOOLS + get_language_instruction()

        default_executor: ResearchDelegationExecutor | None = None
        default_requests: tuple[ResearchDelegationRequest, ...] = ()
        if use_default_report_lenses and delegation_executor is None:
            default_executor, default_requests = build_default_report_lens_delegation(state)

        investment_plan, research_public_output = _render_plan_with_delegation(
            structured_llm,
            llm,
            prompt,
            delegation_executor or default_executor,
            requests=default_requests if default_executor is not None else None,
        )

        new_investment_debate_state = {
            "judge_decision": investment_plan,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": investment_plan,
            "count": investment_debate_state["count"],
        }

        result = {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
        }
        if research_public_output is not None:
            result["reader_public_output"] = {
                "kind": "research",
                "value": research_public_output.model_dump(mode="json"),
            }
        return result

    return research_manager_node


def _learning_research_result(state, llm) -> dict:
    """Keep the legacy research judge from emitting a transaction proposal."""
    debate_state = state["investment_debate_state"]
    evidence_status = str(state.get("evidence_status") or "unknown")
    research_summary, public_summary = _render_learning_research(state, llm, evidence_status)
    result = {
        "investment_debate_state": {
            "judge_decision": research_summary,
            "history": debate_state.get("history", ""),
            "bear_history": debate_state.get("bear_history", ""),
            "bull_history": debate_state.get("bull_history", ""),
            "current_response": research_summary,
            "count": debate_state["count"],
        },
        "investment_plan": research_summary,
        "research_case_candidate": {"evidence_verdict": evidence_status},
    }
    # The rendered report remains available to downstream graph nodes, while
    # the same validated object is promoted only after the graph checkpoint
    # commits.  Reader never has to infer a conclusion from Markdown.
    if public_summary is not None:
        result["reader_public_output"] = {
            "kind": "research",
            "value": {
                "kind": "learning_research_summary",
                "summary": public_summary.model_dump(mode="json"),
            },
        }
    return result


def _render_learning_research(
    state, llm, evidence_status: str
) -> tuple[str, LearningResearchSummary | None]:
    """Use one bounded synthesis turn; fall back to an explicit abstention."""
    structured_llm = bind_structured(llm, LearningResearchSummary, "Research Manager")
    if structured_llm is None:
        return _learning_research_fallback(evidence_status), None
    mode = state.get("mode")
    holding_context = state.get("holding_context") if mode == "holding_review" else None
    prompt = f"""你是学习型公司研究的 Research Manager。请只根据下方已给出的分析师报告和辩论，生成结构化研究摘要。

硬性边界：这不是交易系统。不得建议或描述买入、卖出、持有、仓位比例、目标仓位、数量、订单、价格指令或执行时间。只输出研究倾向、事实、推论、未知、三种情景、催化剂、失效条件与下一次复核。

证据状态：{evidence_status}
持仓复盘上下文（若有）：{holding_context!r}

市场报告：{state.get("market_report", "")}
基本面报告：{state.get("fundamentals_report", "")}
新闻报告：{state.get("news_report", "")}
情绪报告：{state.get("sentiment_report", "")}
研究辩论：{state.get("investment_debate_state", {}).get("history", "")}

持仓复盘规则：只有在持仓上下文中存在 original_thesis 时才填写 holding_thesis_assessment；
assessment 必须说明当前证据是 supported、challenged 还是 not_assessable，并给出可观察的当前研究假设。
若 original_thesis 缺失，绝不推测用户买入理由，也不要填写该字段。

没有证据时明确列入 unknowns，并将 research_tilt 设为 insufficient_evidence。"""
    try:
        result = structured_llm.invoke(prompt)
        if not isinstance(result, LearningResearchSummary):
            result = LearningResearchSummary.model_validate(result)
        return render_learning_research_summary(result), result
    except Exception:
        return _learning_research_fallback(evidence_status), None


def _learning_research_fallback(evidence_status: str) -> str:
    return (
        "## 研究倾向\n\n"
        "- 倾向：insufficient_evidence\n"
        "- 置信度：0%\n"
        "- 本报告用于学习与复盘，不构成交易指令；不包含仓位、数量、订单或执行时间。\n\n"
        "## 未知与待验证\n\n"
        f"- 证据状态：{evidence_status}。需要等待可验证的市场、基本面、新闻或情绪事实。\n\n"
        "## 下次复核\n\n"
        "在新的公告、业绩或风险证据出现后重新进行研究复核。"
    )


def _render_plan_with_delegation(
    structured_llm,
    llm,
    prompt: str,
    delegation_executor: ResearchDelegationExecutor | None,
    *,
    requests: tuple[ResearchDelegationRequest, ...] | None = None,
) -> tuple[str, ResearchPlan | None]:
    """Keep the rendered handoff and its public typed source from one LLM turn."""
    if structured_llm is None:
        rendered = invoke_structured_or_freetext(
            None, llm, prompt, render_research_plan, "Research Manager"
        )
        return _append_delegation_to_freetext(rendered, delegation_executor, requests), None
    try:
        plan = structured_llm.invoke(prompt)
        if not isinstance(plan, ResearchPlan):
            raise ValueError("structured output did not produce ResearchPlan")
    except (ObservationError, AssertionError):
        raise
    except Exception:
        return (
            invoke_structured_or_freetext(
                None, llm, prompt, render_research_plan, "Research Manager"
            ),
            None,
        )

    selected_requests = (
        requests if requests is not None else tuple(task.to_domain() for task in plan.delegation_tasks)
    )
    if delegation_executor is None or not selected_requests:
        return render_research_plan(plan), plan
    try:
        results = delegation_executor.execute(selected_requests)
    except ResearchDelegationError:
        # Delegation failure does not invalidate the primary public judgement.
        return render_research_plan(plan), plan
    return render_research_plan(plan, results), plan


def _append_delegation_to_freetext(
    rendered: str,
    delegation_executor: ResearchDelegationExecutor | None,
    requests: tuple[ResearchDelegationRequest, ...] | None,
) -> str:
    """Keep deterministic default lenses available to non-structured providers."""
    if delegation_executor is None or not requests:
        return rendered
    try:
        delegation = render_delegation_results(delegation_executor.execute(requests))
    except ResearchDelegationError:
        return rendered
    return f"{rendered}\n\n{delegation}" if delegation else rendered


def _extract_confidence_line(evidence_report: str) -> str | None:
    """Extract the 'Evidence confidence:' line from an evidence steward report."""
    if not evidence_report:
        return None
    for line in evidence_report.splitlines():
        if line.strip().startswith("Evidence confidence:"):
            return line.strip()
    return None


def _conviction_cap_for_evidence(
    evidence_status: str, confidence_line: str | None
) -> str:
    """Return a prompt fragment capping conviction when evidence is weak.

    Returns an empty string when evidence is PASS-level. Uses the existing
    rating-scale vocabulary (Buy/Sell → Overweight/Underweight) rather than
    inventing a parallel notion.
    """
    if evidence_status == "LOW_CONFIDENCE":
        detail = confidence_line or "evidence below sufficiency thresholds"
        return (
            f"\n**Evidence Confidence Cap:** {detail}. Because evidence coverage "
            "is below the sufficiency threshold, you MUST cap your rating at "
            "Overweight (bull-leaning) or Underweight (bear-leaning) — do NOT "
            "issue Buy or Sell. State explicitly in your rationale that evidence "
            "confidence is LOW and the rating is capped accordingly.\n"
        )
    return ""
