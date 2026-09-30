"""T07 — research_profile validation and the independent catalyst evidence policy.

Every test here fails without its fix:

* before the fix ``RunCreateRequest`` has no ``research_profile`` field, so
  ``extra="forbid"`` rejects the field and every explicit-profile case errors;
* before the fix there is no ``catalyst-evidence-policy-v1`` module at all;
* before the fix the fingerprint document has no profile/policy component, so
  the resume-compatibility assertions cannot hold.

The catalog rejection cases additionally assert the hard constraint from the
brief: a request that cannot be honored must be *rejected*, never quietly
executed as ``classic``.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tradingagents.analysts import ANALYST_WIRE_KEYS
from tradingagents.execution.models import AnalysisRequest
from tradingagents.research.catalyst_evidence_policy import (
    CATALYST_EVIDENCE_POLICY_VERSION,
    CatalystEvidencePolicyV1,
    catalyst_evidence_policy_v1,
    normalize_research_profile,
)
from tradingagents.web.api import create_app
from tradingagents.web.broker import EventBroker
from tradingagents.web.store import RunStore

pytestmark = pytest.mark.unit


CATALYST_BODY = {
    "ticker": "600519.SS",
    "analysis_date": "2026-07-18",
    "asset_type": "stock",
    "research_depth": 1,
    "output_language": "Chinese",
    "llm_provider": "openai",
    "quick_think_llm": "gpt-5.4-mini",
    "deep_think_llm": "gpt-5.5",
    "checkpoint_enabled": False,
    "research_profile": "catalyst_v1",
}

CLASSIC_BODY = {
    **CATALYST_BODY,
    "ticker": "AAPL",
    "research_profile": "classic",
}


class _BudgetLedger:
    """Stand-in for the model/data budget ledger.

    The contract under test is that a rejected request never reaches the point
    where budget could be spent, so this records any charge attempt at all.
    """

    def __init__(self) -> None:
        self.charges: list[str] = []

    def charge(self, run_id: str, amount: int) -> None:
        self.charges.append(f"{run_id}:{amount}")

    def total(self) -> int:
        return len(self.charges)


class _RecordingManager:
    def __init__(self, store: RunStore, ledger: _BudgetLedger) -> None:
        self.store = store
        self.ledger = ledger
        self.requests: list[AnalysisRequest] = []

    def start(self, request: AnalysisRequest, *, configured_keys=None):
        from tradingagents.web.run_models import RunSnapshot

        self.requests.append(request)
        config = request.effective_config
        snapshot = RunSnapshot.create(
            ticker=request.ticker,
            analysis_date=request.analysis_date,
            asset_type=request.asset_type,
            selected_analysts=request.selected_analysts,
            max_debate_rounds=request.max_debate_rounds,
            max_risk_discuss_rounds=request.max_risk_discuss_rounds,
            output_language=str(config.get("output_language", "English")),
            llm_provider=str(config.get("llm_provider", "")),
            quick_think_llm=str(config.get("quick_think_llm", "")),
            deep_think_llm=str(config.get("deep_think_llm", "")),
            configured_keys=dict(configured_keys or {}),
            metadata={"effective_config": dict(config)},
        ).evolve(status="running")
        self.store.create_run(snapshot)
        # Budget is only ever touched after a run actually exists.
        self.ledger.charge(snapshot.run_id, 1)
        return snapshot

    def list_batches(self):
        return tuple(self.store.list_batches())


@pytest.fixture
def catalyst_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the creation flag on for this test only.

    The flag defaults to off in code configuration.  The environment override
    is the supported way to exercise the enabled path without mutating the
    shared DEFAULT_CONFIG for the rest of the suite.
    """
    monkeypatch.setenv("TRADINGAGENTS_CATALYST_PROFILE_ENABLED", "1")


@pytest.fixture
def client_factory(tmp_path: Path):
    created: list[tuple[TestClient, RunStore, _RecordingManager, _BudgetLedger]] = []

    def build(*, environment: dict[str, str] | None = None) -> tuple:
        store = RunStore(tmp_path / "runs")
        ledger = _BudgetLedger()
        manager = _RecordingManager(store, ledger)
        app = create_app(
            store=store,
            manager=manager,
            broker=EventBroker(store),
            connectivity_check=lambda _ticker: None,
            environment=environment or {"OPENAI_API_KEY": "unit-test-placeholder"},
        )
        bundle = (TestClient(app), store, manager, ledger)
        created.append(bundle)
        return bundle

    return build


