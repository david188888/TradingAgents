"""T09: catalyst artifact write/read wiring on the existing commit barrier.

The properties under test come straight from design section 7.4:

* ``GET /api/runs/{id}/catalyst`` answers ``ready | unavailable | unsupported``
  with a version field, and never conflates them.
* A missing run is 404; a run that exists without a published artifact is
  HTTP 200 ``unavailable``; a classic run is HTTP 200 ``unsupported``.
* A committed *blocked* report is HTTP 200 ``ready`` with completeness
  ``blocked`` and information-insufficient priority. ``ready`` means readable,
  not sufficient, and a consumer that collapses the two would show a
  "research passed" banner on a blocked run.
* Reading the artifact triggers 0 LLM calls and 0 provider calls.
* An internal failure does not leak its exception text.
* Promotion is refused without a committed graph task, and is idempotent.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from tradingagents.agents.schemas import (
    CatalystResearchCase,
)
from tradingagents.execution.output_publisher import (
    DERIVED_PUBLIC_CONTRACTS,
    promote_derived_public_artifact,
)
from tradingagents.observability.events import RunEventDraft
from tradingagents.research.case_assembly import (
    assemble_blocked_catalyst_case,
    build_markdown_from_case,
)
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.web.catalyst_projection import project_catalyst
from tradingagents.web.store import RunNotFound, RunStore

RUN_ID = "run_20260929T010101000000Z_c0a1a1e1"
OTHER_RUN_ID = "run_20260929T010101000000Z_0therrun"
TICKER = "600519"
AS_OF = datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)


class _ObserverSpy:
    """Minimal observer surface: records emissions, wraps a real store."""

    def __init__(self, store: RunStore, run_id: str) -> None:
        self.run_id = run_id
        self.store = store
        self.emitted: list[RunEventDraft] = []

    def emit(self, draft: RunEventDraft) -> None:
        self.emitted.append(draft)
        # The real graph observer persists on emit, and the projection reads the
        # event log. A spy that only records in memory would make the write-path
        # tests pass for the wrong reason.
        self.store.append_event(draft)


def _snapshot(
    store: RunStore,
    *,
    run_id: str = RUN_ID,
    profile: str = "catalyst_v1",
    status: str = "completed",
) -> RunSnapshot:
    snapshot = RunSnapshot.create(
        run_id=run_id,
        ticker=TICKER,
        analysis_date="2026-09-29",
        selected_analysts=("market",),
        llm_provider="openai",
        quick_think_llm="fast",
        deep_think_llm="deep",
        metadata={"research_profile": profile} if profile else {},
    )
    store.create_run(snapshot)
    if status != "created":
        # A run is only terminal for the projection once a terminal run event
        # is on the log; ``RunSnapshot.create`` alone leaves it "created".
        store.append_event(
            RunEventDraft(
                run_id,
                "run.started",
                {"run_status": status, "summary": f"run reached {status}"},
            )
        )
    return store.read_snapshot(run_id)


def _blocked_case() -> CatalystResearchCase:
    return assemble_blocked_catalyst_case(
        run_id=RUN_ID,
        ticker=TICKER,
        as_of=AS_OF,
        source_sequence=7,
        reason_codes=("identity_conflict",),
    )


def _complete_case() -> CatalystResearchCase:
    """A minimal valid ordinary case, assembled through the public schema."""
    from tests.agents.test_catalyst_research_schema import _case  # noqa: PLC0415

    return _case(run_id=RUN_ID, ticker=TICKER)


def _write_raw_artifact(store: RunStore, run_id: str, payload: dict, *, status: str = "committed") -> None:
    """Store an artifact and record the event the graph would have recorded."""
    artifact = store.store_artifact(
        run_id, kind="catalyst-research-case-v1", value=payload
    )
    store.append_event(
        RunEventDraft(
            run_id,
            "artifact.written",
            {
                "artifact_id": artifact.artifact_id,
                "kind": artifact.kind,
                "media_type": artifact.media_type,
                "content_sha256": artifact.content_sha256,
                "byte_size": artifact.byte_size,
                "locator": artifact.locator,
                "public_contract": "catalyst-research-case-v1",
                "committed_sequence": 1,
            },
            status=status,
        )
    )


def _publish(store: RunStore, case: CatalystResearchCase) -> str:
    """Write a case the way the graph does: after a committed task."""
    observer = _ObserverSpy(store, case.run_id)
    checkpoint = store.append_event(_checkpoint_draft(case.run_id))
    artifact_id = promote_derived_public_artifact(
        observer,
        contract="catalyst-research-case-v1",
        value=case,
        graph_task_id=f"gt-{case.run_id}-catalyst",
        checkpoint_event_id=checkpoint.event_id,
        committed_sequence=checkpoint.sequence,
        promoted=set(),
    )
    assert artifact_id is not None
    return artifact_id


def _checkpoint_draft(run_id: str) -> RunEventDraft:
    """A committed graph checkpoint, shaped like the one the graph emits."""
    return RunEventDraft(
        run_id,
        "state.updated",
        {
            "turn_id": "turn_1",
            "graph_task_id": f"gt-{run_id}-catalyst",
            "changed_keys": ["catalyst_case"],
            "checkpoint_event_id": "evt-checkpoint",
        },
        node_id="synthesis",
        status="committed",
    )


@pytest.fixture
def store(tmp_path) -> RunStore:
    return RunStore(tmp_path / "runs")


def test_uncommitted_case_event_is_never_a_readable_result(store):
    _snapshot(store)
    _write_raw_artifact(store, RUN_ID, _blocked_case().model_dump(mode="json"), status="candidate")
    assert project_catalyst(store, RUN_ID)["state"] == "unavailable"


# ---------------------------------------------------------------------------
# Promotion is behind the commit barrier
# ---------------------------------------------------------------------------


def test_catalyst_contract_is_registered_for_derived_promotion() -> None:
    assert "catalyst-research-case-v1" in DERIVED_PUBLIC_CONTRACTS


def test_promotion_requires_a_committed_graph_task(store: RunStore) -> None:
    _snapshot(store)
    case = _complete_case()
    with pytest.raises(ValueError, match="requires a committed graph task"):
        promote_derived_public_artifact(
            _ObserverSpy(store, case.run_id),
            contract="catalyst-research-case-v1",
            value=case,
            graph_task_id="",
            checkpoint_event_id="evt-1",
            committed_sequence=1,
            promoted=set(),
        )


def test_promotion_rejects_a_case_from_another_run(store: RunStore) -> None:
    _snapshot(store)
    foreign = _complete_case().model_copy(update={"run_id": OTHER_RUN_ID})
    with pytest.raises(ValueError, match="must belong to the observer run"):
        promote_derived_public_artifact(
            _ObserverSpy(store, RUN_ID),
            contract="catalyst-research-case-v1",
            value=foreign,
            graph_task_id="gt-1",
            checkpoint_event_id="evt-1",
            committed_sequence=1,
            promoted=set(),
        )


def test_promotion_is_idempotent_for_the_same_task_and_contract(store: RunStore) -> None:
    """A replay must not produce a second artifact or a second event."""
    _snapshot(store)
    case = _complete_case()
    observer = _ObserverSpy(store, RUN_ID)
    checkpoint = store.append_event(_checkpoint_draft(RUN_ID))
    promoted: set[tuple[str, str]] = set()
    kwargs = {
        "contract": "catalyst-research-case-v1",
        "value": case,
        "graph_task_id": "gt-1",
        "checkpoint_event_id": checkpoint.event_id,
        "committed_sequence": checkpoint.sequence,
        "promoted": promoted,
    }
    first = promote_derived_public_artifact(observer, **kwargs)
    second = promote_derived_public_artifact(observer, **kwargs)
    assert first is not None
    assert second is None
    written = [
        event
        for event in store.read_events(RUN_ID)
        if event.type == "artifact.written"
    ]
    assert len(written) == 1


# ---------------------------------------------------------------------------
# Discriminated read
# ---------------------------------------------------------------------------


def test_missing_run_raises_run_not_found(store: RunStore) -> None:
    with pytest.raises(RunNotFound):
        project_catalyst(store, "run_20260929T010101000000Z_abadc0de")


def test_classic_run_is_unsupported(store: RunStore) -> None:
    _snapshot(store, profile="classic")
    body = project_catalyst(store, RUN_ID)
    assert body["state"] == "unsupported"
    assert body["reason_code"] == "classic_profile"
    assert body["schema_version"] == 1


def test_unknown_profile_is_unsupported_with_its_own_reason(store: RunStore) -> None:
    """A typo'd profile is a distinct condition, not a silent classic."""
    _snapshot(store, profile="catalyst_v2")
    body = project_catalyst(store, RUN_ID)
    assert body["state"] == "unsupported"
    assert body["reason_code"] == "unknown_profile"


