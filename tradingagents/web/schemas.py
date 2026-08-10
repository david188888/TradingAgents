"""HTTP-only schemas for the localhost TradingAgents service boundary."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradingagents.execution.models import ANALYST_WIRE_KEYS
from tradingagents.portfolio import PortfolioContext, PortfolioLimits, Position

SUPPORTED_OUTPUT_LANGUAGES = (
    "English",
    "Chinese",
)
RESEARCH_DEPTHS = (1, 3, 5)
TICKER_PATTERN = re.compile(r"^[A-Za-z0-9._\-^=]{1,32}$")


class PortfolioPositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticker: str = Field(min_length=1, max_length=32)
    # Kept intentionally permissive because this model is now a legacy input
    # boundary.  Compatibility normalization owns the stable public errors for
    # the target position instead of exposing generic Pydantic constraints.
    quantity: int
    average_cost: float
    sellable_quantity: int | None = None

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        if not TICKER_PATTERN.fullmatch(value) or not any(
            character.isalnum() for character in value
        ):
            raise ValueError("ticker contains unsupported characters")
        return value

class PortfolioLimitsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_position_weight: float = Field(default=0.10, gt=0, le=1)
    lot_size: int = Field(default=1, ge=1)
    fee_rate: float = Field(default=0.0005, ge=0, lt=1)
    minimum_fee: float = Field(default=0, ge=0)
    allow_short: bool = False


class PortfolioRequest(BaseModel):
    """Non-secret facts required for deterministic PM execution constraints."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    cash: float
    positions: tuple[PortfolioPositionRequest, ...] = ()
    mark_prices: dict[str, float] = Field(default_factory=dict)
    currency: str = "CNY"
    limits: PortfolioLimitsRequest = Field(default_factory=PortfolioLimitsRequest)

    def to_domain(self) -> PortfolioContext:
        return PortfolioContext(
            cash=self.cash,
            positions=tuple(
                Position(
                    ticker=position.ticker,
                    quantity=position.quantity,
                    average_cost=position.average_cost,
                    sellable_quantity=position.sellable_quantity,
                )
                for position in self.positions
            ),
            mark_prices=self.mark_prices,
            currency=self.currency.upper(),
            limits=PortfolioLimits(**self.limits.model_dump()),
        )


class HoldingInputRequest(BaseModel):
    """Raw browser facts normalized at the HTTP boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticker: str = ""
    # Holding validation deliberately happens in compatibility normalization so
    # every invalid value receives the frozen public error code/path instead
    # of a generic Pydantic coercion error.
    quantity: object | None = None
    average_cost: object | None = None
    cash: object | None = None
    total_account_value: object | None = None
    currency: object | None = None
    facts_as_of: object | None = None
    original_thesis: object | None = None


class RunCreateRequest(BaseModel):
    """Validated browser input before any background worker is created."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticker: str = Field(min_length=1, max_length=32)
    analysis_date: str
    selected_analysts: tuple[str, ...] = ANALYST_WIRE_KEYS
    research_depth: Literal[1, 3, 5] = 1
    mode: Literal["company_research", "holding_review"] | None = None
    horizon: Literal["short", "medium", "long"] = "medium"
    llm_provider: str = Field(min_length=1, max_length=64)
    quick_think_llm: str = Field(min_length=1, max_length=256)
    deep_think_llm: str = Field(min_length=1, max_length=256)
    output_language: str = "English"
    checkpoint_enabled: bool = False
    asset_type: Literal["stock", "crypto"] | None = None
    holding: HoldingInputRequest | None = None
    # Legacy-only input; new UI clients send HoldingInputRequest instead.
    portfolio: PortfolioRequest | None = None

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        if not TICKER_PATTERN.fullmatch(value) or not any(
            character.isalnum() for character in value
        ):
            raise ValueError("ticker contains unsupported characters")
        return value

    @field_validator("analysis_date")
    @classmethod
    def validate_analysis_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("analysis_date must use YYYY-MM-DD") from exc
        if parsed > date.today():
            raise ValueError("analysis_date cannot be in the future")
        return value

    @field_validator("selected_analysts")
    @classmethod
    def validate_analysts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("at least one analyst is required")
        unknown = sorted(set(value) - set(ANALYST_WIRE_KEYS))
        if unknown:
            raise ValueError(f"unknown analyst keys: {', '.join(unknown)}")
        if len(value) != len(set(value)):
            raise ValueError("selected_analysts must not contain duplicates")
        return value

    @field_validator("output_language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        if value not in SUPPORTED_OUTPUT_LANGUAGES:
            raise ValueError("unsupported output language")
        return value

    @model_validator(mode="after")
    def validate_asset_analysts(self) -> RunCreateRequest:
        if self.asset_type == "crypto" and "fundamentals" in self.selected_analysts:
            raise ValueError("fundamentals analyst is unavailable for crypto")
        return self


class ArtifactMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    kind: str
    media_type: str
    content_sha256: str
    byte_size: int = Field(ge=0)
    locator: str


class ApiErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    fields: tuple[str, ...] = ()
    active_run_id: str | None = None


class ApiErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: ApiErrorDetail
