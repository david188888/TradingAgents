from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.runner import (
    AnalysisRunner,
    CheckpointAuthorization,
    PreparedInitialContext,
    RuntimePreparationInputs,
    prepare_v3_research_scaffold,
)
from tradingagents.observability.canonical import (
    BUSINESS_PROJECTION_VERSION,
    SERIALIZER_VERSION,
    UnsupportedCanonicalValue,
    agent_state_schema_for,
    business_delta_sha256,
    canonical_json_bytes,
    project_business_delta,
)
from tradingagents.observability.events import ObservationCommitV1
from tradingagents.research.analysis_cutoff import (
    InstrumentIdentityPreflightV1,
    resolve_bounded_analysis_cutoff,
)
from tradingagents.runtime.contracts import RuntimeContractSelection
from tradingagents.runtime.fingerprint import (
    FingerprintCheckpointGuard,
    FingerprintError,
    _build_resume_fingerprint_for_test,
    compare_resume_fingerprints,
)
from tradingagents.runtime.reconciliation import (
    CheckpointObservationIncompatible,
    _parse_commit,
)
from tradingagents.runtime.run_models import RunSnapshot, generate_run_id
from tradingagents.runtime.store import RunStore
from tradingagents.web.manager import (
    RunNotResumable,
    _default_resume_preflight,
    _runtime_policy_from_snapshot,
)

V2_POLICY = "horizon-policy-v2"
V3_POLICY = "horizon-policy-v3"
V2_SCHEMA_SHA256 = (
    "0aa01f8a0cca522554920bec7f212e120ba3d1a70032a17ab9f89da1b2b8b6b2"
)
V2_APPLICATION_FIELDS = (
    "a_share_supplement_bundle",
    "adjusted_price_bundle",
    "allowed_actions",
    "analysis_cutoff",
    "asset_type",
    "canonical_company_profile",
    "clamp_events",
    "company_of_interest",
    "context_compaction_facts",
    "evidence_gate_fault",
    "evidence_ledger",
    "evidence_ledger_artifact_id",
    "evidence_report",
    "evidence_status",
    "execution_outcome",
    "feature_contributions",
    "final_trade_decision",
    "fundamentals_prefetch_bundle",
    "fundamentals_report",
    "holding_context",
    "holding_review_summary",
    "horizon",
    "instrument_context",
    "investment_debate_state",
    "investment_plan",
    "market_report",
    "messages",
    "methodology_reports",
    "mode",
    "news_report",
    "news_window_bundle",
    "past_context",
    "portfolio_context",
    "reader_public_output",
    "research_case_candidate",
    "research_dossier",
    "risk_debate_state",
    "sender",
    "sentiment_report",
    "trade_date",
    "trader_investment_plan",
)


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        ticker="AAPL",
        analysis_date="2026-07-15",
        selected_analysts=("market",),
    )


def _global_preflight() -> InstrumentIdentityPreflightV1:
    return InstrumentIdentityPreflightV1(
        ticker="AAPL",
        market="global",
        candidate_exchange="NMS",
        candidate_timezone="America/New_York",
        regulatory_scope_candidate="us_sec_candidate",
        source_id="fixture.identity",
        derivation="explicit_fixture",
    )


def test_production_v2_descriptor_and_delta_are_frozen() -> None:
    schema = agent_state_schema_for(V2_POLICY)
    delta = {"market_report": "report"}

    assert schema.application_fields == V2_APPLICATION_FIELDS
    assert schema.sha256 == V2_SCHEMA_SHA256
    assert project_business_delta(delta) == delta
    assert canonical_json_bytes(project_business_delta(delta)) == (
        b'{"market_report":"report"}'
    )
    assert business_delta_sha256(delta) == (
        "a2b1dc75075295b18d3cb18bc8d7be3fcf400636708100334be90ec5156c2b37"
    )