def test_unavailable_and_unsupported_are_different_shapes(store: RunStore) -> None:
    _snapshot(store, profile="classic")
    unsupported = project_catalyst(store, RUN_ID)
    _snapshot(store, run_id="run_20260929T010101000000Z_c0a1a1e2", profile="catalyst_v1")
    unavailable = project_catalyst(store, "run_20260929T010101000000Z_c0a1a1e2")
    assert set(unsupported) != set(unavailable)
    assert "reason_codes" in unavailable and "reason_codes" not in unsupported
    assert "run_status" in unavailable and "run_status" not in unsupported


def test_completed_run_without_an_artifact_is_unavailable_not_missing_404(store) -> None:
    _snapshot(store, profile="catalyst_v1")
    body = project_catalyst(store, RUN_ID)
    assert body["state"] == "unavailable"
    assert body["reason_code"] == "missing"
    assert body["run_status"] == "completed"


def test_running_run_reports_a_different_reason_than_a_missing_artifact(store) -> None:
    snapshot = RunSnapshot.create(
        run_id=RUN_ID,
        ticker=TICKER,
        analysis_date="2026-09-29",
        selected_analysts=("market",),
        llm_provider="openai",
        quick_think_llm="fast",
        deep_think_llm="deep",
        metadata={"research_profile": "catalyst_v1"},
    )
    store.create_run(snapshot)
    store.append_event(RunEventDraft(RUN_ID, "run.started", {"run_status": "running"}))
    body = project_catalyst(store, RUN_ID)
    assert body["state"] == "unavailable"
    assert body["reason_code"] == "run_running"
    assert body["run_status"] == "running"


