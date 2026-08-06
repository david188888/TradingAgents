"""Code-owned public contract for the multi-window investment research chain.

The dossier is deliberately conservative: it records what is known, what is
not assessed, and where a transmission edge is broken. It never fills a
missing company order, profit, or valuation multiple from an industry story.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

WindowKind = Literal["event", "theme", "official", "forecast"]
EntityRole = Literal["subject", "subsidiary", "comparable", "industry", "noise"]
VerificationStatus = Literal[
    "verified", "supported", "partial", "unverified", "contradicted", "data_error", "not_assessed"
]


class ResearchWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: WindowKind
    start_date: str
    end_date: str
    lookback_days: int = Field(ge=0)
    source_policy: str = Field(min_length=1, max_length=240)
    coverage: Literal["available", "partial", "unavailable"] = "unavailable"


class ResearchClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    claim_id: str = Field(min_length=1, max_length=120)
    claim_type: Literal[
        "fact", "company_guidance", "analyst_forecast", "market_expectation", "inference", "unknown"
    ]
    statement: str = Field(min_length=1, max_length=800)
    entity_role: EntityRole
    entity_scope: str = Field(min_length=1, max_length=120)
    period: str | None = Field(default=None, max_length=80)
    source_ref: str | None = Field(default=None, max_length=320)
    evidence_level: Literal["primary", "secondary", "tertiary", "none"] = "none"
    verification_status: VerificationStatus = "not_assessed"
    next_verification: str | None = Field(default=None, max_length=400)
    invalidation: str | None = Field(default=None, max_length=400)
    raw_field: str | None = Field(default=None, max_length=160)
    raw_value: float | None = None
    raw_unit: str | None = Field(default=None, max_length=40)
    normalized_value: float | None = None
    normalized_unit: str | None = Field(default=None, max_length=40)
    scale: float | None = None
    currency: str | None = Field(default=None, max_length=12)
    source_table: str | None = Field(default=None, max_length=160)
    derived_formula: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def _numeric_provenance_is_complete(self):
        numeric_fields = (self.raw_value, self.normalized_value, self.scale)
        if any(value is not None for value in numeric_fields):
            if self.raw_value is None or self.raw_unit is None or self.scale is None:
                raise ValueError("numeric claims require raw_value, raw_unit, and scale")
            if self.normalized_value is not None and self.scale == 0:
                raise ValueError("numeric claim scale must not be zero")
        if self.entity_role == "noise" and self.verification_status in {"verified", "supported"}:
            raise ValueError("noise claims cannot be decision-eligible")
        return self


class CommercializationMilestone(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product: str = Field(min_length=1, max_length=240)
    geography: str | None = Field(default=None, max_length=120)
    stage: Literal[
        "concept", "prototype", "customer_validation", "certification", "order", "backlog",
        "production", "shipment", "revenue_recognition", "service"
    ]
    status: Literal["planned", "in_progress", "completed", "delayed", "failed", "unknown"]
    state_date: str | None = None
    entity_role: EntityRole = "subject"
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    next_verification: str = Field(min_length=1, max_length=400)
    delay_risk: str | None = Field(default=None, max_length=400)


class TransmissionEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    edge_id: str = Field(min_length=1, max_length=120)
    from_node: str = Field(min_length=1, max_length=120)
    to_node: str = Field(min_length=1, max_length=120)
    support_status: Literal["supported", "partially_supported", "unsupported", "contradicted", "not_assessed"]
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    lag_months: int | None = Field(default=None, ge=0)
    missing_evidence: list[str] = Field(default_factory=list, max_length=8)
    next_verification: str = Field(min_length=1, max_length=400)
    invalidation: str = Field(min_length=1, max_length=400)


class ProfitBridgeScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scenario: Literal["base", "bull", "bear"]
    period: str = Field(min_length=1, max_length=40)
    volume: float | None = None
    volume_unit: str | None = None
    asp: float | None = None
    asp_unit: str | None = None
    revenue: float | None = None
    gross_margin: float | None = Field(default=None, ge=0.0, le=1.0)
    segment_profit: float | None = None
    net_income_parent: float | None = None
    eps: float | None = None
    status: Literal["supported", "conditional", "incomplete"] = "incomplete"
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    missing_inputs: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def _revenue_arithmetic_is_not_fabricated(self):
        if (
            self.volume is not None
            and self.asp is not None
            and self.revenue is not None
            and abs(self.volume * self.asp - self.revenue) > max(0.01, abs(self.revenue) * 0.02)
        ):
            raise ValueError("profit bridge revenue does not match volume times ASP")
        return self


class ValuationScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scenario: Literal["base", "bull", "bear"]
    earnings_period: str = Field(min_length=1, max_length=40)
    eps: float | None = None
    multiple: float | None = Field(default=None, ge=0.0)
    target_price: float | None = None
    earnings_uplift_supported: bool = False
    multiple_rerating_supported: bool = False
    rerating_conditions: list[str] = Field(default_factory=list, max_length=12)
    invalidation: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def _target_price_requires_inputs(self):
        if self.target_price is not None:
            if self.eps is None or self.multiple is None:
                raise ValueError("target price requires EPS and multiple")
            if abs(self.target_price - self.eps * self.multiple) > max(0.01, abs(self.target_price) * 0.02):
                raise ValueError("target price does not match EPS times multiple")
        return self


class ResearchDossier(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1"] = "1"
    subject_ticker: str = Field(min_length=1, max_length=32)
    as_of: str
    windows: list[ResearchWindow] = Field(min_length=4, max_length=4)
    claims: list[ResearchClaim] = Field(default_factory=list, max_length=40)
    commercialization: list[CommercializationMilestone] = Field(default_factory=list, max_length=24)
    transmission_edges: list[TransmissionEdge] = Field(default_factory=list, max_length=24)
    profit_bridge: list[ProfitBridgeScenario] = Field(default_factory=list, max_length=6)
    valuation: list[ValuationScenario] = Field(default_factory=list, max_length=6)
    unknowns: list[str] = Field(default_factory=list, max_length=24)
    decision_eligible_claim_ids: list[str] = Field(default_factory=list, max_length=40)


def render_research_dossier(dossier: dict[str, Any] | None) -> str:
    """Render only the public dossier, with unknowns kept explicit."""
    return json.dumps(dossier or {}, ensure_ascii=False, sort_keys=True)


def build_research_dossier(state: dict[str, Any]) -> dict[str, Any]:
    """Build a conservative dossier from already validated analyst artifacts."""
    ticker = str(state.get("company_of_interest") or "unknown")
    as_of = str(state.get("trade_date") or date.today().isoformat())
    try:
        end = date.fromisoformat(as_of)
    except ValueError:
        end = date.today()
        as_of = end.isoformat()
    windows = [
        ResearchWindow(kind="event", start_date=(end - timedelta(days=7)).isoformat(), end_date=as_of, lookback_days=7, source_policy="A-share company events and market catalysts", coverage="partial"),
        ResearchWindow(kind="theme", start_date=(end - timedelta(days=180)).isoformat(), end_date=as_of, lookback_days=180, source_policy="A-share official disclosures first; news and peers as supplement", coverage="partial"),
        ResearchWindow(kind="official", start_date=(end - timedelta(days=1460)).isoformat(), end_date=as_of, lookback_days=1460, source_policy="Exchange/company announcements and periodic reports", coverage="partial"),
        ResearchWindow(kind="forecast", start_date=as_of, end_date=(end + timedelta(days=1825)).isoformat(), lookback_days=1825, source_policy="Declared analyst forecasts only; no fabricated estimates", coverage="unavailable"),
    ]
    reports = state.get("methodology_reports") or {}
    claims: list[ResearchClaim] = []
    milestones: list[CommercializationMilestone] = []
    if isinstance(reports, dict):
        news = reports.get("news_analyst") or {}
        if isinstance(news, dict):
            for index, event in enumerate(news.get("event_signals") or []):
                if not isinstance(event, dict):
                    continue
                claim_id = f"news-event-{index + 1}"
                status = "verified" if event.get("status") == "confirmed" else "partial"
                claims.append(ResearchClaim(
                    claim_id=claim_id,
                    claim_type="fact" if status == "verified" else "inference",
                    statement=str(event.get("event_type") or "Unspecified event"),
                    entity_role="subject",
                    entity_scope="listed_company",
                    source_ref=event.get("source_ref"),
                    evidence_level="primary" if event.get("source_ref") else "none",
                    verification_status=status,
                    next_verification=event.get("next_verification"),
                ))
    eligible = [claim.claim_id for claim in claims if claim.verification_status in {"verified", "supported"} and claim.entity_role != "noise"]
    dossier = ResearchDossier(
        subject_ticker=ticker,
        as_of=as_of,
        windows=windows,
        claims=claims,
        commercialization=milestones,
        transmission_edges=[
            TransmissionEdge(
                edge_id="industry-to-company-order",
                from_node="industry_demand",
                to_node="company_orders",
                support_status="not_assessed",
                missing_evidence=["company-specific order or backlog disclosure"],
                next_verification="Search official company/exchange disclosure for order, backlog, or shipment evidence.",
                invalidation="Target product is not certified, eligible, or deliverable.",
            ),
            TransmissionEdge(
                edge_id="company-order-to-profit",
                from_node="company_orders",
                to_node="segment_profit",
                support_status="not_assessed",
                missing_evidence=["volume, ASP, cost, and segment margin"],
                next_verification="Locate segment disclosure or audited management guidance.",
                invalidation="Orders do not convert to revenue or margin.",
            ),
        ],
        profit_bridge=[
            ProfitBridgeScenario(scenario=scenario, period="next_reported_period", status="incomplete", missing_inputs=["volume", "ASP", "cost", "segment margin", "shares", "EPS"])
            for scenario in ("base", "bull", "bear")
        ],
        valuation=[
            ValuationScenario(scenario=scenario, earnings_period="next_forecast_period", rerating_conditions=["verified company commercialization", "supported EPS bridge", "peer-set justification"], invalidation=["critical transmission edge remains unsupported"])
            for scenario in ("base", "bull", "bear")
        ],
        unknowns=["company-specific commercialization stage", "company order/backlog", "segment profit bridge", "EPS forecast and peer multiple"],
        decision_eligible_claim_ids=eligible,
    )
    return dossier.model_dump(mode="json")
