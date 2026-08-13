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


def parse_analysis_cutoff(value: Any) -> AnalysisCutoffV1 | None:
    if isinstance(value, AnalysisCutoffV1):
        return value
    if isinstance(value, Mapping):
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