def test_ready_carries_completeness_and_priority_at_the_top_level(store) -> None:
    """A consumer must not have to walk the case to render the outcome."""
    _snapshot(store, profile="catalyst_v1")
    _publish(store, _complete_case())
    body = project_catalyst(store, RUN_ID)
    assert body["state"] == "ready"
    assert body["completeness"] == "complete"
    assert body["priority"] == "verify_first"
    assert body["case_schema_version"] == "catalyst-research-case-v1"
    # The count travels alongside the case so a consumer can display the
    # budget state without re-deriving it; it is never stored on the case.
    assert "character_count" not in body["case"]["brief"]
    assert body["brief_character_count"] > 0


def test_blocked_case_is_ready_but_not_sufficient(store) -> None:
    """Design section 7.4: committed blocked report is ready + blocked."""
    _snapshot(store, profile="catalyst_v1")
    _publish(store, _blocked_case())
    body = project_catalyst(store, RUN_ID)
    assert body["state"] == "ready"
    assert body["completeness"] == "blocked"
    assert body["priority"] == "insufficient_information"
    assert body["brief"]["kind"] == "safety_overflow"
    assert body["brief"]["overflow_reason"] == "brief_safety_overflow"


def test_ready_is_not_the_same_as_research_passing(store) -> None:
    """The failure mode this guards: a consumer reading ready as PASS."""
    _snapshot(store, profile="catalyst_v1")
    _publish(store, _blocked_case())
    body = project_catalyst(store, RUN_ID)
    assert body["state"] == "ready"
    assert body["quality"] == "FAIL_STOP"
    assert body["completeness"] != "complete"


def test_corrupt_artifact_degrades_to_unavailable_without_leaking(store) -> None:
    _snapshot(store, profile="catalyst_v1")
    case = _complete_case()
    payload = case.model_dump(mode="json")
    payload["completeness"] = "not-a-real-completeness"
    _write_raw_artifact(store, RUN_ID, payload)
    body = project_catalyst(store, RUN_ID)
    assert body["state"] == "unavailable"
    assert body["reason_code"] == "corrupt"


def test_artifact_from_another_run_is_not_served_as_this_runs_result(store) -> None:
    _snapshot(store, profile="catalyst_v1")
    foreign = _complete_case().model_copy(update={"run_id": OTHER_RUN_ID})
    payload = foreign.model_dump(mode="json")
    _write_raw_artifact(store, RUN_ID, payload)
    assert project_catalyst(store, RUN_ID)["state"] == "unavailable"


def test_projection_is_deterministic_across_repeated_reads(store) -> None:
    _snapshot(store, profile="catalyst_v1")
    _publish(store, _complete_case())
    first = project_catalyst(store, RUN_ID)
    second = project_catalyst(store, RUN_ID)
    assert first == second


# ---------------------------------------------------------------------------
# Reading calls nothing
# ---------------------------------------------------------------------------


