import json
from collections.abc import Mapping
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from tradingagents.agents.utils.tool_guard import guard_target_ticker
from tradingagents.dataflows.coverage import CoveredText
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.ticker_utils import is_a_share_ticker
from tradingagents.research.analysis_cutoff import (
    AnalysisCutoffV1,
    cutoff_failure_bundle,
    parse_analysis_cutoff,
    time_sensitive_fetch_blocked,
)
from tradingagents.research.horizon_policy import InvestmentHorizon
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
    for window in plan.company_windows:
        try:
            payload = _public_window_result(
                route_to_vendor(
                    "get_news",
                    ticker,
                    window.start_date,
                    curr_date,
                    max_pages=plan.company_news_max_pages,
                )
            )
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
                "news_window_bundle": cutoff_failure_bundle(
                    state, capability="company_event_window"
                )
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
