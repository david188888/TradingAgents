"""Numeric source semantics, not model explanations or display prose."""

from copy import deepcopy
from decimal import Decimal

import pytest

from tests.test_minimum_evidence import record
from tradingagents.research.numeric_catalog import (
    build_numeric_catalog,
    project_numeric_catalog,
    render_numeric_anchor,
    validate_numeric_catalog,
)


def growth_record(*, base="1000000000"):
    def mutate(documents):
        for document in documents:
            for row in document["numeric_rows"]:
                if row["kind"] == "financial" and row["field"] == "revenue":
                    scale = {"元": 1, "万元": 10000, "百万元": 1000000, "亿元": 100000000}[row["raw_unit"]]
                    row.update(current="1184000000", previous=base,
                        raw_current=str(Decimal("1184000000") / scale),
                        raw_previous=str(Decimal(base) / scale))
    return record(numeric_mutator=mutate)


def test_exact_growth_and_fixed_display_come_from_official_operands():
    source = growth_record()
    catalog = build_numeric_catalog(source)
    anchors = [a for a in catalog["anchors"] if a["definition_key"] == "official.revenue.growth"]
    assert anchors and all(Decimal(a["value"]) == Decimal("0.184") for a in anchors)
    assert all("18.40%" in render_numeric_anchor(a) and "H1" in render_numeric_anchor(a) for a in anchors)
    validate_numeric_catalog(source, catalog)


@pytest.mark.parametrize("base", ["0", "-1000000000"])
def test_nonpositive_base_cannot_supply_growth(base):
    assert not any(a["definition_key"] == "official.revenue.growth"
                   for a in build_numeric_catalog(growth_record(base=base))["anchors"])


def test_forecasts_keep_institution_future_year_and_nonactual_basis():
    catalog = build_numeric_catalog(record())
    forecasts = [a for a in catalog["anchors"] if a["basis"] == "institution_forecast"]
    assert forecasts and all("非已实现" in render_numeric_anchor(a) for a in forecasts)
    assert any("2026年预测" in render_numeric_anchor(a) for a in forecasts)


def test_projection_does_not_give_foundation_or_other_fact_permission():
    catalog = build_numeric_catalog(record())
    empty = project_numeric_catalog(catalog, [])
    assert not empty["anchors"]
    assert all(not m["required_fact_ids"] for m in empty["metadata"])


def test_anchor_or_unit_tamper_is_not_display_tolerance():
    source = record()
    catalog = build_numeric_catalog(source)
    for field, value in (("value", "999"), ("unit", "percent"), ("basis", "institution_forecast")):
        altered = deepcopy(catalog)
        altered["anchors"][0][field] = value
        with pytest.raises(ValueError):
            validate_numeric_catalog(source, altered)


def test_half_even_display_keeps_authoritative_value():
    anchor = next(a for a in build_numeric_catalog(record())["anchors"] if a["unit"] == "CNY")
    sample = {**anchor, "value": "123500000"}
    assert "1.24亿元" in render_numeric_anchor(sample)
    assert sample["value"] == "123500000"


def test_order_does_not_change_catalog_identity():
    # Check snapshots have their own ordered input hash. Isolate the catalog's
    # source-selector identity instead of pretending that hash is unordered.
    source = record().model_copy(update={"evidence_checks": None})
    reordered = source.model_copy(update={"claims": tuple(reversed(source.claims)),
                                         "evidence": tuple(reversed(source.evidence))})
    assert build_numeric_catalog(reordered) == build_numeric_catalog(source)


def test_catalog_overflow_is_unavailable_and_never_partial(monkeypatch):
    from tradingagents.research import numeric_catalog
    monkeypatch.setattr(numeric_catalog, "NUMERIC_CATALOG_LIMIT", 1)
    catalog = build_numeric_catalog(record())
    assert catalog["availability"] == "unavailable"
    assert catalog["reason_code"] == "numeric_catalog_limit"
    assert catalog["anchors"] == catalog["metadata"] == []


def test_missing_current_operand_never_becomes_zero():
    def missing(documents):
        for document in documents:
            for row in document["numeric_rows"]:
                if row["kind"] == "financial" and row["field"] == "revenue":
                    row.update(current=None, raw_current=None)
    catalog = build_numeric_catalog(record(numeric_mutator=missing))
    assert not any(a["definition_key"] in {"official.financial.revenue.current", "official.revenue.growth"}
                   for a in catalog["anchors"])