# ---------------------------------------------------------------------------
# Policy module (independent of the horizon runtime contract)
# ---------------------------------------------------------------------------


def test_catalyst_policy_version_is_independent_of_the_horizon_runtime_enum():
    """The new policy must not ride the horizon gating enum.

    ``RuntimePolicyVersion`` is consumed by five modules and selecting
    ``horizon-policy-v3`` turns on an already-active test gate.  The catalyst
    policy therefore has its own module and its own field.
    """
    import typing

    from tradingagents.runtime.contracts import RuntimePolicyVersion

    allowed = set(typing.get_args(RuntimePolicyVersion))
    assert CATALYST_EVIDENCE_POLICY_VERSION not in allowed
    assert allowed == {"horizon-policy-v2", "horizon-policy-v3"}

    policy = catalyst_evidence_policy_v1()
    assert policy.policy_version == "catalyst-evidence-policy-v1"
    assert policy.profile == "catalyst_v1"
    # The forward-looking product window is 84 calendar days (~one quarter).
    assert policy.forward_window_max_calendar_days == 84
    # Retrieval and budget ceilings are part of the frozen policy identity.
    assert policy.max_source_calls > 0
    assert policy.max_model_calls > 0
    assert policy.max_supplement_rounds == 1
    assert policy.max_supplement_capabilities == 3


def test_catalyst_policy_identity_changes_only_with_real_parameter_changes():
    base = catalyst_evidence_policy_v1().as_identity()
    assert base == CatalystEvidencePolicyV1().as_identity()

    tightened = CatalystEvidencePolicyV1(max_model_calls=12).as_identity()
    assert tightened["max_model_calls"] == 12
    assert tightened["policy_version"] == base["policy_version"]
    # Distinct policy parameter sets must not share an identity.
    assert tightened != base


def test_catalyst_policy_rejects_unknown_parameters():
    with pytest.raises(ValueError):
        CatalystEvidencePolicyV1(unknown_window=3)


# ---------------------------------------------------------------------------
# Backward compatibility: omission == classic
# ---------------------------------------------------------------------------


def test_omitted_research_profile_behaves_as_classic(client_factory):
    body = {key: value for key, value in CLASSIC_BODY.items() if key != "research_profile"}
    client, store, manager, ledger = client_factory()

    response = client.post("/api/runs", json=body)

    assert response.status_code == 201, response.text
    assert len(manager.requests) == 1
    request = manager.requests[0]
    assert request.research_profile == "classic"
    assert request.catalyst_policy is None
    assert request.policy_version == "horizon-policy-v2"
    # No budget is spent on the request-validation path itself; one charge comes
    # from the single accepted run.
    assert ledger.total() == 1


def test_explicit_classic_profile_is_unchanged(client_factory):
    client, _store, manager, _ledger = client_factory()

    response = client.post("/api/runs", json=CLASSIC_BODY)

    assert response.status_code == 201, response.text
    assert manager.requests[0].research_profile == "classic"
    assert manager.requests[0].catalyst_policy is None


def test_legacy_request_shape_with_selected_analysts_still_passes(client_factory):
    """A pre-existing client that still sends selected_analysts is unaffected."""
    body = {
        **CLASSIC_BODY,
        "selected_analysts": ["market", "fundamentals"],
        "research_depth": 3,
    }
    client, _store, manager, _ledger = client_factory()

    response = client.post("/api/runs", json=body)

    assert response.status_code == 201, response.text
    assert manager.requests[0].research_profile == "classic"
    assert manager.requests[0].selected_analysts == ("market", "fundamentals")


# ---------------------------------------------------------------------------
# catalyst_v1 catalog: reject, never silently downgrade
# ---------------------------------------------------------------------------


