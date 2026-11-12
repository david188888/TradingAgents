"""Capability outcomes and the in-memory source draft used to build V9 evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

CAP_IDENTITY = "security_identity"
CAP_EVENT_COVERAGE = "event_coverage"
CAP_PRICE = "price_history"
CAP_FUNDAMENTALS = "fundamentals"

REQUIRED_CAPABILITIES = (CAP_IDENTITY, CAP_EVENT_COVERAGE, CAP_PRICE, CAP_FUNDAMENTALS)


class CapabilityStatus(str, Enum):
    """Whether a capability produced usable evidence for this run.

    ``UNAVAILABLE`` and ``COVERAGE_UNKNOWN`` are deliberately distinct from
    "no matching records": an empty list is a legitimate answer only when the
    source proved it looked and found nothing.
    """

    QUALIFIED = "qualified"
    COVERED_NO_MATCH = "covered_no_matching"
    UNAVAILABLE = "unavailable"
    COVERAGE_UNKNOWN = "coverage_unknown"
    PARTIAL = "partial"
    NOT_APPLICABLE = "not_applicable"

    @property
    def is_usable(self) -> bool:
        return self in {
            CapabilityStatus.QUALIFIED,
            CapabilityStatus.COVERED_NO_MATCH,
            CapabilityStatus.NOT_APPLICABLE,
        }


class FrozenCapability(BaseModel):
    """One capability's result, as it stood when the draft was frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: str = Field(min_length=1, max_length=120)
    status: CapabilityStatus
    required: bool = False
    # Why this status. Always populated: a status a reader cannot audit is a
    # status they have to take on trust.
    reason: str = Field(min_length=1, max_length=400)
    degradations: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    # Source provenance, one entry per source that answered. Empty for a
    # capability that was not applicable.
    sources: tuple[str, ...] = ()
    detail: Mapping[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unusable_capability_states_why(self) -> FrozenCapability:
        # A failed capability with no recorded cause is indistinguishable from
        # a bug, and the run would publish an unexplained gap. An optional
        # capability that was never applicable is exempt: nothing went wrong,
        # and inventing a degradation for it would be noise.
        if (
            not self.status.is_usable
            and not (self.degradations or self.detail)
            and self.status is not CapabilityStatus.NOT_APPLICABLE
        ):
            raise ValueError("an unusable capability must record why it is unusable")
        if self.status in {
            CapabilityStatus.UNAVAILABLE,
            CapabilityStatus.COVERAGE_UNKNOWN,
            CapabilityStatus.PARTIAL,
        } and not self.reason:
            raise ValueError("a degraded capability must carry a reason")
        return self


class FrozenEvidenceDraft(BaseModel):
    """Collected evidence and coverage before building the saved EvidenceRecord."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    cutoff: str = Field(min_length=10, max_length=10)
    capabilities: tuple[FrozenCapability, ...] = ()
    evidence: tuple[Mapping[str, Any], ...] = ()

    @model_validator(mode="after")
    def _validate_cutoff(self) -> FrozenEvidenceDraft:
        if self.cutoff != date.fromisoformat(self.cutoff).isoformat():
            raise ValueError("cutoff must be an ISO calendar date")
        return self

    def capability(self, name: str) -> FrozenCapability | None:
        return next((item for item in self.capabilities if item.capability == name), None)

    def status_of(self, name: str) -> CapabilityStatus:
        found = self.capability(name)
        return found.status if found is not None else CapabilityStatus.UNAVAILABLE


@dataclass
class FreezeInputs:
    """Mutable collector inputs before source admission is complete."""

    run_id: str
    ticker: str
    cutoff: str
    capabilities: list[FrozenCapability] = field(default_factory=list)
    evidence: list[Mapping[str, Any]] = field(default_factory=list)


def freeze_evidence_draft(inputs: FreezeInputs) -> FrozenEvidenceDraft:
    capabilities = list(inputs.capabilities)
    produced = {item.capability for item in capabilities}
    for name in REQUIRED_CAPABILITIES:
        if name not in produced:
            capabilities.append(
                FrozenCapability(
                    capability=name,
                    status=CapabilityStatus.UNAVAILABLE,
                    required=True,
                    reason="capability_not_produced_by_the_plan",
                    degradations=("capability_not_attempted",),
                )
            )
    return FrozenEvidenceDraft(
        run_id=inputs.run_id,
        ticker=inputs.ticker,
        cutoff=inputs.cutoff,
        capabilities=tuple(sorted(capabilities, key=lambda item: item.capability)),
        evidence=tuple(dict(item) for item in inputs.evidence),
    )
