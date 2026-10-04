"""Frozen source windows for evidence_v1; not a research lookahead policy."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


def is_native_stock_ticker(ticker: str) -> bool:
    from tradingagents.dataflows.ticker_utils import normalize_ticker_symbol

    value = normalize_ticker_symbol(ticker)
    code, _, suffix = value.partition(".")
    if len(code) != 6 or not code.isdigit():
        return False
    return (
        (code.startswith(("0", "3")) and suffix == "SZ")
        or (code.startswith("6") and suffix in {"SS", "SH"})
        or (code.startswith(("4", "8", "92")) and suffix == "BJ")
    )


class NativeEvidencePolicyV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    policy_version: Literal["evidence-policy-v1"] = "evidence-policy-v1"
    profile: Literal["evidence_v1"] = "evidence_v1"
    event_lookback_calendar_days: tuple[Literal[7], Literal[30], Literal[90]] = (7, 30, 90)
    price_history_trading_days: Literal[250] = 250
    fundamentals_quarters: Literal[8] = 8

    def as_identity(self):
        return self.model_dump(mode="json")

    def collector_policy(self):
        # This adapter reuses the proven collector's source windows. Its
        # legacy forward field does not become a company/holding outlook.
        from .catalyst_evidence_policy import catalyst_evidence_policy_v1

        return catalyst_evidence_policy_v1()
