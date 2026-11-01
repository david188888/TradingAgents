"""Consumer-neutral inputs and successful outputs for shared graph execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from threading import Event
from typing import Any, Literal


@dataclass(frozen=True)
class AnalysisRequest:
    """The current A-share company research request shared by CLI and Web."""

    ticker: str
    analysis_date: str
    effective_config: Mapping[str, Any] = field(default_factory=dict)
    research_question: str | None = None
    research_profile: Literal["evidence_v1"] = "evidence_v1"

    def __post_init__(self) -> None:
        from tradingagents.research.native_evidence_policy import is_native_stock_ticker
        if not is_native_stock_ticker(self.ticker):
            raise ValueError("research requires A-share common stocks")
        try:
            date.fromisoformat(self.analysis_date)
        except ValueError as exc:
            raise ValueError("analysis_date must use YYYY-MM-DD") from exc
        if self.research_profile != "evidence_v1":
            raise ValueError("unsupported research profile")
        if self.research_question is not None:
            if not isinstance(self.research_question, str):
                raise ValueError("research_question must be a string")
            question = self.research_question.strip() or None
            if question is not None and len(question) > 400:
                raise ValueError("research_question cannot exceed 400 characters")
            object.__setattr__(self, "research_question", question)

    @property
    def mode(self) -> Literal["company_research"]:
        return "company_research"

    @property
    def evidence_policy(self):
        from tradingagents.research.native_evidence_policy import NativeEvidencePolicyV1
        return NativeEvidencePolicyV1()

    @property
    def policy_version(self) -> str:
        return self.evidence_policy.policy_version

    def profile_identity(self) -> dict[str, object]:
        return {"research_profile": self.research_profile,
            "evidence_policy_version": self.policy_version,
            "evidence_policy": self.evidence_policy.as_identity(),
            "research_question": self.research_question}


@dataclass(frozen=True)
class AnalysisResult:
    final_state: Mapping[str, Any]
    final_signal: str

    def __post_init__(self) -> None:
        if not self.final_signal.strip():
            raise ValueError("successful AnalysisResult requires final_signal")


class AnalysisCancelled(Exception):
    def __init__(self, partial_state: Mapping[str, Any] | None = None):
        self.partial_state = partial_state
        super().__init__("analysis cancelled")


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(
        self,
        partial_state: Mapping[str, Any] | None = None,
    ) -> None:
        if self.is_cancelled:
            raise AnalysisCancelled(partial_state)
