"""Versioned, deterministic data requirements for each investment horizon."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradingagents.dataflows.coverage import SourceGroupRequirementV1

InvestmentHorizon = Literal["short", "medium", "long"]
MarketKind = Literal["a_share", "global"]
WindowUnit = Literal["calendar_days", "trading_days", "quarters", "years", "snapshot"]
Granularity = Literal["daily", "weekly", "monthly", "quarterly", "annual", "snapshot"]
PriceBasis = Literal[
    "qfq",
    "split_dividend_adjusted",
    "raw",
    "not_applicable",
]
Requirement = Literal["required", "optional"]
LensId = Literal["market", "fundamentals", "news", "sentiment"]

POLICY_VERSION = "horizon-policy-v1"


class CutoffResolutionPolicyV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: Literal["analysis-cutoff-v1"] = "analysis-cutoff-v1"
    boundary: Literal["market_local_end_of_day"] = "market_local_end_of_day"
    a_share_timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    global_verified_exchange_required: Literal[True] = True


class WindowSpecV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: int = Field(gt=0)
    unit: WindowUnit

    @model_validator(mode="after")
    def validate_snapshot(self) -> WindowSpecV1:
        if self.unit == "snapshot" and self.value != 1:
            raise ValueError("snapshot windows must have value=1")
        return self


class FetchBudgetV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_calls: int = Field(gt=0)
    max_items: int = Field(gt=0)
    max_pages: int = Field(gt=0)


class CapabilityPlanV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    requirement: Requirement
    windows: tuple[WindowSpecV1, ...] = Field(min_length=1)
    granularities: tuple[Granularity, ...] = Field(min_length=1)
    price_basis: PriceBasis = "not_applicable"
    required_source_ids: tuple[str, ...] = ()
    required_source_groups: tuple[SourceGroupRequirementV1, ...] = ()
    optional_source_ids: tuple[str, ...] = ()
    budget: FetchBudgetV1

    @model_validator(mode="after")
    def validate_capability(self) -> CapabilityPlanV1:
        if len({window.window_id for window in self.windows}) != len(self.windows):
            raise ValueError("window IDs must be unique within a capability")
        grouped_source_ids = tuple(
            source_id for group in self.required_source_groups for source_id in group.source_ids
        )
        source_ids = self.required_source_ids + grouped_source_ids + self.optional_source_ids
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("direct, grouped, and optional source IDs must be unique and disjoint")
        if self.requirement == "required" and not (
            self.required_source_ids or self.required_source_groups
        ):
            raise ValueError("required capabilities must declare a concrete source requirement")
        if self.capability_id == "adjusted_price_history":
            if self.price_basis not in {"qfq", "split_dividend_adjusted"}:
                raise ValueError(
                    "adjusted_price_history must use an adjusted price basis"
                )
        else:
            expected_basis = {
                "raw_price_audit": "raw",
            }.get(self.capability_id, "not_applicable")
            if self.price_basis != expected_basis:
                raise ValueError(
                    f"{self.capability_id} must use price_basis={expected_basis}"
                )
        return self


class LensGroupV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    group_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    minimum_usable: int = Field(gt=0)
    lens_ids: tuple[LensId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_group(self) -> LensGroupV1:
        if len(set(self.lens_ids)) != len(self.lens_ids):
            raise ValueError("lens group IDs must be unique")
        if self.minimum_usable > len(self.lens_ids):
            raise ValueError("minimum_usable cannot exceed the lens group size")
        return self


class DataWindowPlanV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    policy_version: Literal["horizon-policy-v1"] = POLICY_VERSION
    horizon: InvestmentHorizon
    market: MarketKind
    analysis_date: str
    cutoff_resolution_policy: CutoffResolutionPolicyV1 = Field(
        default_factory=CutoffResolutionPolicyV1
    )
    capabilities: tuple[CapabilityPlanV1, ...] = Field(min_length=1)
    required_lenses: tuple[LensId, ...]
    required_lens_groups: tuple[LensGroupV1, ...] = ()
    optional_lenses: tuple[LensId, ...] = ()

    @field_validator("analysis_date")
    @classmethod
    def validate_analysis_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("analysis_date must use YYYY-MM-DD") from exc
        if value != parsed.isoformat():
            raise ValueError("analysis_date must use YYYY-MM-DD")
        return value

    @model_validator(mode="after")
    def validate_plan(self) -> DataWindowPlanV1:
        capability_ids = [capability.capability_id for capability in self.capabilities]
        if len(set(capability_ids)) != len(capability_ids):
            raise ValueError("capability IDs must be unique")
        if set(self.required_lenses) & set(self.optional_lenses):
            raise ValueError("required and optional lenses must be disjoint")
        if len({group.group_id for group in self.required_lens_groups}) != len(
            self.required_lens_groups
        ):
            raise ValueError("required lens group IDs must be unique")
        return self

    def capability_index(self) -> dict[str, CapabilityPlanV1]:
        return {capability.capability_id: capability for capability in self.capabilities}


def _window(window_id: str, value: int, unit: WindowUnit) -> WindowSpecV1:
    return WindowSpecV1(window_id=window_id, value=value, unit=unit)


def _budget(max_calls: int, max_items: int, max_pages: int) -> FetchBudgetV1:
    return FetchBudgetV1(max_calls=max_calls, max_items=max_items, max_pages=max_pages)


def _capability(
    capability_id: str,
    requirement: Requirement,
    windows: tuple[WindowSpecV1, ...],
    granularities: tuple[Granularity, ...],
    required_sources: tuple[str, ...],
    optional_sources: tuple[str, ...] = (),
    *,
    budget: FetchBudgetV1,
    price_basis: PriceBasis = "not_applicable",
    required_source_groups: tuple[SourceGroupRequirementV1, ...] = (),
) -> CapabilityPlanV1:
    return CapabilityPlanV1(
        capability_id=capability_id,
        requirement=requirement,
        windows=windows,
        granularities=granularities,
        price_basis=price_basis,
        required_source_ids=required_sources,
        required_source_groups=required_source_groups,
        optional_source_ids=optional_sources,
        budget=budget,
    )


def _shared_capabilities(
    *,
    market: MarketKind,
    price_windows: tuple[WindowSpecV1, ...],
    price_granularities: tuple[Granularity, ...],
    event_windows: tuple[WindowSpecV1, ...],
) -> tuple[CapabilityPlanV1, ...]:
    if market == "a_share":
        identity_source_ids = (
            "tushare.stock_basic",
            "eastmoney.stock_profile",
            "akshare.stock_individual_info",
            "sina.stock_code_name",
            "yfinance.company_profile",
        )
        snapshot_source_ids = (
            "mootdx.daily_bars",
            "tushare.tushare_get_stock",
        )
        adjusted_source_ids = (
            "tushare.qfq_daily",
            "akshare.qfq_daily",
        )
        event_source_ids = ("tavily.company_news", "eastmoney.company_news")
        raw_price_sources = ("mootdx.daily_bars",)
        event_optional_sources = (
            "cls.telegraph",
            "akshare.interactive_questions",
            "ths.hot_list",
            "eastmoney.hot_concept",
        )
        adjusted_price_basis: PriceBasis = "qfq"
    else:
        identity_source_ids = ("yfinance.company_profile",)
        snapshot_source_ids = (
            "yfinance.ohlcv",
            "alpha_vantage.TIME_SERIES_DAILY",
        )
        adjusted_source_ids = (
            "yfinance.adjusted_ohlcv",
            "alpha_vantage.TIME_SERIES_DAILY_ADJUSTED",
        )
        event_source_ids = (
            "tavily.company_news",
            "yfinance.company_news",
            "alpha_vantage.NEWS_SENTIMENT",
        )
        raw_price_sources = ("alpha_vantage.TIME_SERIES_DAILY",)
        event_optional_sources = ()
        adjusted_price_basis = "split_dividend_adjusted"

    identity_sources = SourceGroupRequirementV1(
        group_id="identity_provider",
        minimum_usable=1,
        source_ids=identity_source_ids,
    )
    snapshot_sources = SourceGroupRequirementV1(
        group_id="market_snapshot_provider",
        minimum_usable=1,
        source_ids=snapshot_source_ids,
    )
    adjusted_sources = SourceGroupRequirementV1(
        group_id="adjusted_price_provider",
        minimum_usable=1,
        source_ids=adjusted_source_ids,
    )
    event_sources = SourceGroupRequirementV1(
        group_id="company_news_provider",
        minimum_usable=1,
        source_ids=event_source_ids,
    )
    capabilities = (
        _capability(
            "verified_identity",
            "required",
            (_window("identity", 1, "snapshot"),),
            ("snapshot",),
            (),
            budget=_budget(1, 1, 1),
            required_source_groups=(identity_sources,),
        ),
        _capability(
            "verified_market_snapshot",
            "required",
            (_window("market_snapshot", 1, "snapshot"),),
            ("snapshot",),
            (),
            budget=_budget(2, 3, 1),
            required_source_groups=(snapshot_sources,),
        ),
        _capability(
            "adjusted_price_history",
            "required",
            price_windows,
            price_granularities,
            (),
            budget=_budget(2, 2000, 10),
            price_basis=adjusted_price_basis,
            required_source_groups=(adjusted_sources,),
        ),
        _capability(
            "raw_price_audit",
            "optional",
            price_windows,
            price_granularities,
            (),
            raw_price_sources,
            budget=_budget(1, 2000, 10),
            price_basis="raw",
        ),
        _capability(
            "company_event_window",
            "required",
            event_windows,
            ("daily",),
            (),
            event_optional_sources,
            budget=_budget(5, 500, 10),
            required_source_groups=(event_sources,),
        ),
    )
    return capabilities


def _official_disclosures(
    requirement: Requirement,
    years: int,
    market: MarketKind,
) -> CapabilityPlanV1:
    if market == "a_share":
        candidate_sources = ("cninfo.announcements", "exchange.announcements")
    else:
        candidate_sources = ("sec.company_filings",)
    required_sources = candidate_sources[:1] if requirement == "required" else ()
    optional_sources = candidate_sources[1:] if requirement == "required" else candidate_sources
    return _capability(
        "official_disclosures",
        requirement,
        (_window("official_history", years, "years"),),
        ("daily",),
        required_sources,
        optional_sources,
        budget=_budget(3, 1000, 20),
    )


def _research_reports(
    market: MarketKind,
    years: int,
) -> tuple[CapabilityPlanV1, ...]:
    if market != "a_share":
        return ()
    return (
        _capability(
            "research_reports",
            "optional",
            (_window("research_report_history", years, "years"),),
            ("daily",),
            (),
            ("eastmoney.research_reports",),
            budget=_budget(3, 2000, 20),
        ),
    )


def _fundamentals(
    capability_id: str,
    requirement: Requirement,
    value: int,
    unit: WindowUnit,
    market: MarketKind,
) -> CapabilityPlanV1:
    if market == "a_share":
        providers = {
            "balance_sheet": (
                "tushare.tushare_get_balance_sheet",
                "sina.sina_get_balance_sheet",
            ),
            "cash_flow": (
                "tushare.tushare_get_cashflow",
                "sina.sina_get_cashflow",
            ),
            "income_statement": (
                "tushare.tushare_get_income_statement",
                "sina.sina_get_income_statement",
            ),
        }
    else:
        providers = {
            "balance_sheet": (
                "yfinance.balance_sheet",
                "alpha_vantage.BALANCE_SHEET",
            ),
            "cash_flow": (
                "yfinance.cash_flow",
                "alpha_vantage.CASH_FLOW",
            ),
            "income_statement": (
                "yfinance.income_statement",
                "alpha_vantage.INCOME_STATEMENT",
            ),
        }
    provider_groups = tuple(
        SourceGroupRequirementV1(
            group_id=f"{capability_id}_{statement}_provider",
            minimum_usable=1,
            source_ids=source_ids,
        )
        for statement, source_ids in providers.items()
    )
    required_groups = provider_groups if requirement == "required" else ()
    optional_sources = (
        tuple(source_id for group in provider_groups for source_id in group.source_ids)
        if requirement == "optional"
        else ()
    )
    if unit == "quarters" and market == "a_share":
        optional_sources += ("mootdx.finance_snapshot",)
    return _capability(
        capability_id,
        requirement,
        (_window("financial_history", value, unit),),
        ("quarterly",) if unit == "quarters" else ("annual",),
        (),
        optional_sources,
        budget=_budget(3, 100, 10),
        required_source_groups=required_groups,
    )


def _sentiment(
    windows: tuple[WindowSpecV1, ...],
    sources: tuple[str, ...],
) -> CapabilityPlanV1:
    return _capability(
        "sentiment_pulse",
        "optional",
        windows,
        ("daily",),
        (),
        sources,
        budget=_budget(5, 500, 10),
    )


def _sentiment_sources(
    market: MarketKind,
    a_share_sources: tuple[str, ...],
) -> tuple[str, ...]:
    if market == "a_share":
        return a_share_sources
    return (
        "alpha_vantage.NEWS_SENTIMENT",
        "reddit.company_mentions",
    )


def build_data_window_plan(
    horizon: InvestmentHorizon,
    analysis_date: str,
    *,
    market: MarketKind = "a_share",
) -> DataWindowPlanV1:
    """Return the immutable v1 policy plan without accessing any provider."""

    if horizon == "short":
        capabilities = _shared_capabilities(
            market=market,
            price_windows=(
                _window("underlying_history", 365, "calendar_days"),
                _window("signal_20d", 20, "trading_days"),
                _window("signal_60d", 60, "trading_days"),
            ),
            price_granularities=("daily",),
            event_windows=(
                _window("new_events", 7, "calendar_days"),
                _window("active_themes", 30, "calendar_days"),
                _window("impact_tracking", 90, "calendar_days"),
            ),
        ) + (
            _official_disclosures("optional", 1, market),
            *_research_reports(market, 1),
            _fundamentals("fundamentals_quarterly", "optional", 4, "quarters", market),
            _sentiment(
                (
                    _window("fast_signal", 1, "calendar_days"),
                    _window("flow_5d", 5, "trading_days"),
                    _window("flow_20d", 20, "trading_days"),
                ),
                _sentiment_sources(
                    market,
                    (
                        "eastmoney.capital_flow",
                        "eastmoney.margin_financing",
                        "ths.northbound_flow",
                        "eastmoney.board_fund_flow",
                        "eastmoney.insider_trades",
                    ),
                ),
            ),
        )
        return DataWindowPlanV1(
            horizon=horizon,
            market=market,
            analysis_date=analysis_date,
            capabilities=capabilities,
            required_lenses=("market",),
            required_lens_groups=(
                LensGroupV1(
                    group_id="news_or_sentiment",
                    minimum_usable=1,
                    lens_ids=("news", "sentiment"),
                ),
            ),
            optional_lenses=("fundamentals",),
        )

    if horizon == "medium":
        capabilities = _shared_capabilities(
            market=market,
            price_windows=(
                _window("signal_20d", 20, "trading_days"),
                _window("signal_60d", 60, "trading_days"),
                _window("signal_120d", 120, "trading_days"),
                _window("signal_250d", 250, "trading_days"),
            ),
            price_granularities=("daily", "weekly"),
            event_windows=(
                _window("new_events", 7, "calendar_days"),
                _window("active_themes", 30, "calendar_days"),
                _window("theme_evolution", 180, "calendar_days"),
            ),
        ) + (
            _official_disclosures("required", 4, market),
            *_research_reports(market, 4),
            _fundamentals("fundamentals_quarterly", "required", 8, "quarters", market),
            _fundamentals("fundamentals_annual", "optional", 5, "years", market),
            _sentiment(
                tuple(
                    _window(
                        f"pulse_{value}d", value, "calendar_days" if value == 1 else "trading_days"
                    )
                    for value in (1, 20, 60, 120)
                ),
                _sentiment_sources(
                    market,
                    (
                        "eastmoney.margin_financing",
                        "eastmoney.capital_flow",
                        "ths.northbound_flow",
                        "eastmoney.board_fund_flow",
                        "eastmoney.insider_trades",
                    ),
                ),
            ),
        )
        return DataWindowPlanV1(
            horizon=horizon,
            market=market,
            analysis_date=analysis_date,
            capabilities=capabilities,
            required_lenses=("market", "fundamentals", "news"),
            optional_lenses=("sentiment",),
        )

    if horizon == "long":
        capabilities = _shared_capabilities(
            market=market,
            price_windows=(
                _window("underlying_history", 5, "years"),
                _window("signal_60d", 60, "trading_days"),
                _window("signal_120d", 120, "trading_days"),
                _window("signal_250d", 250, "trading_days"),
            ),
            price_granularities=("weekly", "monthly"),
            event_windows=tuple(
                _window(f"event_{value}d", value, "calendar_days") for value in (7, 30, 90, 365)
            ),
        ) + (
            _official_disclosures("required", 5, market),
            *_research_reports(market, 5),
            _fundamentals("fundamentals_annual", "required", 5, "years", market),
            _fundamentals("fundamentals_quarterly", "optional", 12, "quarters", market),
            _sentiment(
                tuple(_window(f"pulse_{value}d", value, "trading_days") for value in (60, 120)),
                _sentiment_sources(
                    market,
                    (
                        "eastmoney.shareholder_counts",
                        "cninfo.announcements",
                        "eastmoney.insider_trades",
                        "eastmoney.margin_financing",
                        "eastmoney.capital_flow",
                        "eastmoney.northbound_holdings",
                    ),
                ),
            ),
        )
        return DataWindowPlanV1(
            horizon=horizon,
            market=market,
            analysis_date=analysis_date,
            capabilities=capabilities,
            required_lenses=("market", "fundamentals", "news"),
            optional_lenses=("sentiment",),
        )

    raise ValueError(f"unsupported investment horizon: {horizon}")
