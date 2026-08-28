"""Parse committed state bundles into typed inputs for the valuation chain.

This module is the assembly-layer glue between the deterministic prefetch
bundles stored in run state and the pure decision chain in ``valuation``.
Parsing is deliberately strict: missing or malformed rows degrade the affected
input to ``None`` (with a reason note upstream), never to a guessed value.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Mapping
from datetime import date
from typing import Any

from tradingagents.research.metric_provider_adapter import (
    observations_from_fundamentals_bundle,
)
from tradingagents.research.valuation import (
    DailyMultipleV1,
    EarningsBaseV1,
    ValuationInputsV1,
    ValuationSnapshotInputV1,
)

logger = logging.getLogger(__name__)


def _csv_rows_from_rendered(rendered: str) -> list[dict[str, str]]:
    """Parse a provider-rendered report: '#' comment lines, then one CSV table."""
    lines = [line for line in rendered.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        return []
    try:
        reader = csv.DictReader(io.StringIO("\n".join(lines)))
        return [dict(row) for row in reader]
    except csv.Error:
        return []


def _number(raw: Any) -> float | None:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN/inf
        return None
    return value


def _truthy_number(raw: Any) -> float | None:
    """Provider rows encode missing multiples as 0; treat those as absent."""
    value = _number(raw)
    if value is None or value <= 0:
        return None
    return value


def _day(raw: Any) -> date | None:
    text = str(raw or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _latest_annual_base(
    observations: tuple[Any, ...], metric_id: str
) -> EarningsBaseV1 | None:
    candidates = [
        item
        for item in observations
        if item.metric_id == metric_id and item.frequency == "annual" and item.value is not None
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda item: (item.period, item.as_of))
    value = float(latest.value)
    if value <= 0:
        return EarningsBaseV1(metric_id=metric_id, value_yi=value, period=latest.period)
    return EarningsBaseV1(metric_id=metric_id, value_yi=value, period=latest.period)


def _snapshot_from_rows(rows: list[dict[str, str]], fallback_day: date) -> ValuationSnapshotInputV1 | None:
    for row in reversed(rows):
        price = _truthy_number(row.get("Price"))
        if price is None:
            continue
        return ValuationSnapshotInputV1(
            as_of=fallback_day,
            price=price,
            pe_ttm=_truthy_number(row.get("PE TTM")),
            pb=_truthy_number(row.get("PB")),
            total_market_cap_yi=_truthy_number(row.get("Market Cap (yi)")),
        )
    return None


def _history_from_rows(
    rows: list[dict[str, str]],
    pe_column: str,
    pb_column: str,
) -> tuple[tuple[DailyMultipleV1, ...], tuple[DailyMultipleV1, ...]]:
    pe_items: list[DailyMultipleV1] = []
    pb_items: list[DailyMultipleV1] = []
    for row in rows:
        day = _day(row.get("date") or row.get("Date"))
        if day is None:
            continue
        pe_value = _truthy_number(row.get(pe_column))
        if pe_value is not None:
            pe_items.append(DailyMultipleV1(day=day, value=pe_value))
        pb_value = _truthy_number(row.get(pb_column))
        if pb_value is not None:
            pb_items.append(DailyMultipleV1(day=day, value=pb_value))
    return tuple(sorted(pe_items, key=lambda item: item.day)), tuple(
        sorted(pb_items, key=lambda item: item.day)
    )


def _prices_from_adjusted(adjusted_data: object) -> tuple[tuple[date, float], ...]:
    rendered = ""
    if isinstance(adjusted_data, Mapping):
        rendered = str(adjusted_data.get("data") or "")
    elif isinstance(adjusted_data, str):
        rendered = adjusted_data
    items: list[tuple[date, float]] = []
    for row in _csv_rows_from_rendered(rendered):
        # Column variants: generic "Date"/"Close" and the Wind kline
        # "TIME"/"MATCH" settlement pair used by wind.stock_data.get_stock_kline.
        day = _day(row.get("Date") or row.get("TIME"))
        close = _truthy_number(row.get("Close"))
        if close is None:
            close = _truthy_number(row.get("MATCH"))
        if day is not None and close is not None:
            items.append((day, close))
    return tuple(sorted(items, key=lambda item: item[0]))


def _verified_price_from_adjusted(adjusted: Mapping[str, Any] | None) -> tuple[date, float] | None:
    """Prefer the run's verified market quote over any rendered close."""
    if adjusted is None:
        return None
    quote = adjusted.get("quote_snapshot")
    if not isinstance(quote, Mapping) or quote.get("status") != "available":
        return None
    price = _truthy_number(quote.get("market_price"))
    observed_on = quote.get("price_as_of")
    if price is None:
        return None
    day = _day(observed_on) if observed_on else None
    return (day or date.min, price)


