"""Offline experiment costs never silently price unreported usage as zero."""

from decimal import Decimal

from scripts.summarize_v9_usage import summarize


def test_usage_summary_prices_measured_calls_and_reports_coverage():
    def attempt(logical, *, dispatched=True, outcome="ok", **usage):
        return {"logical_call_id": logical, "attempt_id": logical, "dispatched_at": dispatched,
                "outcome": outcome, **usage}

    provider = {"provider": "bailian", "model": "mock"}
    checkpoint = {
        "run_id": "fixture",
        "records": [
            attempt("insight.operating_quality.main", input_tokens=1000, output_tokens=100,
                    cached_tokens=400, cache_creation_tokens=100, reasoning_tokens=80),
            attempt("insight.event_context.main", outcome="failed", input_tokens=3000, output_tokens=200),
            attempt("insight.challenge.main", outcome="unknown"),
            attempt("insight.synthesis.main", input_tokens=100, output_tokens=10, cached_tokens=0),
            attempt("insight.focus_response.main", dispatched=False),
            attempt("insight.search.round.1"),
            attempt("insight.jev_verify.I1"),
            attempt("collection.stock.basic"),
        ],
        "insight.operating_quality.main.structured": provider,
        "insight.event_context.main.structured": provider,
        "insight.challenge.main.structured": provider,
        "insight.synthesis.main.structured": {"provider": "other", "model": "not priced"},
        "insight.model_usage": {"event_context.main": {
            "input_token_details": {"cache_read": 100}, "output_token_details": {"reasoning": 90},
        }},
    }
    rates = {"currency": "CNY", "models": {"bailian/mock": {
        "input": "2", "output": "8", "cache_read": "0.4", "cache_creation": "2.5",
    }}}
    result = summarize(checkpoint, rates)
    assert result["dispatched_insight_attempts"] == 4
    assert result["usage"]["reasoning_tokens"] == {"known_attempts": 2, "known_tokens": 170}
    assert result["cache_hit_rate"] == {
        "measured_attempts": 3, "input_tokens": 4100, "cached_tokens": 500, "share": 500 / 4100,
    }
    assert result["standard_price_reference"] == {"priced_attempts": 2, "known_subtotal": "0.0104"}
    assert result["cache_adjusted_estimate"]["priced_attempts"] == 1
    assert Decimal(result["cache_adjusted_estimate"]["known_subtotal"]) == Decimal("0.00221")
    assert result["attempts"][1]["cache_adjusted_estimate"] is None
    assert result["attempts"][2]["output_tokens"] is None
    assert result["attempts"][3]["standard_price_reference"] is None


def test_unknown_cache_is_not_reported_as_a_zero_hit_rate():
    result = summarize({"run_id": "empty", "records": []}, {"models": {}})
    assert result["cache_hit_rate"]["share"] is None
    assert result["cache_hit_rate"]["cached_tokens"] is None
    assert result["standard_price_reference"] == {"priced_attempts": 0, "known_subtotal": None}
