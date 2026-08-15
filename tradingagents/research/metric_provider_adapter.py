"""Strict adapters from frozen A-share statement bundles to public metrics."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from tradingagents.dataflows.ticker_utils import normalize_ticker_symbol

from .metric_models import MetricObservationV1

_MONETARY_UNIT = "CNY_100m"

# These aliases intentionally prefer attributable net income and named cash-flow
# lines. Generic labels are not accepted when their accounting scope is unclear.
_FIELD_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "income_statement": {
        "revenue": ("revenue", "营业收入"),
        "net_income": (
            "n_income_attr_p",
            "归属于母公司股东的净利润",
            "归母净利润",
        ),
        "gross_profit": ("gross_profit", "毛利", "营业毛利"),
    },
    "cash_flow": {
        "operating_cash_flow": (
            "n_cashflow_act",
            "经营活动产生的现金流量净额",
        ),
    },
    "balance_sheet": {
        "total_assets": ("total_assets", "资产总计"),
        "total_liabilities": ("total_liab", "total_liabilities", "负债合计"),
        "equity": (
            "total_hldr_eqy_exc_min_int",
            "total_hldr_eqy_inc_min_int",
            "total_hldr_eqy",
            "股东权益合计",
            "所有者权益合计",
        ),
    },
}
_PERIOD_ALIASES = ("end_date", "fiscaldateending", "报告期", "报告日")
_FILING_ALIASES = ("ann_date", "f_ann_date", "reporteddate", "filingdate", "公告日期")


def observations_from_fundamentals_bundle(
    bundle: Mapping[str, Any],
    *,
    run_id: str,
    entity_id: str,
    analysis_cutoff: date,
    evidence_ref_id: str,
) -> tuple[MetricObservationV1, ...]:
    """Convert only point-in-time-proven rows into raw metric observations.

    The prefetch bundle is public evidence, but its rendered statement text is
    still treated as untrusted provider output. Unknown field names, missing
    filing dates, ambiguous net-income labels, invalid units, and post-cutoff
    rows are skipped instead of being guessed.
    """
    bundle_ticker = bundle.get("ticker")
    if bundle_ticker is not None:
        try:
            if normalize_ticker_symbol(str(bundle_ticker)) != normalize_ticker_symbol(entity_id):
                return ()
        except ValueError:
            return ()
    observations: list[MetricObservationV1] = []
    target_ticker = normalize_ticker_symbol(entity_id)
    for result in bundle.get("results", ()):
        if not isinstance(result, Mapping):
            continue
        frequency = str(result.get("frequency") or "")
        if frequency not in {"quarterly", "annual"}:
            continue
        for statement in result.get("statements", ()):
            if not isinstance(statement, Mapping) or statement.get("status") not in {"ok", "partial"}:
                continue
            statement_name = str(statement.get("statement") or "")
            aliases = _FIELD_ALIASES.get(statement_name)
            if aliases is None:
                continue
            source_id = str(statement.get("source_id") or "")
            if not source_id.startswith(("tushare.", "sina.")):
                continue
            if frequency == "quarterly" and "# Period basis: single_period" not in str(statement.get("data") or ""):
                continue
            data_text = str(statement.get("data") or "")
            if "# Monetary raw unit: CNY" not in data_text or "# Monetary normalization formula: raw_value / 100000000" not in data_text:
                continue
            for row in _csv_rows(data_text):
                row_ticker = _first_value(row, ("ts_code", "代码", "股票代码"))
                if source_id.startswith("tushare."):
                    try:
                        if not row_ticker or normalize_ticker_symbol(row_ticker) != target_ticker:
                            continue
                    except ValueError:
                        continue

                period = _parse_date(_first_value(row, _PERIOD_ALIASES))
                filing_date = _parse_date(_first_value(row, _FILING_ALIASES))
                if period is None or filing_date is None or filing_date > analysis_cutoff:
                    continue
                for metric_id, field_names in aliases.items():
                    value = _parse_number(_first_value(row, field_names))
                    if value is None:
                        continue
                    observations.append(
                        MetricObservationV1(
                            observation_id=(
                                f"obs:{entity_id.casefold()}:{metric_id}:{period.isoformat()}:{frequency}"
                            ),
                            run_id=run_id,
                            metric_id=metric_id,
                            entity_id=entity_id,
                            period=period.isoformat(),
                            as_of=filing_date,
                            frequency=frequency,
                            value=value / 100_000_000,
                            unit=_MONETARY_UNIT,
                            source_evidence_ref_ids=(evidence_ref_id,),
                            point_in_time=True,
                        )
                    )
    return tuple(
        sorted(
            {item.observation_id: item for item in observations}.values(),
            key=lambda item: (item.metric_id, item.period, item.frequency),
        )
    )


def _csv_rows(rendered: str) -> tuple[dict[str, str], ...]:
    lines = [line for line in rendered.splitlines() if line and not line.startswith("#")]
    if not lines:
        return ()
    try:
        rows = tuple(csv.DictReader(io.StringIO("\n".join(lines))))
    except csv.Error:
        return ()
    return tuple(
        {
            _normalize_key(str(key)): str(value or "").strip()
            for key, value in row.items()
            if key is not None
        }
        for row in rows
        if isinstance(row, Mapping)
    )


def _first_value(row: Mapping[str, str], aliases: tuple[str, ...]) -> str:
    normalized = {_normalize_key(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_normalize_key(alias), "")
        if value:
            return value
    return ""


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", value.casefold())


def _parse_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace("/", "-")):
        try:
            return date.fromisoformat(candidate[:10])
        except ValueError:
            pass
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _parse_number(value: str) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text or text.casefold() in {"nan", "none", "null", "--", "-"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


__all__ = ["observations_from_fundamentals_bundle"]
