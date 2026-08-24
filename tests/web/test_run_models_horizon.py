"""Investment horizon persistence and legacy snapshot compatibility."""

from tradingagents.web.run_models import RunSnapshot


def test_new_snapshot_persists_explicit_horizon():
    snapshot = RunSnapshot.create(
        ticker="000338.SZ",
        analysis_date="2026-07-31",
        horizon="long",
    )

    assert snapshot.horizon == "long"
    assert snapshot.as_dict()["horizon"] == "long"


def test_legacy_snapshot_without_horizon_deserializes_for_medium_fallback():
    payload = RunSnapshot.create(
        ticker="AAPL",
        analysis_date="2026-07-31",
    ).as_dict()
    payload.pop("horizon")

    snapshot = RunSnapshot.from_dict(payload)

    assert snapshot.horizon is None
