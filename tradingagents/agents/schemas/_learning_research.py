"""Structured, non-transactional research synthesis for learning modes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LearningScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=120)
    condition: str = Field(min_length=1, max_length=500)
    implication: str = Field(min_length=1, max_length=600)


class HoldingThesisAssessment(BaseModel):
    """Public assessment of a user-provided thesis, never a trade direction."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: Literal["supported", "challenged", "not_assessable"]
    rationale: str = Field(min_length=1, max_length=800)
    current_research_hypothesis: str = Field(min_length=1, max_length=800)


class LearningResearchSummary(BaseModel):
    """Public report content without allocation, order, or execution fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    research_tilt: Literal["favorable", "neutral", "cautious", "insufficient_evidence"]
    confidence: float = Field(ge=0, le=1)
    facts: tuple[str, ...] = Field(default=(), max_length=5)
    inferences: tuple[str, ...] = Field(default=(), max_length=4)
    unknowns: tuple[str, ...] = Field(default=(), max_length=4)
    upside: LearningScenario
    base: LearningScenario
    downside: LearningScenario
    catalysts: tuple[str, ...] = Field(default=(), max_length=4)
    invalidation_conditions: tuple[str, ...] = Field(default=(), max_length=4)
    next_review: str = Field(min_length=1, max_length=500)
    holding_thesis_assessment: HoldingThesisAssessment | None = None


def render_learning_research_summary(summary: LearningResearchSummary) -> str:
    """Render the schema as a readable research report, never a trade plan."""
    lines = [
        "## 研究倾向",
        "",
        f"- 倾向：{summary.research_tilt}",
        f"- 置信度：{summary.confidence:.0%}",
        "- 本报告用于学习与复盘，不构成交易指令；不包含仓位、数量、订单或执行时间。",
        "",
        "## 事实",
        *(_bullets(summary.facts) or ["- 当前没有足够的可验证事实。"]),
        "",
        "## 推论",
        *(_bullets(summary.inferences) or ["- 当前不作额外推论。"]),
        "",
        "## 未知与待验证",
        *(_bullets(summary.unknowns) or ["- 没有额外未知项被记录。"]),
        "",
        "## 三种情景",
        *_scenario_lines("上行", summary.upside),
        *_scenario_lines("基准", summary.base),
        *_scenario_lines("下行", summary.downside),
        "",
        "## 催化剂与失效条件",
        "### 催化剂",
        *(_bullets(summary.catalysts) or ["- 暂无已验证催化剂。"]),
        "### 失效条件",
        *(_bullets(summary.invalidation_conditions) or ["- 暂无额外失效条件。"]),
        "",
        "## 下次复核",
        summary.next_review,
    ]
    if summary.holding_thesis_assessment is not None:
        assessment = summary.holding_thesis_assessment
        lines += [
            "",
            "## 持仓理由复核",
            f"- 当前证据评估：{assessment.status}",
            f"- 依据：{assessment.rationale}",
            f"- 当前可观察研究假设：{assessment.current_research_hypothesis}",
        ]
    return "\n".join(lines)


def _bullets(items: tuple[str, ...]) -> list[str]:
    return [f"- {item}" for item in items]


def _scenario_lines(label: str, scenario: LearningScenario) -> list[str]:
    return [
        f"### {label}：{scenario.title}",
        f"- 条件：{scenario.condition}",
        f"- 研究含义：{scenario.implication}",
    ]
