"""Versioned, deterministic data requirements for the ``catalyst_v1`` profile.

This module is deliberately independent from :mod:`tradingagents.research.horizon_policy`.

``horizon-policy-v2`` (and the internal ``horizon-policy-v3`` test gate) describe the
``classic`` graph's data window plan and are consumed through
``tradingagents.runtime.contracts.RuntimePolicyVersion``, a horizon-gating enum
read by five modules.  The ``catalyst-evidence-policy-v1`` policy is a different
contract with a different meaning: it bounds what the new bounded-research
profile is allowed to fetch and how coverage must be proven.  Adding its version
string to the horizon enum would silently turn on the ``horizon-policy-v3`` test
gate, so the two never share a field, a module, or a literal.

The version string below is a data requirement constant only.  It records which
window parameters a run was created under so that resume compatibility can
distinguish runs whose evidence base actually differs.  It does not select a
runtime contract family.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The evidence policy version string.  Independent from RuntimePolicyVersion in
# ``tradingagents.runtime.contracts`` on purpose -- see the module docstring.
CATALYST_EVIDENCE_POLICY_VERSION = "catalyst-evidence-policy-v1"

CatalystEvidencePolicyVersion = Literal["catalyst-evidence-policy-v1"]

ResearchProfile = Literal["classic", "catalyst_v1"]
RESEARCH_PROFILES: tuple[str, ...] = ("classic", "catalyst_v1")
CLASSIC_PROFILE = "classic"
CATALYST_V1_PROFILE = "catalyst_v1"

# The only profile that runs under the new evidence policy.  ``classic`` keeps
# horizon-policy-v2 exactly as it is today.
PROFILE_POLICY_VERSIONS: dict[str, str] = {
    CLASSIC_PROFILE: "horizon-policy-v2",
    CATALYST_V1_PROFILE: CATALYST_EVIDENCE_POLICY_VERSION,
}


def normalize_research_profile(value: object) -> str:
    """Omission and explicit ``classic`` are the same thing.

    This is the only place a missing profile becomes a profile, so the
    backward-compatible default cannot drift between entry points.
    """
    if value is None:
        return CLASSIC_PROFILE
    if not isinstance(value, str):
        raise ValueError("research_profile must be a string")
    normalized = value.strip()
    if not normalized:
        return CLASSIC_PROFILE
    if normalized not in RESEARCH_PROFILES:
        raise ValueError(
            f"unsupported research_profile: {normalized} "
            f"(expected one of {', '.join(RESEARCH_PROFILES)})"
        )
    return normalized


class CatalystEvidencePolicyV1(BaseModel):
    """Immutable data requirements for one ``catalyst_v1`` run.

    Only the window/budget parameters the design fixes today live here.  The
    qualitative gates (identity, coverage, PIT, priority ceiling) belong to the
    canonical case schema owned by the schema workstream; this model records the
    *inputs* those gates are evaluated against.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: CatalystEvidencePolicyVersion = CATALYST_EVIDENCE_POLICY_VERSION
    profile: Literal["catalyst_v1"] = "catalyst_v1"
    # Product research-lookahead window.  This is the time range the reader is
    # asked about, NOT the historical data-fetch window.
    forward_window_max_calendar_days: int = Field(default=84, gt=0)
    # Recent event/announcement lookback windows, focused rather than exhaustive.
    event_lookback_calendar_days: tuple[int, ...] = (7, 30, 90)
    # Historical fetch ranges reused from the medium horizon plan.
    price_history_trading_days: int = Field(default=250, gt=0)
    fundamentals_quarters: int = Field(default=8, gt=0)
    # A plan can never fetch more than these regardless of source health.
    max_source_calls: int = Field(default=40, gt=0)
    max_model_calls: int = Field(default=20, gt=0)
    # One in-budget supplement round after the frozen dossier, at most this many
    # additional capabilities (design §8.6 / §9).
    max_supplement_rounds: int = Field(default=1, ge=0)
    max_supplement_capabilities: int = Field(default=3, gt=0)

    def as_identity(self) -> dict[str, object]:
        """Return the fingerprint-facing projection of this policy.

        Only values that change what the run is allowed to fetch are included.
        Derived copies of the same version string are not duplicated here.
        """
        return {
            "policy_version": self.policy_version,
            "profile": self.profile,
            "forward_window_max_calendar_days": self.forward_window_max_calendar_days,
            "event_lookback_calendar_days": list(self.event_lookback_calendar_days),
            "price_history_trading_days": self.price_history_trading_days,
            "fundamentals_quarters": self.fundamentals_quarters,
            "max_source_calls": self.max_source_calls,
            "max_model_calls": self.max_model_calls,
            "max_supplement_rounds": self.max_supplement_rounds,
            "max_supplement_capabilities": self.max_supplement_capabilities,
        }


def catalyst_evidence_policy_v1() -> CatalystEvidencePolicyV1:
    """Return the frozen first-version policy. Pure; touches no provider."""
    return CatalystEvidencePolicyV1()


# ---------------------------------------------------------------------------
# Stable public error codes
# ---------------------------------------------------------------------------
# These strings are part of the HTTP contract.  Clients switch on them, so they
# are frozen here rather than spelled inline at each raise site.

CATALYST_PROFILE_UNAVAILABLE = "catalyst_profile_unavailable"
CATALYST_MODE_UNSUPPORTED = "catalyst_mode_unsupported"
CATALYST_MARKET_UNSUPPORTED = "catalyst_market_unsupported"
CATALYST_LEGACY_SCHEDULING_PARAMS = "catalyst_legacy_scheduling_params_not_applicable"
CATALYST_HORIZON_NOT_SUPPORTED = "catalyst_horizon_not_supported"
CATALYST_PROFILE_MISMATCH = "catalyst_profile_mismatch"
