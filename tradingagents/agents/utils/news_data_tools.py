import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from tradingagents.agents.utils.tool_guard import guard_target_ticker
from tradingagents.dataflows.capability_result import (
    CapabilityResultV1,
    ProviderAttemptV1,
    aggregate_capability_availability,
)
from tradingagents.dataflows.coverage import BundleCoverageV1, CoveredText, SourceCoverageV1
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.ticker_utils import is_a_share_ticker
from tradingagents.research.analysis_cutoff import (
    AnalysisCutoffV1,
    cutoff_failure_bundle,
    parse_analysis_cutoff,
    time_sensitive_fetch_blocked,
)
from tradingagents.research.horizon_policy import InvestmentHorizon, build_data_window_plan
from tradingagents.research.news_prefetch import build_news_prefetch_plan
from tradingagents.research.official_disclosures import (
    build_official_disclosure_result,
)

MAX_PREFETCH_DATA_CHARS = 12_000


@tool
@guard_target_ticker("ticker")
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    return route_to_vendor("get_news", ticker, start_date, end_date)

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int | None, "Days to look back; omit to use the configured default"] = None,
    limit: Annotated[int | None, "Max articles to return; omit to use the configured default"] = None,
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor. Defaults for look_back_days and
    limit come from DEFAULT_CONFIG (global_news_lookback_days,
    global_news_article_limit); pass explicit values to override.

    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back; omit to inherit config
        limit (int): Maximum number of articles to return; omit to inherit config

    Returns:
        str: A formatted string containing global news data
    """
    return route_to_vendor("get_global_news", curr_date, look_back_days, limit)

@tool
@guard_target_ticker("ticker")
def get_news_windows(
    ticker: Annotated[str, "Target A-share ticker symbol"],
    curr_date: Annotated[str, "Analysis cutoff date in yyyy-mm-dd format"],
    state: Annotated[dict[str, Any] | None, InjectedState] = None,
) -> str:
    """Fetch policy-owned event/theme/official windows for a target.

    Horizon is injected from graph state and is not part of the model-visible
    tool schema. Bare legacy callers use the medium policy.
    """
    horizon = _state_horizon(state)
    return run_news_windows(
        ticker,
        curr_date,
        horizon=horizon,
        analysis_cutoff=parse_analysis_cutoff(
            state.get("analysis_cutoff") if state is not None else None
        ),
    )


def _state_horizon(state: Mapping[str, Any] | None) -> InvestmentHorizon:
    value = state.get("horizon") if state is not None else None
    return value if value in {"short", "medium", "long"} else "medium"


def _public_window_result(raw: object) -> dict[str, object]:
    rendered = str(raw)
    result: dict[str, object] = {
        "status": "ok",
        "data": rendered[:MAX_PREFETCH_DATA_CHARS],
        "truncated": len(rendered) > MAX_PREFETCH_DATA_CHARS,
    }
    if isinstance(raw, CoveredText):
        result["coverage"] = raw.coverage.model_dump(mode="json")
    else:
        result["coverage"] = {
            "completeness": "unknown",
            "degradations": ["source_coverage_not_reported"],
        }
    return result


def run_news_windows(
    ticker: str,
    curr_date: str,
    *,
    horizon: InvestmentHorizon,
    analysis_cutoff: AnalysisCutoffV1 | None = None,
) -> str:
    """Execute deterministic prefetch windows for one run and horizon."""
    market = "a_share" if is_a_share_ticker(ticker) else "global"
    try:
        plan = build_news_prefetch_plan(horizon, curr_date, market=market)
    except ValueError:
        return "Invalid analysis cutoff date or investment horizon."
    result: dict[str, object] = {
        "ticker": ticker,
        "as_of": curr_date,
        "horizon": horizon,
        "policy_version": plan.policy_version,
        "windows": {},
        "results": [],
    }
    windows = result["windows"]
    assert isinstance(windows, dict)

    company_events: dict[str, object] = {}
    company_observations: dict[str, tuple[object, datetime, datetime]] = {}
    for window in plan.company_windows:
        started_at = datetime.now(timezone.utc)
        try:
            raw = route_to_vendor(
                "get_news",
                ticker,
                window.start_date,
                curr_date,
                max_pages=plan.company_news_max_pages,
            )
            ended_at = datetime.now(timezone.utc)
            company_observations[window.window_id] = (raw, started_at, ended_at)
            payload = _public_window_result(raw)
        except Exception as exc:
            payload = {"status": "unavailable", "error_type": type(exc).__name__}
        company_events[window.window_id] = {
            "start_date": window.start_date,
            "end_date": curr_date,
            "lookback_days": window.lookback_days,
            "source_policy": "company_news",
            **payload,
        }
    windows["company_events"] = company_events

    if analysis_cutoff is not None:
        company_result = _company_event_capability_result(
            ticker,
            curr_date,
            horizon=horizon,
            cutoff=analysis_cutoff,
            observations=company_observations,
        )
        result_items = result["results"]
        assert isinstance(result_items, list)
        result_items.append(company_result)

    typed_official: dict[str, Any] | None = None
    if analysis_cutoff is not None:
        typed_official = build_official_disclosure_result(
            ticker,
            curr_date,
            horizon=horizon,
            cutoff=analysis_cutoff,
        )

    if typed_official is not None:
        capability_result = typed_official["capability_result"]
        assert isinstance(capability_result, dict)
        official = {
            "status": typed_official["status"],
            "data": str(typed_official.get("data") or "")[:MAX_PREFETCH_DATA_CHARS],
            "truncated": len(str(typed_official.get("data") or ""))
            > MAX_PREFETCH_DATA_CHARS,
            "capability_result_id": typed_official["capability_result_id"],
            "availability": capability_result["availability"],
            "coverage": capability_result["coverage"],
            "limitations": capability_result["limitations"],
        }
        result_items = result["results"]
        assert isinstance(result_items, list)
        result_items.append(
            {key: value for key, value in typed_official.items() if key != "data"}
        )
    elif market == "a_share":
        try:
            official = _public_window_result(
                route_to_vendor(
                    "get_a_share_cninfo_announcements",
                    ticker,
                    plan.official_start,
                    curr_date,
                    max_pages=plan.official_max_pages,
                )
            )
        except Exception as exc:
            official = {"status": "unavailable", "error_type": type(exc).__name__}
    else:
        official = {
            "status": "unavailable",
            "reason": "official_filings_provider_not_implemented",
        }

    if market == "a_share":
        assert plan.research_reports_start is not None
        assert plan.research_reports_max_pages is not None
        try:
            research_reports = _public_window_result(
                route_to_vendor(
                    "get_a_share_research_reports",
                    ticker,
                    as_of=curr_date,
                    start_date=plan.research_reports_start,
                    max_pages=plan.research_reports_max_pages,
                )
            )
        except Exception as exc:
            research_reports = {
                "status": "unavailable",
                "error_type": type(exc).__name__,
            }
    else:
        research_reports = {
            "status": "unavailable",
            "reason": "a_share_research_reports_not_applicable",
        }
    windows["official"] = {
        "start_date": plan.official_start,
        "end_date": curr_date,
        "lookback_years": plan.official_lookback_years,
        "source_policy": "official_disclosures",
        **official,
    }
    windows["research_reports"] = {
        "start_date": plan.research_reports_start,
        "end_date": curr_date,
        "lookback_years": plan.research_reports_lookback_years,
        "source_policy": "company_research_reports",
        **research_reports,
    }
    return json.dumps(result, ensure_ascii=False)


def create_news_window_prefetch_node():
    """Create the deterministic graph task that precedes the News Analyst."""

    def prefetch(state: Mapping[str, Any]) -> dict[str, str]:
        horizon = _state_horizon(state)
        if time_sensitive_fetch_blocked(state):
            return {
                "news_window_bundle": _news_cutoff_failure_bundle(state, horizon)
            }
        return {
            "news_window_bundle": run_news_windows(
                str(state["company_of_interest"]),
                str(state["trade_date"]),
                horizon=horizon,
                analysis_cutoff=parse_analysis_cutoff(state.get("analysis_cutoff")),
            )
        }

    return prefetch


def _news_cutoff_failure_bundle(
    state: Mapping[str, Any], horizon: InvestmentHorizon
) -> str:
    """Retain the legacy failure shell plus typed negative planned results."""

    legacy = json.loads(
        cutoff_failure_bundle(state, capability="company_event_window")
    )
    cutoff = parse_analysis_cutoff(state.get("analysis_cutoff"))
    assert cutoff is not None and cutoff.status == "invalid"
    plan = build_data_window_plan(
        horizon,
        cutoff.analysis_date,
        market=cutoff.market,
    )
    captured = datetime.now(timezone.utc)
    results = []
    for capability_id in ("company_event_window", "official_disclosures"):
        capability = plan.capability_index()[capability_id]
        source_ids = (
            tuple(capability.required_source_ids)
            + tuple(
                source_id
                for group in capability.required_source_groups
                for source_id in group.source_ids
            )
            + tuple(capability.optional_source_ids)
        )
        attempts = tuple(
            ProviderAttemptV1(
                source_id=source_id,
                provider=source_id.split(".", 1)[0],
                outcome="skipped_unobserved",
                reason_code="analysis_cutoff_resolution_failed",
                recorded_at=captured,
            )
            for source_id in source_ids
        )
        records = tuple(
            SourceCoverageV1(
                capability=capability_id,
                source_id=source_id,
                item_count=0,
                completeness="unavailable",
                sources=(source_id,),
                degradations=("analysis_cutoff_resolution_failed",),
                as_of=cutoff.analysis_date,
            )
            for source_id in source_ids
        )
        coverage = BundleCoverageV1.build(
            capability=capability_id,
            records=records,
            required_source_ids=capability.required_source_ids,
            required_source_groups=capability.required_source_groups,
            optional_source_ids=capability.optional_source_ids,
        )
        typed = CapabilityResultV1(
            capability=capability_id,
            symbol=cutoff.ticker,
            market=cutoff.market,
            analysis_date=cutoff.analysis_date,
            analysis_cutoff_at=None,
            availability="invalid",
            freshness="unknown",
            coverage=coverage,
            source_ids=source_ids,
            attempts=attempts,
            degradation_codes=("analysis_cutoff_resolution_failed",),
            limitations=("analysis_cutoff_resolution_failed",),
        )
        results.append(
            {
                "capability": capability_id,
                "requirement": capability.requirement,
                "status": "unavailable",
                "capability_result_id": typed.capability_result_id,
                "capability_result": typed.semantic_payload(),
            }
        )
    legacy["results"] = results
    return json.dumps(legacy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _company_event_capability_result(
    ticker: str,
    analysis_date: str,
    *,
    horizon: InvestmentHorizon,
    cutoff: AnalysisCutoffV1,
    observations: Mapping[str, tuple[object, datetime, datetime]],
) -> dict[str, object]:
    plan = build_data_window_plan(
        horizon,
        analysis_date,
        market=cutoff.market,
    ).capability_index()["company_event_window"]
    source_ids = tuple(
        source_id
        for group in plan.required_source_groups
        for source_id in group.source_ids
    ) + tuple(plan.required_source_ids) + tuple(plan.optional_source_ids)
    widest = min(
        build_news_prefetch_plan(
            horizon, analysis_date, market=cutoff.market
        ).company_windows,
        key=lambda window: window.start_date,
    )
    observed = observations.get(widest.window_id)
    raw = observed[0] if observed is not None else None
    source_coverage = raw.coverage if isinstance(raw, CoveredText) else None
    selected_source = (
        source_coverage.source_id
        if source_coverage is not None and source_coverage.source_id in source_ids
        else None
    )
    captured = datetime.now(timezone.utc)
    attempts = tuple(
        ProviderAttemptV1(
            source_id=source_id,
            provider=source_id.split(".", 1)[0],
            outcome="observed" if source_id == selected_source else "skipped_unobserved",
            reason_code=(
                "provider_payload_observed"
                if source_id == selected_source
                else "source_not_observed"
            ),
            recorded_at=captured,
            started_at=(observed[1] if source_id == selected_source and observed else None),
            ended_at=(observed[2] if source_id == selected_source and observed else None),
        )
        for source_id in source_ids
    )
    records = []
    for source_id, attempt in zip(source_ids, attempts, strict=True):
        if source_id == selected_source and source_coverage is not None:
            projected = source_coverage.model_dump(mode="json")
            projected["capability"] = "company_event_window"
            records.append(SourceCoverageV1.model_validate(projected))
        else:
            records.append(
                SourceCoverageV1(
                    capability="company_event_window",
                    source_id=source_id,
                    requested_start=widest.start_date,
                    requested_end=analysis_date,
                    item_count=0,
                    completeness="unavailable",
                    sources=(source_id,),
                    degradations=(attempt.reason_code,),
                    as_of=analysis_date,
                )
            )
    coverage = BundleCoverageV1.build(
        capability="company_event_window",
        records=tuple(records),
        required_source_ids=plan.required_source_ids,
        required_source_groups=plan.required_source_groups,
        optional_source_ids=plan.optional_source_ids,
    )
    availability = aggregate_capability_availability(coverage, attempts)
    reached = tuple(attempt for attempt in attempts if attempt.reached_provider)
    typed = CapabilityResultV1(
        capability="company_event_window",
        symbol=ticker,
        market=cutoff.market,
        analysis_date=analysis_date,
        analysis_cutoff_at=cutoff.analysis_cutoff_at,
        availability=availability,
        freshness=(
            "current" if availability in {"available", "partial"} else "unknown"
        ),
        coverage=coverage,
        source_ids=source_ids,
        attempts=attempts,
        effective_period=f"{widest.lookback_days}_calendar_days",
        source_observed_at=(
            datetime.fromisoformat(source_coverage.actual_end).replace(
                tzinfo=timezone.utc
            )
            if source_coverage is not None and source_coverage.actual_end
            else None
        ),
        fetched_at=(observed[1] if reached and observed is not None else None),
        degradation_codes=tuple(
            dict.fromkeys(
                degradation
                for record in records
                for degradation in record.degradations
            )
        ),
        limitations=(
            () if selected_source is not None else ("source_coverage_not_reported",)
        ),
    )
    return {
        "capability": "company_event_window",
        "requirement": plan.requirement,
        "status": "ok" if availability in {"available", "partial"} else "unavailable",
        "capability_result_id": typed.capability_result_id,
        "capability_result": typed.semantic_payload(),
    }


@tool
@guard_target_ticker("ticker")
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """
    Retrieve insider transaction information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
    Returns:
        str: A report of insider transaction data
    """
    return route_to_vendor("get_insider_transactions", ticker)
