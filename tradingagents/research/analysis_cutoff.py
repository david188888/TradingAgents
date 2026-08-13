"""Resolve and freeze the temporal cutoff used by one research run."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, time, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradingagents.dataflows.ticker_utils import is_a_share_ticker

CUTOFF_POLICY_VERSION = "analysis-cutoff-v1"
BOUNDED_CUTOFF_POLICY_VERSION = "analysis-cutoff-v2"

_EXCHANGE_TIMEZONES = {
    "ASE": "America/New_York",
    "NASDAQ": "America/New_York",
    "NCM": "America/New_York",
    "NGM": "America/New_York",
    "NMS": "America/New_York",
    "NYQ": "America/New_York",
    "NYSE": "America/New_York",
    "PCX": "America/New_York",
    "LSE": "Europe/London",
    "LON": "Europe/London",
    "HKG": "Asia/Hong_Kong",
    "HKSE": "Asia/Hong_Kong",
    "JPX": "Asia/Tokyo",
    "TSE": "Asia/Tokyo",
    "TOR": "America/Toronto",
    "TSX": "America/Toronto",
    "ASX": "Australia/Sydney",
}

_SUFFIX_TIMEZONES = {
    ".L": "Europe/London",
    ".HK": "Asia/Hong_Kong",
    ".T": "Asia/Tokyo",
    ".TO": "America/Toronto",
    ".AX": "Australia/Sydney",
}


class AnalysisCutoffV1(BaseModel):
    """Frozen resolution result persisted in initial graph state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    policy_version: Literal["analysis-cutoff-v1"] = CUTOFF_POLICY_VERSION
    ticker: str = Field(min_length=1, max_length=80)
    market: Literal["a_share", "global"]
    analysis_date: str
    status: Literal["resolved", "invalid"]
    analysis_cutoff_at: datetime | None = None
    timezone_name: str | None = None
    exchange: str | None = None
    identity_source_id: str | None = Field(default=None, min_length=1, max_length=160)
    identity_reference: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")

    @field_validator("analysis_date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("analysis_date must use YYYY-MM-DD")
        return value

    @field_validator("analysis_cutoff_at")
    @classmethod
    def validate_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("analysis_cutoff_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_status(self) -> AnalysisCutoffV1:
        if self.status == "resolved":
            if (
                self.analysis_cutoff_at is None
                or not self.timezone_name
                or not self.identity_source_id
            ):
                raise ValueError("resolved cutoff requires timestamp and timezone")
            if self.reason_code is not None:
                raise ValueError("resolved cutoff cannot carry a failure reason")
        else:
            if self.analysis_cutoff_at is not None or self.timezone_name is not None:
                raise ValueError("invalid cutoff cannot claim a timestamp or timezone")
            if self.reason_code != "analysis_cutoff_resolution_failed":
                raise ValueError("invalid cutoff requires the stable failure reason")
        return self


class AnalysisCutoffV2(AnalysisCutoffV1):
    """Clock-bounded cutoff used only by the explicit v3 runtime contract."""

    schema_version: Literal[2] = 2
    policy_version: Literal["analysis-cutoff-v2"] = BOUNDED_CUTOFF_POLICY_VERSION
    reason_code: Literal["analysis_cutoff_resolution_failed"] | None = None

    @model_validator(mode="after")
    def validate_bounded_status(self) -> AnalysisCutoffV2:
        if (
            self.status == "invalid"
            and self.reason_code != "analysis_cutoff_resolution_failed"
        ):
            raise ValueError("invalid bounded cutoff requires a stable failure reason")
        return self


class InstrumentIdentityPreflightV1(BaseModel):
    """Non-verifying candidates sufficient to freeze the market-time cutoff."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    contract_kind: Literal["instrument-identity-preflight-v1"] = (
        "instrument-identity-preflight-v1"
    )
    ticker: str = Field(min_length=1, max_length=80)
    market: Literal["a_share", "global"]
    candidate_exchange: str = Field(min_length=1, max_length=120)
    candidate_timezone: str = Field(min_length=1, max_length=120)
    regulatory_scope_candidate: Literal[
        "a_share_official", "us_sec_candidate", "global_non_sec", "unresolved"
    ]
    source_id: str = Field(min_length=1, max_length=160)
    derivation: Literal["validated_ticker", "explicit_fixture", "provider_candidate"]


class PreparedResearchScaffoldV1(BaseModel):
    """Pure v3 preflight result with provider-populated slots left empty."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    contract_kind: Literal["prepared-research-scaffold-v1"] = (
        "prepared-research-scaffold-v1"
    )
    runtime_policy_version: Literal["horizon-policy-v3"] = "horizon-policy-v3"
    ticker: str = Field(min_length=1, max_length=80)
    analysis_date: str
    identity_preflight: InstrumentIdentityPreflightV1
    analysis_cutoff: AnalysisCutoffV2
    # S2a deliberately keeps provider-populated slots graph-outside and empty.
    # The later atomic activation story replaces ``None`` with its strict
    # provider result contract without coupling this pure scaffold to provider
    # modules (which also depend on canonical hashing).
    verified_identity: None = None
    resolved_plan: None = None

    @field_validator("analysis_date")
    @classmethod
    def validate_scaffold_date(cls, value: str) -> str:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("analysis_date must use YYYY-MM-DD")
        return value

    @model_validator(mode="after")
    def validate_scaffold(self) -> PreparedResearchScaffoldV1:
        cutoff = self.analysis_cutoff
        if cutoff.ticker != self.ticker or cutoff.analysis_date != self.analysis_date:
            raise ValueError("scaffold identity must match its cutoff")
        if self.identity_preflight.ticker != self.ticker:
            raise ValueError("scaffold identity preflight must match its ticker")
        if self.identity_preflight.market != cutoff.market:
            raise ValueError("scaffold identity preflight must match its market")
        if cutoff.exchange != self.identity_preflight.candidate_exchange:
            raise ValueError("scaffold identity preflight must match its exchange")
        if cutoff.status == "resolved" and (
            cutoff.timezone_name != self.identity_preflight.candidate_timezone
            or cutoff.identity_source_id != self.identity_preflight.source_id
        ):
            raise ValueError("scaffold identity preflight must match cutoff provenance")
        return self


PREPARED_CONTEXT_SCHEMA_DOCUMENT = PreparedResearchScaffoldV1.model_json_schema(
    mode="validation"
)


def resolve_analysis_cutoff(
    ticker: str,
    analysis_date: str,
    *,
    identity: Mapping[str, Any] | None = None,
) -> AnalysisCutoffV1:
    """Resolve end-of-analysis-day in the verified instrument timezone."""

    parsed_date = date.fromisoformat(analysis_date)
    market: Literal["a_share", "global"] = (
        "a_share" if is_a_share_ticker(ticker) else "global"
    )
    identity_value = dict(identity or _resolve_identity(ticker, market))
    if market == "global" and identity_value and not identity_value.get(
        "identity_source"
    ):
        identity_value["identity_source"] = "yfinance.company_profile"
    exchange = _clean(identity_value.get("exchange"))
    timezone_name = _timezone_for_identity(ticker, market, identity_value)
    identity_reference = _identity_reference(ticker, market, identity_value)
    if timezone_name is None:
        return AnalysisCutoffV1(
            ticker=ticker,
            market=market,
            analysis_date=analysis_date,
            status="invalid",
            exchange=exchange,
            identity_reference=identity_reference,
            reason_code="analysis_cutoff_resolution_failed",
        )
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return AnalysisCutoffV1(
            ticker=ticker,
            market=market,
            analysis_date=analysis_date,
            status="invalid",
            exchange=exchange,
            identity_reference=identity_reference,
            reason_code="analysis_cutoff_resolution_failed",
        )
    local_cutoff = datetime.combine(parsed_date, time.max, tzinfo=local_timezone)
    return AnalysisCutoffV1(
        ticker=ticker,
        market=market,
        analysis_date=analysis_date,
        status="resolved",
        analysis_cutoff_at=local_cutoff.astimezone(timezone.utc),
        timezone_name=timezone_name,
        exchange=exchange,
        identity_source_id=_clean(identity_value.get("identity_source")),
        identity_reference=identity_reference,
    )


def resolve_bounded_analysis_cutoff(
    ticker: str,
    analysis_date: str,
    *,
    captured_at: datetime,
    identity: InstrumentIdentityPreflightV1 | Mapping[str, Any] | None = None,
) -> AnalysisCutoffV2:
    """Resolve a pure point-in-time cutoff without implicit provider access."""

    if captured_at.tzinfo is None:
        raise ValueError("captured_at must be timezone-aware")
    captured_utc = captured_at.astimezone(timezone.utc)
    parsed_date = date.fromisoformat(analysis_date)
    market: Literal["a_share", "global"] = (
        "a_share" if is_a_share_ticker(ticker) else "global"
    )
    if identity is None and market == "a_share":
        suffix = ticker.upper().rsplit(".", 1)[-1]
        preflight = InstrumentIdentityPreflightV1(
            ticker=ticker,
            market=market,
            candidate_exchange=suffix,
            candidate_timezone="Asia/Shanghai",
            regulatory_scope_candidate="a_share_official",
            source_id="validated_ticker.exchange",
            derivation="validated_ticker",
        )
    elif isinstance(identity, InstrumentIdentityPreflightV1):
        preflight = identity
    elif isinstance(identity, Mapping):
        preflight = InstrumentIdentityPreflightV1.model_validate(identity)
    else:
        preflight = None
    identity_value = (
        {
            "exchange": preflight.candidate_exchange,
            "exchange_timezone": preflight.candidate_timezone,
            "identity_source": preflight.source_id,
        }
        if preflight is not None
        else {}
    )
    exchange = _clean(identity_value.get("exchange"))
    timezone_name = _timezone_for_identity(ticker, market, identity_value)
    identity_reference = _identity_reference(ticker, market, identity_value)
    if preflight is not None and (
        preflight.ticker != ticker or preflight.market != market
    ):
        raise ValueError("identity preflight does not match the cutoff target")
    if timezone_name is None:
        return AnalysisCutoffV2(
            ticker=ticker,
            market=market,
            analysis_date=analysis_date,
            status="invalid",
            exchange=exchange,
            identity_reference=identity_reference,
            reason_code="analysis_cutoff_resolution_failed",
        )
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return AnalysisCutoffV2(
            ticker=ticker,
            market=market,
            analysis_date=analysis_date,
            status="invalid",
            exchange=exchange,
            identity_reference=identity_reference,
            reason_code="analysis_cutoff_resolution_failed",
        )
    captured_local_date = captured_utc.astimezone(local_timezone).date()
    if parsed_date > captured_local_date:
        return AnalysisCutoffV2(
            ticker=ticker,
            market=market,
            analysis_date=analysis_date,
            status="invalid",
            exchange=exchange,
            identity_reference=identity_reference,
            reason_code="analysis_cutoff_resolution_failed",
        )
    local_eod = datetime.combine(parsed_date, time.max, tzinfo=local_timezone)
    eod_utc = local_eod.astimezone(timezone.utc)
    bounded = min(eod_utc, captured_utc)
    return AnalysisCutoffV2(
        ticker=ticker,
        market=market,
        analysis_date=analysis_date,
        status="resolved",
        analysis_cutoff_at=bounded,
        timezone_name=timezone_name,
        exchange=exchange,
        identity_source_id=_clean(identity_value.get("identity_source")),
        identity_reference=identity_reference,
    )


def parse_analysis_cutoff(value: Any) -> AnalysisCutoffV1 | AnalysisCutoffV2 | None:
    if isinstance(value, AnalysisCutoffV2):
        return value
    if isinstance(value, AnalysisCutoffV1):
        return value
    if isinstance(value, Mapping):
        if value.get("policy_version") == BOUNDED_CUTOFF_POLICY_VERSION:
            return AnalysisCutoffV2.model_validate(value)
        return AnalysisCutoffV1.model_validate(value)
    return None


def time_sensitive_fetch_blocked(state: Mapping[str, Any] | None) -> bool:
    if state is None:
        return False
    result = parse_analysis_cutoff(state.get("analysis_cutoff"))
    return result is not None and result.status == "invalid"


def cutoff_failure_bundle(
    state: Mapping[str, Any], *, capability: str
) -> str:
    result = parse_analysis_cutoff(state.get("analysis_cutoff"))
    if result is None or result.status != "invalid":
        raise ValueError("cutoff failure bundle requires an invalid cutoff result")
    return json.dumps(
        {
            "schema_version": 1,
            "ticker": str(state.get("company_of_interest") or result.ticker),
            "as_of": str(state.get("trade_date") or result.analysis_date),
            "status": "invalid",
            "capability": capability,
            "reason_code": result.reason_code,
            "analysis_cutoff": result.model_dump(mode="json"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _resolve_identity(ticker: str, market: str) -> Mapping[str, Any]:
    if market == "a_share":
        suffix = ticker.upper().rsplit(".", 1)[-1]
        return {
            "exchange": suffix,
            "identity_source": "validated_ticker.exchange",
        }
    from tradingagents.agents.utils.agent_utils import resolve_instrument_identity

    identity = dict(resolve_instrument_identity(ticker))
    if identity:
        identity["identity_source"] = "yfinance.company_profile"
    return identity


def _timezone_for_identity(
    ticker: str, market: str, identity: Mapping[str, Any]
) -> str | None:
    if market == "a_share":
        return "Asia/Shanghai"
    timezone_name = _clean(
        identity.get("exchange_timezone")
        or identity.get("timezone")
        or identity.get("timeZoneFullName")
    )
    if timezone_name:
        return timezone_name
    exchange = _clean(identity.get("exchange"))
    if exchange:
        mapped = _EXCHANGE_TIMEZONES.get(exchange.upper())
        if mapped:
            return mapped
    upper = ticker.upper()
    for suffix, mapped in sorted(
        _SUFFIX_TIMEZONES.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if upper.endswith(suffix):
            return mapped
    if _clean(identity.get("quote_type")).upper() == "CRYPTOCURRENCY":
        return "UTC"
    return None


def _identity_reference(
    ticker: str, market: str, identity: Mapping[str, Any]
) -> str:
    payload = {
        "ticker": ticker,
        "market": market,
        "exchange": _clean(identity.get("exchange")),
        "exchange_timezone": _clean(
            identity.get("exchange_timezone")
            or identity.get("timezone")
            or identity.get("timeZoneFullName")
        ),
        "quote_type": _clean(identity.get("quote_type")),
        "identity_source": _clean(identity.get("identity_source")),
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"none", "n/a", "nan", "null"} else text
