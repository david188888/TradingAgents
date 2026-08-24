from datetime import date, datetime, timezone

import pytest

from tradingagents.research.logic_loop import evaluate_logic_edge
from tradingagents.research.metric_catalog import metric_definition
from tradingagents.research.metric_engine import calculate_metric, calculate_yoy
from tradingagents.research.metric_models import MetricObservationV1
from tradingagents.research.peer_set import PeerCandidateV1, build_peer_set, compare_metric
from tradingagents.research.research_package import ResearchEvidenceRefV1, ResearchPackageV1

AS_OF = date(2026, 8, 15)


def observation(
    observation_id: str,
    metric_id: str,
    entity_id: str,
    value: float,
    *,
    unit: str = "CNY",
    period: str = "2026Q2",
    evidence: tuple[str, ...] = ("e1",),
) -> MetricObservationV1:
    return MetricObservationV1(
        observation_id=observation_id,
        run_id="run1",
        metric_id=metric_id,
        entity_id=entity_id,
        period=period,
        as_of=AS_OF,
        frequency="quarterly",
        value=value,
        unit=unit,
        source_evidence_ref_ids=evidence,
    )


def test_catalog_and_yoy_are_explainable_and_deterministic() -> None:
    definition = metric_definition("revenue_yoy")
    result = calculate_yoy(
        "revenue_yoy",
        observation("current", "revenue", "600000.SH", 120, period="2026Q2"),
        observation("prior", "revenue", "600000.SH", 100, period="2025Q2"),
    )

    assert definition.formula_text
    assert definition.plain_explanation
    assert result.status == "available"
    assert result.output_observation.value == pytest.approx(0.2)
    assert result.input_observation_ids == ("current", "prior")


def test_negative_earnings_make_pe_unavailable() -> None:
    result = calculate_metric(
        "pe",
        {
            "equity_value": observation("market", "equity_value", "600000.SH", 1000),
            "net_income": observation("loss", "net_income", "600000.SH", -10),
        },
    )

    assert result.status == "unavailable"
    assert result.output_observation.unavailable_reason == "non_positive_denominator"


def test_peer_set_is_stable_and_comparison_requires_same_period() -> None:
    candidates = [
        PeerCandidateV1(
            entity_id="target",
            industry_code="A",
            market_cap=100,
            as_of=AS_OF,
            source_evidence_ref_ids=("e1",),
        ),
        PeerCandidateV1(
            entity_id="peer_b",
            industry_code="A",
            market_cap=120,
            business_similarity=0.9,
            as_of=AS_OF,
            source_evidence_ref_ids=("e2",),
        ),
        PeerCandidateV1(
            entity_id="peer_a",
            industry_code="A",
            market_cap=80,
            business_similarity=0.8,
            as_of=AS_OF,
            source_evidence_ref_ids=("e3",),
        ),
    ]
    peers = build_peer_set("target", candidates, run_id="run1", as_of=AS_OF)
    comparison = compare_metric(
        peers,
        observation("target-revenue", "revenue", "target", 120),
        [
            observation("b-revenue", "revenue", "peer_b", 100),
            observation("a-revenue", "revenue", "peer_a", 80),
        ],
    )

    assert peers.member_entity_ids == ("peer_b", "peer_a")
    assert comparison.peer_median == 90
    assert comparison.target_percentile == 100


def test_logic_edge_blocks_missing_evidence() -> None:
    item = observation("growth", "revenue_yoy", "target", 0.2, unit="%")
    edge = evaluate_logic_edge(
        edge_id="growth-to-profit",
        run_id="run1",
        from_node="revenue",
        to_node="profit",
        input_observation_ids=(item.observation_id,),
        observations={item.observation_id: item},
        evidence_ref_ids=("e1",),
        next_validation="check next filing",
        invalidation="growth reverses",
    )

    assert edge.status == "blocked"
    assert "unavailable_evidence:e1" in edge.missing_evidence


def test_package_rejects_cross_run_evidence() -> None:
    item = observation("margin", "net_margin", "600000.SH", 0.2)
    with pytest.raises(ValueError, match="current run"):
        ResearchPackageV1(
            package_id="pkg1",
            run_id="run1",
            ticker="600000.SH",
            analysis_cutoff=AS_OF,
            created_at=datetime.now(timezone.utc),
            evidence_refs=(ResearchEvidenceRefV1(ref_id="e1", run_id="run2", source_label="x"),),
            metric_definitions=(metric_definition("net_margin"),),
            observations=(item,),
        )


def test_package_rejects_cross_entity_and_non_finite_observations():
    for item in (
        observation("other", "net_margin", "peer", 0.2),
        observation("infinite", "net_margin", "600000.SH", float("inf")),
    ):
        with pytest.raises(ValueError):
            ResearchPackageV1(
                package_id="pkg1",
                run_id="run1",
                ticker="600000.SH",
                target_entity_id="600000.SH",
                analysis_cutoff=AS_OF,
                created_at=datetime.now(timezone.utc),
                evidence_refs=(ResearchEvidenceRefV1(ref_id="e1", run_id="run1", source_label="x"),),
                metric_definitions=(metric_definition("net_margin"),),
                observations=(item,),
            )


def test_metric_engine_rejects_wrong_metric_and_entity_inputs() -> None:
    with pytest.raises(ValueError, match="do not match"):
        calculate_metric(
            "gross_margin",
            {
                "gross_profit": observation("wrong", "revenue", "target", 100),
                "revenue": observation("revenue", "revenue", "peer", 1000),
            },
        )


def test_package_rejects_unvalidated_point_in_time_observation() -> None:
    with pytest.raises(ValueError, match="point-in-time"):
        ResearchPackageV1(
            package_id="pkg1",
            run_id="run1",
            ticker="600000.SH",
            analysis_cutoff=AS_OF,
            created_at=datetime.now(timezone.utc),
            metric_definitions=(metric_definition("net_margin"),),
            observations=(observation("margin", "net_margin", "600000.SH", 0.2).model_copy(update={"point_in_time": False}),),
        )
