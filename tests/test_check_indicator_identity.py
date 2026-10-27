"""Repeated saved check keys must not mix distinct displayed observations."""

from tests.test_minimum_evidence import record
from tradingagents.research.report_explanation import explanation_targets, indicator_presentations


def test_repeated_operating_observations_keep_their_own_values_and_job_targets():
    saved = record()
    indicators = indicator_presentations(saved)
    check = next(c for c in saved.evidence_checks.checks if c.check_id == "operating_disclosures")
    expected = {
        "天然气总销售气量": ("20,467 百万立方米", "20,329 百万立方米"),
        "其中：平台交易气销售量": ("2,439 百万立方米", "2,689 百万立方米"),
        "天然气零售气销售量": ("13,054 百万立方米", "12,953 百万立方米"),
        "接收站接卸量": ("56.48 万吨", "113.67 万吨"),
    }
    for label, values in expected.items():
        seen = []
        for position, obs in enumerate(check.observations):
            if obs.label.endswith(label):
                item = indicators[f"check:{check.check_id}:observation:{position}"]
                assert item.value == values[0 if obs.key.endswith("current") else 1]
                assert item.label == obs.label
                seen.append(obs.key)
        assert sorted(seen) == ["operating_measure_current", "operating_measure_previous"]
    assert "check:operating_disclosures:operating_measure_current" not in indicators
    assert "check:operating_disclosures:operating_measure_previous" not in indicators

    # Before this change indicators used the old check keys. They are never
    # model explanation targets, so existing job target hashes must not change.
    legacy = {k: v for k, v in indicators.items() if not k.startswith("check:")}
    for c in saved.evidence_checks.checks:
        for o in c.observations:
            legacy[f"check:{c.check_id}:{o.key}"] = None
    assert explanation_targets(saved, indicators) == explanation_targets(saved, legacy)
    assert explanation_targets(saved, indicators, batched=True) == explanation_targets(saved, legacy, batched=True)
