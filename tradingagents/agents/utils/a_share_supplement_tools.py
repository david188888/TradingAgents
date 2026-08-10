"""Code-owned A-share supplemental bundle for the Sentiment Analyst."""

from __future__ import annotations

import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.dataflows.coverage import CoveredText
from tradingagents.dataflows.errors import DataSourceUnavailableError, VendorError
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.ticker_utils import is_a_share_ticker
from tradingagents.research.a_share_supplement import (
    AshareSupplementCapabilityV1,
    AshareSupplementPlanV1,
    build_a_share_supplement_plan,
)
from tradingagents.research.horizon_policy import InvestmentHorizon

MAX_PARALLEL_SUPPLEMENTS = 3
_POINT_IN_TIME_CAPABILITIES = frozenset(
    {
        "industry_board_flow",
        "concept_board_flow",
        "hot_list",
        "hot_concept",
        "concept_blocks",
        "northbound_holdings",
        "interactive_questions",
        "cls_telegraph",
    }
)


def _current_shanghai_date() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def _state_horizon(state: Mapping[str, Any]) -> InvestmentHorizon:
    value = state.get("horizon")
    return value if value in {"short", "medium", "long"} else "medium"


def _invoke_capability(
    capability: AshareSupplementCapabilityV1,
    plan: AshareSupplementPlanV1,
    ticker: str,
) -> object:
    capability_id = capability.capability_id
    if capability_id == "capital_flow":
        return route_to_vendor(
            capability.route_method,
            ticker,
            plan.capital_flow_start,
            plan.as_of,
        )
    if capability_id == "northbound_flow":
        return route_to_vendor(
            capability.route_method,
            plan.capital_flow_start,
            plan.as_of,
        )
    if capability_id in {"margin_financing", "insider_trades"}:
        return route_to_vendor(
            capability.route_method,
            ticker,
            plan.capital_flow_start,
            plan.as_of,
        )
    if capability_id == "northbound_holdings":
        return route_to_vendor(capability.route_method, ticker)
    if capability_id == "dragon_tiger":
        return route_to_vendor(capability.route_method, ticker, plan.as_of)
    if capability_id in {"industry_board_flow", "concept_board_flow"}:
        board_type = "industry" if capability_id.startswith("industry") else "concept"
        return route_to_vendor(
            capability.route_method,
            board_type,
            plan.board_period,
            20,
        )
    if capability_id == "hot_list":
        period = "hour" if plan.horizon == "short" else "day"
        return route_to_vendor(capability.route_method, period)
    if capability_id in {"hot_concept", "concept_blocks", "interactive_questions"}:
        return route_to_vendor(capability.route_method, ticker)
    if capability_id == "cls_telegraph":
        return route_to_vendor(capability.route_method)
    raise ValueError(f"unsupported A-share supplement: {capability_id}")


def _fetch_capability(
    capability: AshareSupplementCapabilityV1,
    plan: AshareSupplementPlanV1,
    ticker: str,
    *,
    point_in_time_allowed: bool,
) -> dict[str, object]:
    if capability.capability_id == "industry_research_reports":
        return {
            "capability": capability.capability_id,
            "route_method": capability.route_method,
            "status": "unavailable",
            "degradations": ["industry_report_qtype1_not_verified"],
            "substitution_allowed": False,
        }
    if (
        capability.capability_id in _POINT_IN_TIME_CAPABILITIES
        and not point_in_time_allowed
    ):
        return {
            "capability": capability.capability_id,
            "route_method": capability.route_method,
            "status": "unavailable",
            "degradations": ["point_in_time_source_not_replayable"],
        }
    try:
        raw = _invoke_capability(capability, plan, ticker)
    except Exception as exc:
        public_type = (
            "source_unavailable"
            if isinstance(exc, (DataSourceUnavailableError, VendorError))
            else "source_failed"
        )
        return {
            "capability": capability.capability_id,
            "route_method": capability.route_method,
            "status": "unavailable",
            "degradations": ["capability_unavailable"],
            "error_type": public_type,
        }
    rendered = str(raw)
    if not rendered or rendered.startswith(("NO_DATA_AVAILABLE:", "Data unavailable")):
        return {
            "capability": capability.capability_id,
            "route_method": capability.route_method,
            "status": "unavailable",
            "degradations": ["no_usable_data"],
        }
    result: dict[str, object] = {
        "capability": capability.capability_id,
        "route_method": capability.route_method,
        "status": "ok",
        "data": rendered[: capability.max_chars],
        "truncated": len(rendered) > capability.max_chars,
    }
    if isinstance(raw, CoveredText):
        result["coverage"] = raw.coverage.model_dump(mode="json")
    else:
        result["coverage"] = {
            "completeness": "unknown",
            "as_of": plan.as_of,
            "degradations": ["provider_coverage_not_reported"],
        }
    return result


def run_a_share_supplement_prefetch(
    ticker: str,
    analysis_date: str,
    *,
    horizon: InvestmentHorizon,
) -> str:
    """Fetch a stable, horizon-budgeted bundle with per-capability failures."""
    if not is_a_share_ticker(ticker):
        return json.dumps(
            {
                "schema_version": 1,
                "ticker": ticker,
                "as_of": analysis_date,
                "horizon": horizon,
                "status": "not_applicable",
                "results": [],
            },
            ensure_ascii=False,
        )
    plan = build_a_share_supplement_plan(horizon, analysis_date)
    point_in_time_allowed = analysis_date == _current_shanghai_date()
    result_by_id: dict[str, dict[str, object]] = {}
    with ThreadPoolExecutor(
        max_workers=min(MAX_PARALLEL_SUPPLEMENTS, len(plan.capabilities))
    ) as executor:
        futures = {
            executor.submit(
                _fetch_capability,
                capability,
                plan,
                ticker,
                point_in_time_allowed=point_in_time_allowed,
            ): capability
            for capability in plan.capabilities
        }
        for future in as_completed(futures):
            capability = futures[future]
            result_by_id[capability.capability_id] = future.result()
    results = [result_by_id[item.capability_id] for item in plan.capabilities]
    ok_count = sum(item["status"] == "ok" for item in results)
    status = "ok" if ok_count == len(results) else ("partial" if ok_count else "unavailable")
    return json.dumps(
        {
            "schema_version": 1,
            "policy_version": plan.policy_version,
            "ticker": ticker,
            "as_of": analysis_date,
            "horizon": horizon,
            "status": status,
            "capital_flow_start": plan.capital_flow_start,
            "requested_flow_windows": plan.requested_flow_windows,
            "board_period": plan.board_period,
            "parallelism_limit": MAX_PARALLEL_SUPPLEMENTS,
            "results": results,
        },
        ensure_ascii=False,
    )


def create_a_share_supplement_prefetch_node():
    """Create the graph task that owns optional A-share supplement fetching."""

    def prefetch(state: Mapping[str, Any]) -> dict[str, str]:
        return {
            "a_share_supplement_bundle": run_a_share_supplement_prefetch(
                str(state["company_of_interest"]),
                str(state["trade_date"]),
                horizon=_state_horizon(state),
            )
        }

    return prefetch