def test_reading_triggers_zero_llm_and_zero_provider_calls(store, monkeypatch) -> None:
    """Design section 7.4 and gate A10: a read is a read, not a recompute."""
    _snapshot(store, profile="catalyst_v1")
    _publish(store, _complete_case())

    calls: list[str] = []

    class _Tripwire:
        def __init__(self, label: str) -> None:
            self.label = label

        def __getattr__(self, name: str):
            def _boom(*args, **kwargs):
                calls.append(f"{self.label}.{name}")
                raise AssertionError(f"catalyst read called {self.label}.{name}")

            return _boom

        def __call__(self, *args, **kwargs):
            calls.append(f"{self.label}()")
            raise AssertionError(f"catalyst read called {self.label}()")

    # Trip every LLM factory and the vendor-routing entry point that would
    # reach a provider, so any attempt to recompute rather than read fails.
    for module_path, attribute in (
        ("tradingagents.llm_clients", "create_llm_client"),
        ("tradingagents.llm_clients.factory", "create_llm_client"),
        ("tradingagents.llm_clients", "BaseLLMClient"),
        ("tradingagents.dataflows.interface", "route_to_vendor"),
        ("tradingagents.dataflows.interface", "route_to_vendor_with_trace"),
    ):
        module = __import__(module_path, fromlist=[attribute])
        if hasattr(module, attribute):
            monkeypatch.setattr(module, attribute, _Tripwire(f"{module_path}.{attribute}"))

    body = project_catalyst(store, RUN_ID)
    assert body["state"] == "ready"
    assert calls == []


# ---------------------------------------------------------------------------
# Markdown renders from the same case
# ---------------------------------------------------------------------------


def test_markdown_renders_from_the_same_case_without_a_second_model_call() -> None:
    case = _complete_case()
    markdown = build_markdown_from_case(case)
    assert case.brief.judgement in markdown
    assert case.brief.next_check.text in markdown
    assert f"brief_characters={case.brief.character_count}" in markdown


def test_markdown_keeps_every_limitation(store) -> None:
    case = _complete_case()
    assert case.brief.judgement in build_markdown_from_case(case)


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------


@pytest.fixture
def client(store) -> TestClient:
    from tradingagents.web.api import create_app

    return TestClient(create_app(store=store), raise_server_exceptions=False)


def test_endpoint_returns_200_unavailable_for_an_unpublished_run(client) -> None:
    _snapshot(store_of(client), profile="catalyst_v1")
    response = client.get(f"/api/runs/{RUN_ID}/catalyst")
    assert response.status_code == 200
    assert response.json()["state"] == "unavailable"


def test_endpoint_returns_404_for_a_missing_run(client) -> None:
    response = client.get("/api/runs/run_20260929T010101000000Z_abadc0de/catalyst")
    assert response.status_code == 404


def test_endpoint_returns_200_unsupported_for_a_classic_run(client) -> None:
    _snapshot(store_of(client), profile="classic")
    response = client.get(f"/api/runs/{RUN_ID}/catalyst")
    assert response.status_code == 200
    assert response.json()["state"] == "unsupported"


def test_endpoint_serves_a_committed_blocked_case(client) -> None:
    store = store_of(client)
    _snapshot(store, profile="catalyst_v1")
    _publish(store, _blocked_case())
    response = client.get(f"/api/runs/{RUN_ID}/catalyst")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ready"
    assert body["completeness"] == "blocked"
    assert body["priority"] == "insufficient_information"


def test_endpoint_does_not_leak_internal_exception_text(client, store) -> None:
    """Design section 7.4: internal errors use the safe envelope."""
    _snapshot(store, profile="catalyst_v1")
    _publish(store, _complete_case())
    original = store.read_artifact
    store.read_artifact = lambda *a, **k: (_ for _ in ()).throw(  # type: ignore[method-assign]
        RuntimeError("SECRET_MARKER_9f2a: upstream provider key sk-abcdef0123456789")
    )
    try:
        response = client.get(f"/api/runs/{RUN_ID}/catalyst")
    finally:
        store.read_artifact = original  # type: ignore[method-assign]
    text = response.text
    assert "SECRET_MARKER_9f2a" not in text
    assert "sk-abcdef0123456789" not in text
    assert "RuntimeError" not in text


def test_public_case_never_exposes_internal_locators_or_secrets(client, store) -> None:
    _snapshot(store, profile="catalyst_v1")
    _publish(store, _complete_case())
    body = client.get(f"/api/runs/{RUN_ID}/catalyst").json()
    serialized = str(body)
    assert "locator" not in serialized
    assert "content_sha256" not in serialized
    assert "sk-" not in serialized


def store_of(client: TestClient) -> RunStore:
    return client.app.state.store