def _frozen_fingerprint(
    *,
    runtime_contract: RuntimeContractSelection | None = None,
    research_preflight: dict | None = None,
):
    request = AnalysisRequest(
        ticker=" aapl ",
        analysis_date="2026-07-18",
        selected_analysts=("news", "market"),
        max_debate_rounds=2,
        max_risk_discuss_rounds=3,
        horizon="medium",
        effective_config={
            "llm_provider": "openai",
            "quick_think_llm": "gpt-4.1-mini",
            "max_tokens": 2048,
            "backend_url": "https://api.example.com/v1?trace=discarded",
        },
    )
    initial_context = {
        "past_context": "No prior decision memory.",
        "company_of_interest": "AAPL",
        "asset_type": "stock",
        "instrument_context": {"symbol": "AAPL", "exchange": "NASDAQ"},
    }
    if research_preflight is not None:
        initial_context["research_preflight"] = research_preflight
    return _build_resume_fingerprint_for_test(
        request,
        effective_config=request.effective_config,
        initial_context=initial_context,
        runtime_semantics_hash="a" * 64,
        runtime_python={
            "implementation": "cpython",
            "version": "3.12.5",
            "cache_tag": "cpython-312",
            "abi_flags": "",
            "platform": "macosx-14.0-arm64",
        },
        runtime_distributions=[
            {
                "name": "langgraph",
                "version": "1.1.10",
                "record_sha256": "b" * 64,
                "direct_url_sha256": None,
            }
        ],
        runtime_contract=runtime_contract or RuntimeContractSelection.production_v2(),
    )


def test_production_v2_fingerprint_bytes_are_frozen() -> None:
    fingerprint = _frozen_fingerprint()

    assert fingerprint.document["initial_context_hash"] == (
        "6f2d09c59f6d60c896d96625065c7c691a41f66a5ef883a7c47a4c43e9c8ad69"
    )
    assert "runtime_contract" not in fingerprint.document
    assert fingerprint.sha256 == (
        "d45fca186bf32816f7dd2d2d12fe9b7bed014af97ab0e520fe003f5f3830af68"
    )


def test_v3_scaffold_semantics_participate_in_fingerprint() -> None:
    request = AnalysisRequest(ticker="AAPL", analysis_date="2026-07-18")
    first_scaffold = prepare_v3_research_scaffold(
        request,
        captured_at=datetime(2026, 7, 18, 15, 30, tzinfo=timezone.utc),
        identity_preflight=_global_preflight(),
    ).model_dump(mode="json")
    changed_scaffold = prepare_v3_research_scaffold(
        request,
        captured_at=datetime(2026, 7, 18, 15, 31, tzinfo=timezone.utc),
        identity_preflight=_global_preflight(),
    ).model_dump(mode="json")
    first = _frozen_fingerprint(
        runtime_contract=RuntimeContractSelection.v3_test(),
        research_preflight=first_scaffold,
    )
    changed = _frozen_fingerprint(
        runtime_contract=RuntimeContractSelection.v3_test(),
        research_preflight=changed_scaffold,
    )

    comparison = compare_resume_fingerprints(first, changed)
    assert comparison.compatible is False
    assert comparison.mismatch_categories == ("initial_context_hash",)


def test_v3_fingerprint_rejects_half_typed_scaffold() -> None:
    with pytest.raises(FingerprintError, match="valid v3 research_preflight"):
        _frozen_fingerprint(
            runtime_contract=RuntimeContractSelection.v3_test(),
            research_preflight={"analysis_cutoff": "untyped"},
        )


def test_checkpoint_authorization_is_bound_to_prepared_context() -> None:
    context = PreparedInitialContext(
        {
            "past_context": "frozen",
            "company_of_interest": "AAPL",
            "asset_type": "stock",
            "instrument_context": {"exchange": "NASDAQ"},
        }
    )
    authorization = CheckpointAuthorization._issue(
        run_id="run-1",
        fingerprint_sha256="a" * 64,
        mode="fresh",
        runtime_policy_version=V2_POLICY,
        agent_state_schema_sha256=V2_SCHEMA_SHA256,
        prepared_context_sha256="b" * 64,
        checkpoint_id=None,
    )

    with pytest.raises(RuntimeError, match="prepared context"):
        AnalysisRunner(SimpleNamespace())._validate_checkpoint_authorization(
            authorization,
            SimpleNamespace(latest=None),
            "run-1",
            context,
        )


