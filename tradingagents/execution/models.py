"""Consumer-neutral inputs and successful outputs for shared graph execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from threading import Event
from typing import Any, Literal

from tradingagents.analysts import ANALYST_WIRE_KEYS

ResearchMode = Literal["company_research", "holding_review"]
# Omitting research_profile is exactly equivalent to "classic"; the default is
# applied by normalize_research_profile so it cannot drift between entry points.
ResearchProfile = Literal["classic", "catalyst_v1"]
# Typed learning modes produce research narratives, not trade outcomes: they
# must not write into the trading-reflection memory (see AnalysisRunner).
LEARNING_MODES: frozenset[str] = frozenset({"company_research", "holding_review"})
HoldingSource = Literal["user_provided", "legacy_portfolio"]


@dataclass(frozen=True)
class HoldingContext:
    """Normalized, non-secret facts for a learning-oriented holding review.

    This intentionally is not a portfolio or execution context.  It captures
    only the target holding facts a reader may discuss and never contains
    tradable quantities, limits, or inferred account facts.
    """

    ticker: str
    quantity: float
    average_cost: float
    cash: float | None
    total_account_value: float | None
    currency: str | None
    facts_as_of: str
    original_thesis: str | None
    source: HoldingSource

    def __post_init__(self) -> None:
        if not self.ticker.strip():
            raise ValueError("holding ticker is required")
        if not isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("holding quantity must be positive")
        if not isfinite(self.average_cost) or self.average_cost <= 0:
            raise ValueError("holding average_cost must be positive")
        if self.cash is not None and (not isfinite(self.cash) or self.cash < 0):
            raise ValueError("holding cash must be non-negative")
        if self.total_account_value is not None and (
            not isfinite(self.total_account_value) or self.total_account_value <= 0
        ):
            raise ValueError("holding total_account_value must be positive")
        if self.currency is not None and (
            len(self.currency) != 3 or not self.currency.isalpha()
        ):
            raise ValueError("holding currency must be a three-letter code")
        try:
            date.fromisoformat(self.facts_as_of)
        except ValueError as exc:
            raise ValueError("holding facts_as_of must use YYYY-MM-DD") from exc
        if self.source not in {"user_provided", "legacy_portfolio"}:
            raise ValueError("unsupported holding source")


def holding_context_from_dict(value: Mapping[str, Any]) -> HoldingContext:
    """Rehydrate the explicit snapshot contract without accepting omissions."""
    return HoldingContext(
        ticker=str(value["ticker"]),
        quantity=float(value["quantity"]),
        average_cost=float(value["average_cost"]),
        cash=float(value["cash"]) if value.get("cash") is not None else None,
        total_account_value=(
            float(value["total_account_value"])
            if value.get("total_account_value") is not None
            else None
        ),
        currency=str(value["currency"]) if value.get("currency") is not None else None,
        facts_as_of=str(value["facts_as_of"]),
        original_thesis=(
            str(value["original_thesis"])
            if value.get("original_thesis") is not None
            else None
        ),
        source=str(value["source"]),
    )


@dataclass(frozen=True)
class AnalysisRequest:
    ticker: str
    analysis_date: str
    asset_type: Literal["stock", "crypto"] = "stock"
    selected_analysts: tuple[str, ...] = ANALYST_WIRE_KEYS
    max_debate_rounds: int = 1
    max_risk_discuss_rounds: int = 1
    effective_config: Mapping[str, Any] = field(default_factory=dict)
    horizon: Literal["short", "medium", "long"] = "medium"
    mode: ResearchMode = "company_research"
    holding_context: HoldingContext | None = None
    # Execution profile. "classic" runs the existing bull/bear graph under
    # horizon-policy-v2; "catalyst_v1" runs the bounded research flow under
    # catalyst-evidence-policy-v1. Omission is "classic".
    research_profile: ResearchProfile = "classic"
    # Frozen evidence policy parameters for catalyst_v1. None for classic,
    # which keeps horizon-policy-v2 and must not carry this bundle.
    #
    # Annotated structurally rather than as CatalystEvidencePolicyV1: that
    # class lives in tradingagents.research.catalyst_evidence_policy, whose
    # package import pulls holding_review, which imports this module. A
    # resolvable class annotation would therefore make typing.get_type_hints
    # (and every consumer of it, e.g. tests/test_frontend_wire_contract.py)
    # fail with NameError the first time it runs, because the deferred runtime
    # imports in __post_init__ are not on that code path. The shape is
    # asserted in tests/test_research_profile_contract.py, and
    # __post_init__ rejects anything that is not the real policy object, so a
    # value can never reach the wire under the wrong type.
    catalyst_policy: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        # Imported here: tradingagents.research.__init__ imports this module
        # (holding_review), so a module-level import would be circular.
        from tradingagents.research.catalyst_evidence_policy import (
            CATALYST_V1_PROFILE,
            CLASSIC_PROFILE,
            PROFILE_POLICY_VERSIONS,
            CatalystEvidencePolicyV1,
            catalyst_evidence_policy_v1,
            normalize_research_profile,
        )

        if not self.ticker.strip():
            raise ValueError("ticker is required")
        try:
            date.fromisoformat(self.analysis_date)
        except ValueError as exc:
            raise ValueError("analysis_date must use YYYY-MM-DD") from exc
        if not self.selected_analysts:
            raise ValueError("at least one analyst is required")
        unknown = set(self.selected_analysts) - set(ANALYST_WIRE_KEYS)
        if unknown:
            raise ValueError(f"unknown analyst keys: {', '.join(sorted(unknown))}")
        if len(set(self.selected_analysts)) != len(self.selected_analysts):
            raise ValueError("selected_analysts must not contain duplicates")
        if self.max_debate_rounds < 1 or self.max_risk_discuss_rounds < 1:
            raise ValueError("debate and risk rounds must be positive")
        if self.horizon not in {"short", "medium", "long"}:
            raise ValueError(f"unsupported investment horizon: {self.horizon}")
        if self.mode not in {"company_research", "holding_review"}:
            raise ValueError(f"unsupported research mode: {self.mode}")
        if self.mode == "company_research" and self.holding_context is not None:
            raise ValueError("company_research cannot include holding_context")
        if self.mode == "holding_review" and self.holding_context is None:
            raise ValueError("holding_review requires holding_context")
        profile = normalize_research_profile(self.research_profile)
        if profile not in PROFILE_POLICY_VERSIONS:
            raise ValueError(f"unsupported research profile: {profile}")
        if profile == CATALYST_V1_PROFILE and self.catalyst_policy is None:
            object.__setattr__(
                self, "catalyst_policy", catalyst_evidence_policy_v1()
            )
        if profile == CLASSIC_PROFILE and self.catalyst_policy is not None:
            raise ValueError("classic research profile cannot carry a catalyst policy")
        if self.catalyst_policy is not None and not isinstance(
            self.catalyst_policy, CatalystEvidencePolicyV1
        ):
            # The dataclass field is annotated structurally (see the field
            # comment), so the concrete class is enforced here rather than by
            # the annotation. A hand-rolled dict cannot masquerade as a policy.
            raise ValueError("catalyst_policy must be a CatalystEvidencePolicyV1 instance")

    @property
    def policy_version(self) -> str:
        """The evidence policy that governs this run.

        This is a lookup, not a runtime contract selection.  It must never be
        used to widen RuntimePolicyVersion in runtime/contracts.py.
        """
        from tradingagents.research.catalyst_evidence_policy import (
            PROFILE_POLICY_VERSIONS,
            normalize_research_profile,
        )

        return PROFILE_POLICY_VERSIONS[normalize_research_profile(self.research_profile)]

    def profile_identity(self) -> dict[str, object]:
        """Fingerprint-facing projection of profile + its evidence policy.

        Returns ``{}`` for the ``classic`` default so that every fingerprint
        byte produced before this field existed is reproduced exactly.  Old
        checkpoints therefore stay resumable without recomputation, and the
        frozen classic digest is not silently invalidated by this release.

        A non-classic profile always emits its own evidence policy version, so
        a catalyst_v1 checkpoint can never be compared equal to a classic one.
        """
        from tradingagents.research.catalyst_evidence_policy import normalize_research_profile

        profile = normalize_research_profile(self.research_profile)
        if profile == "classic":
            return {}
        identity: dict[str, object] = {
            "research_profile": profile,
            "evidence_policy_version": self.policy_version,
        }
        if self.catalyst_policy is not None:
            identity["catalyst_policy"] = self.catalyst_policy.as_identity()
        return identity


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