def test_catalyst_v1_company_research_a_share_is_accepted(client_factory, catalyst_enabled):
    client, _store, manager, _ledger = client_factory()

    response = client.post("/api/runs", json=CATALYST_BODY)

    assert response.status_code == 201, response.text
    request = manager.requests[0]
    assert request.research_profile == "catalyst_v1"
    assert request.catalyst_policy is not None
    assert request.policy_version == CATALYST_EVIDENCE_POLICY_VERSION


def test_catalyst_v1_is_rejected_when_the_feature_flag_is_off(client_factory):
    """Default-off is a hard gate, not a silent fallback to classic."""
    client, store, manager, ledger = client_factory()

    response = client.post("/api/runs", json=CATALYST_BODY)

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "catalyst_profile_unavailable"
    assert "classic" in detail["message"]
    # Not enqueued, not charged.
    assert manager.requests == []
    assert store.list_runs() == []
    assert ledger.total() == 0


def test_catalyst_v1_with_holding_review_is_rejected_not_downgraded(
    client_factory, catalyst_enabled
):
    body = {
        **CATALYST_BODY,
        "mode": "holding_review",
        "holding": {
            "ticker": "600519.SS",
            "quantity": 100,
            "average_cost": 1500.0,
            "cash": 10000.0,
            "total_account_value": 200000.0,
            "currency": "CNY",
            "facts_as_of": "2026-07-18",
        },
    }
    client, store, manager, ledger = client_factory()

    response = client.post("/api/runs", json=body)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "catalyst_mode_unsupported"
    assert "holding review" in detail["message"]
    assert "research_profile" in detail["fields"]
    # The rejection is real: nothing ran as classic either.
    assert manager.requests == []
    assert store.list_runs() == []
    assert ledger.total() == 0


def test_catalyst_v1_with_non_a_share_ticker_is_rejected(client_factory, catalyst_enabled):
    body = {**CATALYST_BODY, "ticker": "AAPL", "asset_type": "stock"}
    client, store, manager, ledger = client_factory()

    response = client.post("/api/runs", json=body)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "catalyst_market_unsupported"
    assert "A-share" in detail["message"]
    assert manager.requests == []
    assert store.list_runs() == []
    assert ledger.total() == 0


def test_catalyst_v1_with_crypto_is_rejected(client_factory, catalyst_enabled):
    body = {**CATALYST_BODY, "ticker": "BTC-USD", "asset_type": "crypto"}
    client, store, manager, ledger = client_factory()

    response = client.post("/api/runs", json=body)

    assert response.status_code == 422
    # The pre-existing schema rule for crypto + the default analyst tuple
    # (which includes fundamentals) rejects first.  What matters for T07 is
    # that the request is refused and never executed as classic.
    assert response.json()["detail"]["code"] == "validation_error"
    assert manager.requests == []
    assert store.list_runs() == []
    assert ledger.total() == 0


def test_catalyst_v1_with_crypto_and_no_fundamentals_analyst_is_rejected(
    client_factory, catalyst_enabled
):
    """The market gate is what rejects crypto, not the classic analyst rule."""
    body = {
        **CATALYST_BODY,
        "ticker": "BTC-USD",
        "asset_type": "crypto",
        "selected_analysts": ["market"],
    }
    client, store, manager, ledger = client_factory()

    response = client.post("/api/runs", json=body)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "catalyst_market_unsupported"
    assert manager.requests == []
    assert store.list_runs() == []
    assert ledger.total() == 0


def test_catalyst_v1_with_non_default_scheduling_params_is_rejected(
    client_factory, catalyst_enabled
):
    body = {**CATALYST_BODY, "research_depth": 3}
    client, store, manager, ledger = client_factory()

    response = client.post("/api/runs", json=body)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "catalyst_legacy_scheduling_params_not_applicable"
    assert "research_depth" in detail["fields"]
    assert manager.requests == []
    assert store.list_runs() == []
    assert ledger.total() == 0


def test_catalyst_v1_with_explicit_analyst_selection_is_rejected(
    client_factory, catalyst_enabled
):
    body = {**CATALYST_BODY, "selected_analysts": ["market"]}
    client, store, manager, ledger = client_factory()

    response = client.post("/api/runs", json=body)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "catalyst_legacy_scheduling_params_not_applicable"
    assert manager.requests == []
    assert store.list_runs() == []
    assert ledger.total() == 0