def test_frozen_v2_resume_authorization_is_read_only(tmp_path, monkeypatch) -> None:
    run_id = generate_run_id()
    store = RunStore(tmp_path)
    store.create_run(
        RunSnapshot.create(
            run_id=run_id,
            ticker="AAPL",
            analysis_date="2026-07-18",
            selected_analysts=("news", "market"),
            llm_provider="openai",
            quick_think_llm="gpt-4.1-mini",
            deep_think_llm="gpt-4.1",
        )
    )
    fingerprint = _frozen_fingerprint()
    monkeypatch.setattr(
        "tradingagents.runtime.fingerprint.build_resume_fingerprint",
        lambda *_args, **_kwargs: fingerprint,
    )
    request = AnalysisRequest(
        ticker="AAPL",
        analysis_date="2026-07-18",
        selected_analysts=("news", "market"),
        max_debate_rounds=2,
        max_risk_discuss_rounds=3,
        horizon="medium",
        effective_config={
            "llm_provider": "openai",
            "quick_think_llm": "gpt-4.1-mini",
            "max_tokens": 2048,
            "backend_url": "https://api.example.com/v1?trace=discarded",
        },
    )
    context = PreparedInitialContext(
        {
            "past_context": "No prior decision memory.",
            "company_of_interest": "AAPL",
            "asset_type": "stock",
            "instrument_context": {"symbol": "AAPL", "exchange": "NASDAQ"},
        }
    )
    guard = FingerprintCheckpointGuard(
        store,
        run_id,
        request,
        request.effective_config,
    )
    guard(context, SimpleNamespace(latest=None))
    run_dir = tmp_path / run_id
    before = {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    access = SimpleNamespace(
        latest=SimpleNamespace(
            config={"configurable": {"checkpoint_id": "checkpoint-1"}},
            checkpoint={"id": "checkpoint-1"},
        )
    )

    authorization = guard(context, access)

    after = {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    assert authorization.mode == "resume"
    assert authorization.checkpoint_id == "checkpoint-1"
    assert after == before


def test_startup_reconciliation_policy_is_durable_and_fail_closed() -> None:
    legacy = RunSnapshot.create(
        ticker="AAPL",
        analysis_date="2026-07-18",
    )
    v3 = replace(
        legacy,
        resume_fingerprint={
            "document": {
                "runtime_contract": {"policy_version": V3_POLICY},
            }
        },
    )
    unknown = replace(
        legacy,
        resume_fingerprint={
            "document": {
                "runtime_contract": {"policy_version": "horizon-policy-v99"},
            }
        },
    )

    assert _runtime_policy_from_snapshot(legacy) == V2_POLICY
    assert _runtime_policy_from_snapshot(v3) == V3_POLICY
    with pytest.raises(RunNotResumable, match="runtime contract fingerprint"):
        _runtime_policy_from_snapshot(unknown)


def test_v3_web_resume_preflight_never_reads_pending_memory(
    tmp_path,
    monkeypatch,
) -> None:
    config = {
        "checkpoint_enabled": True,
        "data_cache_dir": str(tmp_path / "cache"),
    }
    request = AnalysisRequest(
        ticker="AAPL",
        analysis_date="2026-07-18",
        effective_config=config,
    )
    snapshot = RunSnapshot.create(
        ticker="AAPL",
        analysis_date="2026-07-18",
    )
    store = RunStore(tmp_path / "runs")
    store.create_run(snapshot)
    forbidden_pending = Mock(
        side_effect=AssertionError("v3 resume must not resolve pending entries")
    )
    owner = SimpleNamespace(
        config=config,
        ticker=None,
        _resolve_pending_entries=forbidden_pending,
        _run_signature=lambda *_args: "v3-test",
    )
    runtime_inputs = RuntimePreparationInputs(
        captured_at=datetime(2026, 7, 18, 15, 30, tzinfo=timezone.utc),
        identity_preflight=_global_preflight(),
        past_context="frozen",
        instrument_context={"exchange": "NMS"},
    )
    runner = AnalysisRunner(owner, runtime_preparation=runtime_inputs)
    expected_context = runner.prepare_initial_context(request)
    authorized_contexts = []
    guard = SimpleNamespace(
        preauthorize=lambda context, _access: (
            authorized_contexts.append(context)
            or SimpleNamespace(mode="resume")
        )
    )
    access = SimpleNamespace(latest=object(), parent=None)
    monkeypatch.setattr(
        "tradingagents.execution.runner.checkpoint_access",
        lambda *_args, **_kwargs: access,
    )
    reconciliation_policies = []
    monkeypatch.setattr(
        "tradingagents.web.reconciliation.reconcile_checkpoint_frontier",
        lambda *_args, **kwargs: (
            reconciliation_policies.append(kwargs["policy_version"])
            or SimpleNamespace(
                missing_checkpoint_transition=None,
                abandoned_task_ids=(),
            )
        ),
    )
    run_dir = store.root / snapshot.run_id
    before = {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }

    result = _default_resume_preflight(
        store,
        snapshot,
        request,
        lambda *_args: runner,
        lambda *_args: guard,
    )
    after = {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }

    assert result is guard
    assert authorized_contexts == [expected_context]
    assert reconciliation_policies == [V3_POLICY]
    assert after == before
    forbidden_pending.assert_not_called()


def test_scaffold_delta_is_v3_only() -> None:
    delta = {"research_preflight": {"contract_kind": "fixture"}}

    with pytest.raises(UnsupportedCanonicalValue, match="research_preflight"):
        project_business_delta(delta, policy_version=V2_POLICY)

    assert project_business_delta(delta, policy_version=V3_POLICY) == delta
    assert agent_state_schema_for(V3_POLICY).sha256 != V2_SCHEMA_SHA256


def test_v3_cutoff_is_clock_bounded_and_future_dates_fail_closed() -> None:
    preflight = _global_preflight()
    captured_at = datetime(2026, 7, 15, 15, 30, tzinfo=timezone.utc)

    intraday = resolve_bounded_analysis_cutoff(
        "AAPL",
        "2026-07-15",
        captured_at=captured_at,
        identity=preflight,
    )
    future = resolve_bounded_analysis_cutoff(
        "AAPL",
        "2026-07-16",
        captured_at=captured_at,
        identity=preflight,
    )

    assert intraday.analysis_cutoff_at == captured_at
    assert future.status == "invalid"
    assert future.analysis_cutoff_at is None
    assert future.reason_code == "analysis_cutoff_resolution_failed"


@pytest.mark.parametrize(
    ("ticker", "analysis_date", "captured_at", "identity", "expected"),
    (
        (
            "600519.SH",
            "2026-07-15",
            datetime(2026, 7, 15, 0, 30, tzinfo=timezone.utc),
            None,
            datetime(2026, 7, 15, 0, 30, tzinfo=timezone.utc),
        ),
        (
            "600519.SH",
            "2026-07-15",
            datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc),
            None,
            datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc),
        ),
        (
            "600519.SH",
            "2026-07-15",
            datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc),
            None,
            datetime(2026, 7, 15, 15, 59, 59, 999999, tzinfo=timezone.utc),
        ),
        (
            "AAPL",
            "2026-07-15",
            datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc),
            _global_preflight(),
            datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc),
        ),
        (
            "AAPL",
            "2026-07-15",
            datetime(2026, 7, 15, 15, 30, tzinfo=timezone.utc),
            _global_preflight(),
            datetime(2026, 7, 15, 15, 30, tzinfo=timezone.utc),
        ),
        (
            "AAPL",
            "2026-07-15",
            datetime(2026, 7, 16, 4, 0, tzinfo=timezone.utc),
            _global_preflight(),
            datetime(2026, 7, 16, 3, 59, 59, 999999, tzinfo=timezone.utc),
        ),
    ),
)
def test_v3_cutoff_matrix_is_market_local_and_clock_bounded(
    ticker: str,
    analysis_date: str,
    captured_at: datetime,
    identity: InstrumentIdentityPreflightV1 | None,
    expected: datetime,
) -> None:
    result = resolve_bounded_analysis_cutoff(
        ticker,
        analysis_date,
        captured_at=captured_at,
        identity=identity,
    )

    assert result.status == "resolved"
    assert result.analysis_cutoff_at == expected


