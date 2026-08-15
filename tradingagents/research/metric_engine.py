"""Pure deterministic calculations over structured metric observations."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import date

from .metric_catalog import metric_definition
from .metric_models import FormulaEvaluationV1, MetricObservationV1

_FORMULAS: dict[str, tuple[str, Callable[[dict[str, float]], float]]] = {
    "revenue_yoy": (
        "(revenue_current - revenue_prior) / abs(revenue_prior)",
        lambda x: (x["revenue_current"] - x["revenue_prior"]) / abs(x["revenue_prior"]),
    ),
    "net_income_yoy": (
        "(net_income_current - net_income_prior) / abs(net_income_prior)",
        lambda x: (x["net_income_current"] - x["net_income_prior"]) / abs(x["net_income_prior"]),
    ),
    "operating_cash_flow_yoy": (
        "(operating_cash_flow_current - operating_cash_flow_prior) / abs(operating_cash_flow_prior)",
        lambda x: (x["operating_cash_flow_current"] - x["operating_cash_flow_prior"])
        / abs(x["operating_cash_flow_prior"]),
    ),
    "gross_margin": ("gross_profit / revenue", lambda x: x["gross_profit"] / x["revenue"]),
    "net_margin": ("net_income / revenue", lambda x: x["net_income"] / x["revenue"]),
    "roe": (
        "net_income / ((equity_begin + equity_end) / 2)",
        lambda x: x["net_income"] / ((x["equity_begin"] + x["equity_end"]) / 2),
    ),
    "cash_conversion": (
        "operating_cash_flow / net_income",
        lambda x: x["operating_cash_flow"] / x["net_income"],
    ),
    "debt_ratio": (
        "total_liabilities / total_assets",
        lambda x: x["total_liabilities"] / x["total_assets"],
    ),
    "pe": ("equity_value / net_income", lambda x: x["equity_value"] / x["net_income"]),
    "pb": ("equity_value / equity", lambda x: x["equity_value"] / x["equity"]),
    "ps": ("equity_value / revenue", lambda x: x["equity_value"] / x["revenue"]),
}


def _observation_map(
    inputs: Mapping[str, MetricObservationV1] | tuple[MetricObservationV1, ...],
) -> dict[str, MetricObservationV1]:
    if isinstance(inputs, Mapping):
        result = dict(inputs)
    else:
        result = {item.metric_id: item for item in inputs}
    if len(result) != len(set(result)):
        raise ValueError("metric input keys must be unique")
    return result


def _expected_input_metric_id(input_key: str) -> str:
    return input_key.removesuffix("_current").removesuffix("_prior")


def _validate_input_semantics(
    metric_id: str,
    values: Mapping[str, MetricObservationV1],
) -> None:
    definition = metric_definition(metric_id)
    missing = set(definition.required_inputs).difference(values)
    if missing:
        return
    expected = {
        _expected_input_metric_id(key) for key in definition.required_inputs
    }
    actual = {item.metric_id for item in values.values()}
    if actual != expected:
        raise ValueError(
            f"metric inputs do not match {metric_id}: expected {sorted(expected)}, got {sorted(actual)}"
        )
    entities = {item.entity_id for item in values.values()}
    runs = {item.run_id for item in values.values()}
    frequencies = {item.frequency for item in values.values()}
    as_ofs = {item.as_of for item in values.values()}
    units = {item.unit for item in values.values()}
    if len(entities) != 1:
        raise ValueError("metric inputs must belong to one entity")
    if len(runs) != 1:
        raise ValueError("metric inputs must belong to one run")
    if len(frequencies) != 1:
        raise ValueError("metric inputs must share frequency")
    if len(units) != 1:
        raise ValueError("metric inputs must share units")
    if metric_id.endswith("_yoy"):
        base = metric_id.removesuffix("_yoy")
        current = values.get(f"{base}_current")
        prior = values.get(f"{base}_prior")
        if current is None or prior is None or current.period <= prior.period:
            raise ValueError("yoy inputs must have distinct ordered periods")
    elif len(as_ofs) != 1:
        raise ValueError("metric inputs must share as_of")


def _output_context(
    values: Mapping[str, MetricObservationV1], *, period: str | None
) -> tuple[str, date, str, str]:
    observations = tuple(values.values())
    runs = {item.run_id for item in observations}
    if len(runs) != 1:
        raise ValueError("metric inputs must belong to one run")
    frequencies = {item.frequency for item in observations}
    if len(frequencies) != 1:
        raise ValueError("metric inputs must share frequency")
    first = observations[0]
    return period or first.period, max(item.as_of for item in observations), first.frequency, first.run_id


def unavailable_observation(
    metric_id: str,
    *,
    run_id: str,
    entity_id: str,
    period: str,
    as_of: date,
    frequency: str,
    reason: str,
) -> MetricObservationV1:
    return MetricObservationV1(
        observation_id=f"obs:{entity_id.casefold()}:{metric_id}:{period.casefold()}",
        run_id=run_id,
        metric_id=metric_id,
        entity_id=entity_id,
        period=period,
        as_of=as_of,
        frequency=frequency,
        unit=metric_definition(metric_id).unit,
        availability="unavailable",
        unavailable_reason=reason,
        observation_kind="derived",
    )


def calculate_metric(
    metric_id: str,
    inputs: Mapping[str, MetricObservationV1] | tuple[MetricObservationV1, ...],
    *,
    output_id: str | None = None,
    period: str | None = None,
) -> FormulaEvaluationV1:
    """Evaluate one catalog formula, returning a typed unavailable result on gaps."""
    definition = metric_definition(metric_id)
    try:
        formula, operation = _FORMULAS[metric_id]
    except KeyError as exc:
        raise KeyError(f"metric has no deterministic implementation: {metric_id}") from exc
    values = _observation_map(inputs)
    _validate_input_semantics(metric_id, values)
    missing = [key for key in definition.required_inputs if key not in values]
    if missing:
        if not values:
            raise ValueError("metric calculation requires at least one input")
        context_period, as_of, frequency, run_id = _output_context(values, period=period)
        entity_id = next(iter(values.values())).entity_id
        output = unavailable_observation(
            metric_id,
            run_id=run_id,
            entity_id=entity_id,
            period=context_period,
            as_of=as_of,
            frequency=frequency,
            reason="missing_input:" + ",".join(missing),
        )
        return FormulaEvaluationV1(
            evaluation_id=output_id or f"{output.observation_id}:evaluation",
            run_id=run_id,
            metric_id=metric_id,
            formula=formula,
            input_observation_ids=tuple(item.observation_id for item in values.values()),
            output_observation=output,
            status="unavailable",
            limitations=("required input is unavailable",),
        )

    ordered = {key: values[key] for key in definition.required_inputs}
    context_period, as_of, frequency, run_id = _output_context(ordered, period=period)
    entity_id = next(iter(ordered.values())).entity_id
    unavailable = [item for item in ordered.values() if item.availability != "available"]
    unit_groups = {item.unit for item in ordered.values()}
    reason: str | None = None
    if unavailable:
        reason = "input_unavailable"
    elif len(unit_groups) > 1:
        reason = "inconsistent_input_units"
    elif any(not math.isfinite(float(item.value)) for item in ordered.values()):
        reason = "non_finite_input"
    else:
        denominator_keys = {
            "revenue": ("revenue", "revenue_prior", "net_income"),
            "net_income": ("net_income", "net_income_prior"),
            "operating_cash_flow": ("operating_cash_flow_prior",),
            "equity": ("equity", "equity_begin", "equity_end"),
            "total_assets": ("total_assets",),
        }
        for key in denominator_keys.get(metric_id, ()):
            if key in ordered and float(ordered[key].value) == 0:
                reason = "zero_denominator"
                break
        if metric_id == "roe" and (
            float(ordered["equity_begin"].value) + float(ordered["equity_end"].value)
        ) == 0:
            reason = "zero_denominator"
        if metric_id in {"cash_conversion", "pe", "pb", "ps"}:
            denominator = {
                "cash_conversion": "net_income",
                "pe": "net_income",
                "pb": "equity",
                "ps": "revenue",
            }[metric_id]
            if float(ordered[denominator].value) <= 0:
                reason = "non_positive_denominator"
        if metric_id == "debt_ratio" and float(ordered["total_assets"].value) <= 0:
            reason = "non_positive_denominator"
    if reason:
        output = unavailable_observation(
            metric_id,
            run_id=run_id,
            entity_id=entity_id,
            period=context_period,
            as_of=as_of,
            frequency=frequency,
            reason=reason,
        )
        status = "unavailable"
        limitations = (reason,)
    else:
        try:
            result = float(operation({key: float(item.value) for key, item in ordered.items()}))
        except (ArithmeticError, KeyError, ValueError) as exc:
            result = math.nan
            reason = f"calculation_error:{type(exc).__name__}"
        if not math.isfinite(result):
            output = unavailable_observation(
                metric_id,
                run_id=run_id,
                entity_id=entity_id,
                period=context_period,
                as_of=as_of,
                frequency=frequency,
                reason=reason or "non_finite_result",
            )
            status = "unavailable"
            limitations = (reason or "non_finite_result",)
        else:
            output = MetricObservationV1(
                observation_id=output_id or f"obs:{entity_id.casefold()}:{metric_id}:{context_period.casefold()}",
                run_id=run_id,
                metric_id=metric_id,
                entity_id=entity_id,
                period=context_period,
                as_of=as_of,
                frequency=frequency,
                value=result,
                unit=definition.unit,
                observation_kind="derived",
            )
            status = "available"
            limitations = ()
    return FormulaEvaluationV1(
        evaluation_id=output_id or f"{output.observation_id}:evaluation",
        run_id=run_id,
        metric_id=metric_id,
        formula=formula,
        input_observation_ids=tuple(item.observation_id for item in ordered.values()),
        output_observation=output,
        status=status,
        limitations=limitations,
    )


def calculate_yoy(
    metric_id: str,
    current: MetricObservationV1,
    prior: MetricObservationV1,
    *,
    output_id: str | None = None,
) -> FormulaEvaluationV1:
    if metric_id not in {"revenue_yoy", "net_income_yoy", "operating_cash_flow_yoy"}:
        raise ValueError("calculate_yoy requires a yoy metric")
    base = metric_id.removesuffix("_yoy")
    return calculate_metric(
        metric_id,
        {f"{base}_current": current, f"{base}_prior": prior},
        output_id=output_id,
        period=current.period,
    )


def calculate_roe(
    net_income: MetricObservationV1,
    equity_begin: MetricObservationV1,
    equity_end: MetricObservationV1,
    *,
    output_id: str | None = None,
) -> FormulaEvaluationV1:
    return calculate_metric(
        "roe",
        {"net_income": net_income, "equity_begin": equity_begin, "equity_end": equity_end},
        output_id=output_id,
    )