def test_catalyst_v1_with_non_medium_horizon_is_rejected(client_factory, catalyst_enabled):
    body = {**CATALYST_BODY, "horizon": "long"}
    client, store, manager, ledger = client_factory()

    response = client.post("/api/runs", json=body)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "catalyst_horizon_not_supported"
    assert "horizon" in detail["fields"]
    assert manager.requests == []
    assert store.list_runs() == []
    assert ledger.total() == 0


def test_catalyst_v1_accepts_the_explicit_default_analyst_tuple(
    client_factory, catalyst_enabled
):
    """Sending the same default value explicitly is still the default."""
    body = {**CATALYST_BODY, "selected_analysts": list(ANALYST_WIRE_KEYS)}
    client, _store, manager, _ledger = client_factory()

    response = client.post("/api/runs", json=body)

    assert response.status_code == 201, response.text


def test_unknown_research_profile_value_is_rejected(client_factory):
    body = {**CATALYST_BODY, "research_profile": "catalyst_v2"}
    client, store, manager, ledger = client_factory()

    response = client.post("/api/runs", json=body)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"
    assert manager.requests == []
    assert store.list_runs() == []
    assert ledger.total() == 0


# ---------------------------------------------------------------------------
# Shared request model
# ---------------------------------------------------------------------------


def test_shared_request_defaults_to_classic_and_rejects_a_policy_bundle():
    classic = AnalysisRequest(ticker="AAPL", analysis_date="2026-07-18")
    assert classic.research_profile == "classic"
    assert classic.catalyst_policy is None
    # classic emits no profile component at all, so every pre-existing
    # fingerprint byte is reproduced exactly.
    assert classic.profile_identity() == {}

    catalyst = AnalysisRequest(
        ticker="600519.SS", analysis_date="2026-07-18", research_profile="catalyst_v1"
    )
    assert catalyst.catalyst_policy is not None
    assert catalyst.profile_identity()["evidence_policy_version"] == (
        CATALYST_EVIDENCE_POLICY_VERSION
    )

    with pytest.raises(ValueError, match="classic research profile"):
        AnalysisRequest(
            ticker="AAPL",
            analysis_date="2026-07-18",
            catalyst_policy=catalyst_evidence_policy_v1(),
        )


def test_profile_identity_is_json_serializable_and_stable():
    identity = AnalysisRequest(
        ticker="600519.SS", analysis_date="2026-07-18", research_profile="catalyst_v1"
    ).profile_identity()
    assert json.loads(json.dumps(identity)) == identity
    assert identity["catalyst_policy"]["forward_window_max_calendar_days"] == 84


def test_normalize_research_profile_treats_omission_and_blank_as_classic():
    assert normalize_research_profile(None) == "classic"
    assert normalize_research_profile("") == "classic"
    assert normalize_research_profile("  classic  ") == "classic"
    assert normalize_research_profile("catalyst_v1") == "catalyst_v1"
    with pytest.raises(ValueError):
        normalize_research_profile("catalyst")

def test_analysis_request_annotations_stay_resolvable():
    """``typing.get_type_hints(AnalysisRequest)`` must not raise.

    A catalog web consumer resolves the request's Literal fields through
    get_type_hints (tests/test_frontend_wire_contract.py).  If any annotation
    named a class that is not importable at runtime from this module, that
    consumer would die with NameError on the first request.
    """
    hints = typing.get_type_hints(AnalysisRequest)
    assert set(typing.get_args(hints["research_profile"])) == {"classic", "catalyst_v1"}


def test_catalyst_policy_field_is_a_real_policy_object_not_a_lookalike():
    """The field is annotated structurally, so the class is enforced at runtime."""
    request = AnalysisRequest(
        ticker="600519.SS", analysis_date="2026-07-18", research_profile="catalyst_v1"
    )
    assert isinstance(request.catalyst_policy, CatalystEvidencePolicyV1)
    assert request.catalyst_policy.profile == "catalyst_v1"
    with pytest.raises(ValueError, match="CatalystEvidencePolicyV1"):
        AnalysisRequest(
            ticker="600519.SS",
            analysis_date="2026-07-18",
            research_profile="catalyst_v1",
            catalyst_policy={"policy_version": "catalyst-evidence-policy-v1"},
        )