def test_v3_cutoff_rejects_naive_clock() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_bounded_analysis_cutoff(
            "AAPL",
            "2026-07-15",
            captured_at=datetime(2026, 7, 15, 15, 30),
            identity=_global_preflight(),
        )


def test_v3_preflight_resolution_is_pure_and_repeatable() -> None:
    class ForbiddenDependency:
        def __getattr__(self, name: str):
            raise AssertionError(f"pure v3 preflight accessed {name}")

    runner = AnalysisRunner(
        SimpleNamespace(
            memory_log=ForbiddenDependency(),
            resolve_instrument_context=ForbiddenDependency(),
        ),
        runtime_preparation=RuntimePreparationInputs(
            captured_at=datetime(2026, 7, 15, 15, 30, tzinfo=timezone.utc),
            identity_preflight=_global_preflight(),
            past_context="frozen prior context",
            instrument_context={"symbol": "AAPL", "exchange": "NMS"},
        ),
    )

    first = runner.prepare_initial_context(_request())
    second = runner.prepare_initial_context(_request())

    assert first == second
    assert first.runtime_contract.policy_version == V3_POLICY
    scaffold = first.values["research_preflight"]
    assert scaffold["verified_identity"] is None
    assert scaffold["resolved_plan"] is None
    assert scaffold["analysis_cutoff"]["analysis_cutoff_at"] == (
        "2026-07-15T15:30:00Z"
    )


