"""Static ownership map closing horizon policy capabilities to durable consumers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityPipelineV1:
    producer: str
    state_key: str
    registry_projection: str
    eligibility_consumer: str
    typed_result: bool


CAPABILITY_PIPELINES: dict[str, CapabilityPipelineV1] = {
    capability: CapabilityPipelineV1(
        producer=producer,
        state_key=state_key,
        registry_projection="EvidenceRegistry.capability_results_by_capability",
        eligibility_consumer="assess_decision_eligibility",
        typed_result=True,
    )
    for capability, producer, state_key in (
        (
            "verified_identity",
            "analysis_cutoff + adjusted price prefetch",
            "adjusted_price_bundle",
        ),
        (
            "verified_market_snapshot",
            "adjusted price prefetch",
            "adjusted_price_bundle",
        ),
        (
            "adjusted_price_history",
            "adjusted price prefetch",
            "adjusted_price_bundle",
        ),
        ("company_event_window", "news window prefetch", "news_window_bundle"),
        ("official_disclosures", "news window prefetch", "news_window_bundle"),
        (
            "fundamentals_quarterly",
            "fundamentals prefetch",
            "fundamentals_prefetch_bundle",
        ),
        (
            "fundamentals_annual",
            "fundamentals prefetch",
            "fundamentals_prefetch_bundle",
        ),
    )
}