def parse_valuation_inputs(
    *,
    run_id: str,
    ticker: str,
    analysis_cutoff: date,
    valuation_bundle: Mapping[str, Any] | None,
    adjusted_price_bundle: Mapping[str, Any] | None,
    fundamentals_bundle: Mapping[str, Any] | None,
) -> ValuationInputsV1 | None:
    """Build typed decision-chain inputs; returns None only on hard errors."""
    pe_history: tuple[DailyMultipleV1, ...] = ()
    pb_history: tuple[DailyMultipleV1, ...] = ()
    snapshot: ValuationSnapshotInputV1 | None = None
    verified_quote = _verified_price_from_adjusted(adjusted_price_bundle)

    if isinstance(valuation_bundle, Mapping):
        results = valuation_bundle.get("results")
        if isinstance(results, list):
            for result in results:
                if not isinstance(result, Mapping) or result.get("status") != "ok":
                    continue
                capability = str(result.get("capability") or "")
                data_text = str(result.get("data") or "")
                rows = _csv_rows_from_rendered(data_text)
                if capability == "valuation_snapshot":
                    snapshot = _snapshot_from_rows(rows, analysis_cutoff)
                elif capability == "valuation_history":
                    pe_history, pb_history = _history_from_rows(rows, "peTTM", "pbMRQ")

    prices = _prices_from_adjusted(
        (adjusted_price_bundle or {}).get("adjusted")
        if isinstance(adjusted_price_bundle, Mapping)
        else None
    )
    if verified_quote is not None:
        verified_day, verified_price = verified_quote
        if verified_day == date.min:
            verified_day = prices[-1][0] if prices else analysis_cutoff
        prices = tuple(item for item in prices if item[0] <= verified_day)

    annual_observations: tuple[Any, ...] = ()
    if fundamentals_bundle is not None:
        from tradingagents.research.research_package import _bundle_ref_id

        ref_id = _bundle_ref_id(fundamentals_bundle)
        try:
            annual_observations = observations_from_fundamentals_bundle(
                fundamentals_bundle,
                run_id=run_id,
                entity_id=ticker,
                analysis_cutoff=analysis_cutoff,
                evidence_ref_id=ref_id,
            )
        except Exception as exc:  # noqa: BLE001 - degraded fundamentals stay partial
            logger.warning("valuation inputs: fundamentals observations failed (%s)", exc)

    if (
        snapshot is None
        and not pe_history
        and not pb_history
        and not prices
        and not annual_observations
    ):
        return None

    return ValuationInputsV1(
        run_id=run_id,
        ticker=ticker,
        as_of=analysis_cutoff,
        snapshot=snapshot,
        net_income_annual=_latest_annual_base(annual_observations, "net_income"),
        equity_annual=_latest_annual_base(annual_observations, "equity"),
        closing_prices=prices,
        pe_history=pe_history,
        pb_history=pb_history,
        peers=None,
    )


def load_committed_bundle(store: Any, run_id: str, state_key: str) -> dict[str, Any] | None:
    """Read the latest committed public bundle JSON for one state key."""
    import hashlib

    best: tuple[int, str] | None = None
    for event in store.read_events(run_id):
        if event.type != "artifact.written" or event.status != "committed":
            continue
        payload = event.payload
        if payload.get("state_key") != state_key:
            continue
        sequence = payload.get("committed_sequence")
        artifact_id = payload.get("artifact_id")
        if isinstance(sequence, int) and isinstance(artifact_id, str) and (
            best is None or sequence > best[0]
        ):
            best = (sequence, artifact_id)
    if best is None:
        return None
    try:
        raw = store.read_artifact(run_id, best[1])
        expected_hash = ""
        for event in store.read_events(run_id):
            if (
                event.type == "artifact.written"
                and event.payload.get("artifact_id") == best[1]
                and event.payload.get("content_sha256")
            ):
                expected_hash = str(event.payload["content_sha256"])
                break
        if expected_hash and hashlib.sha256(raw).hexdigest() != expected_hash:
            return None
        value = json.loads(raw)
    except Exception:  # noqa: BLE001 - bundle degradation must not break the run
        return None
    return value if isinstance(value, dict) else None