@pytest.mark.parametrize(
    "missing",
    (
        "captured_at",
        "identity_preflight",
        "past_context_preflight",
        "instrument_context_preflight",
    ),
)
def test_v3_preflight_requires_every_injected_input(missing: str) -> None:
    runner = AnalysisRunner(SimpleNamespace())
    kwargs = {
        "runtime_contract": RuntimeContractSelection.v3_test(),
        "captured_at": datetime(2026, 7, 15, 15, 30, tzinfo=timezone.utc),
        "identity_preflight": _global_preflight().model_dump(mode="json"),
        "past_context_preflight": "frozen prior context",
        "instrument_context_preflight": {"symbol": "AAPL", "exchange": "NMS"},
    }
    kwargs.pop(missing)

    with pytest.raises(ValueError, match="fully injected inputs"):
        runner._resolve_initial_context(_request(), **kwargs)


@pytest.mark.parametrize(
    ("producer_policy", "consumer_policy"),
    ((V2_POLICY, V3_POLICY), (V3_POLICY, V2_POLICY)),
)
def test_commit_tokens_cannot_cross_policy_boundaries(
    producer_policy: str,
    consumer_policy: str,
) -> None:
    producer_schema = agent_state_schema_for(producer_policy)
    commit = ObservationCommitV1(
        serializer_version=SERIALIZER_VERSION,
        projection_version=BUSINESS_PROJECTION_VERSION,
        agent_state_schema_sha256=producer_schema.sha256,
        task_kind="maintenance",
        graph_task_id="task_runtime_scaffold",
        graph_step=1,
        business_delta_sha256="a" * 64,
        node_id="Runtime Scaffold",
        turn_id=None,
        tool_call_ids=(),
    ).as_dict()

    assert _parse_commit(commit, policy_version=producer_policy).as_dict() == commit
    with pytest.raises(CheckpointObservationIncompatible) as exc_info:
        _parse_commit(commit, policy_version=consumer_policy)

    assert exc_info.value.categories == ("commit_token_schema",)
