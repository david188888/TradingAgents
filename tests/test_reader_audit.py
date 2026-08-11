"""Contract tests for the terminal-run Audit Center summary and detail APIs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tradingagents.observability.events import RunEventDraft
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore, RunStoreCorruption
from tradingagents.web.api import create_app
from tradingagents.web.audit_models import AuditDetailDTO

RUN_ID = "run_20260811T010000000000Z_aaaaaaaa"
OTHER_RUN_ID = "run_20260811T020000000000Z_bbbbbbbb"
ACTOR_ID = "analyst.fundamentals"
CAPABILITY_ID = "market.price"
TOOL_CALL_ID = "tool_call_audit_1"


def _append_artifact_event(
    store: RunStore,
    run_id: str,
    artifact: Any,
    *,
    graph_task_id: str = "task_audit",
) -> None:
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
                "graph_task_id": graph_task_id,
            },
            status="committed",
        )
    )


def _seed_audit_run(
    store: RunStore,
    *,
    run_id: str = RUN_ID,
    status: str = "completed",
    legacy: bool = False,
) -> dict[str, str]:
    snapshot = RunSnapshot.create(
        run_id=run_id,
        ticker="000338.SZ",
        analysis_date="2026-08-11",
        mode="company_research",
        horizon="medium",
        llm_provider="openai",
        quick_think_llm="gpt-4.1-mini",
        deep_think_llm="gpt-4.1",
        configured_keys={"OPENAI_API_KEY": True},
        degraded_data_sources=(
            {
                "capability": CAPABILITY_ID,
                "status": "degraded",
                "attempted_vendors": ["vendor-a"],
                "selected_vendors": ["vendor-a"],
                "reasons": [{"vendor": "vendor-a", "code": "partial_window"}],
                "affected_sections": ["market"],
            },
        ),
    )
    store.create_run(snapshot)

    report = store.store_artifact(
        run_id,
        kind="report-final",
        value=f"# 完整报告\n\n利润率仍需下一期验证。\n\n运行：{run_id}",
        media_type="text/markdown",
    )
    _append_artifact_event(store, run_id, report, graph_task_id="task_report")

    private_artifact = store.store_artifact(
        run_id,
        kind="private-evidence",
        value={"raw_secret": "must-not-reach-audit-dom"},
    )
    _append_artifact_event(store, run_id, private_artifact)

    prompt = store.store_artifact(
        run_id,
        kind="prompt",
        value={
            "messages": [{"role": "user", "content": "分析利润率变化"}],
            "api_key": "sk-private-prompt-value",
        },
    )
    _append_artifact_event(store, run_id, prompt)

    config = store.store_artifact(
        run_id,
        kind="data",
        value={
            "values": {
                "llm_provider": "openai",
                "quick_think_llm": "gpt-4.1-mini",
                "max_debate_rounds": 1,
                "OPENAI_API_KEY": "sk-private-config-value",
            }
        },
    )
    _append_artifact_event(store, run_id, config)

    graph_task_id = "task_fundamentals"
    turn_id = "turn_fundamentals_1"
    attempt_id = "attempt_fundamentals_1"
    model_call_id = "model_call_fundamentals_1"
    store.append_event(
        RunEventDraft(
            run_id,
            "role.status_changed",
            {
                "role_instance_id": ACTOR_ID,
                "previous_status": "pending",
                "new_status": "completed",
                "reason": "completed",
            },
            actor_id=ACTOR_ID,
            node_id="fundamentals",
            status="completed",
        )
    )
    common_turn = {
        "role_instance_id": ACTOR_ID,
        "turn_id": turn_id,
        "graph_task_id": graph_task_id,
        "graph_step": 1,
        "turn_index": 0,
    }
    store.append_event(
        RunEventDraft(
            run_id,
            "turn.started",
            {**common_turn, "turn_status": "started"},
            actor_id=ACTOR_ID,
            node_id="fundamentals",
            status="started",
        )
    )
    model_common = {
        "turn_id": turn_id,
        "graph_task_id": graph_task_id,
        "attempt_id": attempt_id,
        "model_call_id": model_call_id,
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "invocation_path": "analysis.fundamentals",
    }
    store.append_event(
        RunEventDraft(
            run_id,
            "model.started",
            model_common,
            actor_id=ACTOR_ID,
            node_id="fundamentals",
            status="started",
        )
    )
    store.append_event(
        RunEventDraft(
            run_id,
            "input.prompt_snapshot",
            {
                "turn_id": turn_id,
                "graph_task_id": graph_task_id,
                "capture_kind": "analysis",
                "artifact_id": prompt.artifact_id,
                "content_sha256": prompt.content_sha256,
                "redaction_manifest": ["api_key"],
                "attempt_id": attempt_id,
                "model_call_id": model_call_id,
            },
            actor_id=ACTOR_ID,
            node_id="fundamentals",
        )
    )
    store.append_event(
        RunEventDraft(
            run_id,
            "input.config_snapshot",
            {
                "turn_id": turn_id,
                "graph_task_id": graph_task_id,
                "capture_kind": "effective_config",
                "artifact_id": config.artifact_id,
                "content_sha256": config.content_sha256,
                "redaction_manifest": ["values.OPENAI_API_KEY"],
            },
            actor_id=ACTOR_ID,
            node_id="fundamentals",
        )
    )
    tool_common = {
        "turn_id": turn_id,
        "graph_task_id": graph_task_id,
        "attempt_id": attempt_id,
        "tool_call_id": TOOL_CALL_ID,
        "tool_name": "get_market_data",
    }
    store.append_event(
        RunEventDraft(
            run_id,
            "tool.requested",
            {
                **tool_common,
                "arguments": {
                    "ticker": "000338.SZ",
                    "api_key": "tool-secret",
                    "path": "/private/vendor/cache",
                },
            },
            actor_id=ACTOR_ID,
            node_id="fundamentals",
            status="requested",
        )
    )
    store.append_event(
        RunEventDraft(
            run_id,
            "tool.committed",
            {**tool_common, "checkpoint_event_id": "checkpoint:tool:1"},
            actor_id=ACTOR_ID,
            node_id="fundamentals",
            status="committed",
        )
    )
    store.append_event(
        RunEventDraft(
            run_id,
            "model.completed",
            {**model_common, "duration_ms": 1200, "usage": {"total_tokens": 512}},
            actor_id=ACTOR_ID,
            node_id="fundamentals",
            status="completed",
        )
    )
    store.append_event(
        RunEventDraft(
            run_id,
            "turn.completed",
            {
                **common_turn,
                "turn_status": "completed",
                "reason": "completed",
                "duration_ms": 1500,
            },
            actor_id=ACTOR_ID,
            node_id="fundamentals",
            status="completed",
        )
    )

    current = store.read_snapshot(run_id)
    store.write_snapshot_atomic(
        current.evolve(
            status=status,
            mode=None if legacy else current.mode,
            horizon=None if legacy else current.horizon,
            completed_at="2026-08-11T01:00:00.000Z" if status == "completed" else None,
            final_report_artifact_id=report.artifact_id,
        )
    )
    return {
        "report": report.artifact_id,
        "private": private_artifact.artifact_id,
        "prompt": prompt.artifact_id,
        "config": config.artifact_id,
    }


def _detail_payload(
    *,
    availability: str,
    reason_code: str | None,
    mode: str,
) -> dict[str, Any]:
    content: dict[str, Any] = {
        "mode": mode,
        "media_type": "text/plain" if mode != "none" else None,
        "byte_size": 12 if mode != "none" else None,
        "redaction_status": "clean",
        "text": "safe content" if mode == "inline" else None,
        "download_url": "/api/download" if mode == "download" else None,
    }
    return {
        "schema_version": 1,
        "run_id": RUN_ID,
        "source_sequence": 9,
        "selection": {"kind": "run", "id": "run"},
        "availability": availability,
        "reason_code": reason_code,
        "title": "detail",
        "facts": [],
        "related_selections": [],
        "content": content,
    }


@pytest.mark.parametrize(
    ("availability", "reason_code", "mode"),
    [
        ("ready", None, "none"),
        ("ready", None, "inline"),
        ("ready", "content_too_large", "download"),
        ("ready", "unsupported_artifact", "download"),
        ("unavailable", "content_sensitive", "none"),
    ],
)
def test_detail_model_accepts_the_five_normative_outcomes(
    availability: str,
    reason_code: str | None,
    mode: str,
) -> None:
    detail = AuditDetailDTO.model_validate(
        _detail_payload(
            availability=availability,
            reason_code=reason_code,
            mode=mode,
        )
    )
    assert detail.content.mode == mode


def test_detail_model_rejects_non_normative_outcome_combinations() -> None:
    with pytest.raises(ValidationError):
        AuditDetailDTO.model_validate(
            _detail_payload(
                availability="unavailable",
                reason_code="content_sensitive",
                mode="download",
            )
        )


def test_audit_summary_is_terminal_only_and_contains_no_raw_content(tmp_path) -> None:
    store = RunStore(tmp_path)
    artifacts = _seed_audit_run(store)
    client = TestClient(create_app(store=store))

    response = client.get(f"/api/runs/{RUN_ID}/audit")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "schema_version",
        "run_id",
        "source_sequence",
        "availability",
        "reason_code",
        "run",
        "counts",
        "sections",
        "stage_navigation",
        "roles",
        "capabilities",
        "tools",
        "artifacts",
        "prompts",
        "configs",
    }
    assert payload["run"]["item_id"] == "run"
    assert payload["source_sequence"] == store.read_snapshot(RUN_ID).latest_sequence
    assert [section["section_id"] for section in payload["sections"]] == [
        "overview",
        "roles",
        "capabilities",
        "tools",
        "artifacts",
        "prompt_config",
    ]
    serialized = response.text
    for forbidden in (
        "locator",
        "content_sha256",
        "must-not-reach-audit-dom",
        "sk-private-prompt-value",
        "sk-private-config-value",
        "/private/vendor/cache",
    ):
        assert forbidden not in serialized
    private = next(item for item in payload["artifacts"] if item["item_id"] == artifacts["private"])
    assert private["content_exposure"] == "prohibited"


def test_running_run_returns_typed_terminal_guard(tmp_path) -> None:
    store = RunStore(tmp_path)
    _seed_audit_run(store, status="running")

    response = TestClient(create_app(store=store)).get(f"/api/runs/{RUN_ID}/audit")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "audit_terminal_required"


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "interrupted"])
def test_all_terminal_statuses_return_a_partial_summary_without_inventing_data(
    tmp_path,
    status: str,
) -> None:
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(
        run_id=RUN_ID,
        ticker="000338.SZ",
        analysis_date="2026-08-11",
    )
    store.create_run(snapshot)
    store.write_snapshot_atomic(snapshot.evolve(status=status))

    response = TestClient(create_app(store=store)).get(f"/api/runs/{RUN_ID}/audit")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["status"] == status
    assert payload["availability"] == "partial"
    assert any(section["availability"] == "not_recorded" for section in payload["sections"])


def test_summary_projection_failure_returns_a_safe_unavailable_envelope(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = RunStore(tmp_path)
    _seed_audit_run(store)

    def fail_events(*_args: object, **_kwargs: object) -> object:
        raise RunStoreCorruption("private storage failure")

    monkeypatch.setattr(store, "read_events", fail_events)
    response = TestClient(create_app(store=store)).get(f"/api/runs/{RUN_ID}/audit")

    assert response.status_code == 200
    payload = response.json()
    assert payload["availability"] == "unavailable"
    assert payload["reason_code"] == "projection_failed"
    assert "private storage failure" not in response.text


def test_legacy_summary_keeps_explicit_not_recorded_stage_navigation(tmp_path) -> None:
    store = RunStore(tmp_path)
    _seed_audit_run(store, legacy=True)

    payload = TestClient(create_app(store=store)).get(f"/api/runs/{RUN_ID}/audit").json()

    assert payload["availability"] == "legacy"
    assert payload["stage_navigation"]
    assert any(
        stage["availability"] == "not_recorded"
        and stage["status"] == "unknown"
        and stage["reason_code"] in {"legacy_event_gap", "not_recorded"}
        for stage in payload["stage_navigation"]
    )


@pytest.mark.parametrize(
    ("kind", "artifact_key", "selection_id"),
    [
        ("run", None, "run"),
        ("role", None, ACTOR_ID),
        ("capability", None, CAPABILITY_ID),
        ("tool", None, TOOL_CALL_ID),
        ("artifact", "private", None),
        ("prompt", "prompt", None),
        ("config", "config", None),
        ("report", "report", None),
    ],
)
def test_all_eight_detail_kinds_resolve_only_from_the_current_summary(
    tmp_path,
    kind: str,
    artifact_key: str | None,
    selection_id: str | None,
) -> None:
    store = RunStore(tmp_path)
    artifacts = _seed_audit_run(store)
    source_sequence = store.read_snapshot(RUN_ID).latest_sequence
    selected = artifacts[artifact_key] if artifact_key is not None else selection_id

    response = TestClient(create_app(store=store)).get(
        f"/api/runs/{RUN_ID}/audit/detail",
        params={"kind": kind, "id": selected, "v": source_sequence},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selection"] == {"kind": kind, "id": selected}
    assert payload["source_sequence"] == source_sequence
    assert "locator" not in response.text
    assert "content_sha256" not in response.text
    if kind == "artifact":
        assert payload["availability"] == "unavailable"
        assert payload["reason_code"] == "content_sensitive"
        assert payload["content"]["mode"] == "none"
    if kind == "report":
        assert payload["content"]["mode"] == "inline"
        assert "完整报告" in payload["content"]["text"]
    if kind == "prompt":
        assert "sk-private" not in response.text
    if kind == "config":
        assert "OPENAI_API_KEY" not in response.text


def test_detail_rejects_cross_run_ids_and_stale_summary_sequences(tmp_path) -> None:
    store = RunStore(tmp_path)
    artifacts = _seed_audit_run(store)
    other = _seed_audit_run(store, run_id=OTHER_RUN_ID)
    client = TestClient(create_app(store=store))
    original_sequence = store.read_snapshot(RUN_ID).latest_sequence

    cross_run = client.get(
        f"/api/runs/{RUN_ID}/audit/detail",
        params={"kind": "report", "id": other["report"], "v": original_sequence},
    )
    assert cross_run.status_code == 404
    assert cross_run.json()["detail"]["code"] == "audit_item_not_found"

    extra = store.store_artifact(RUN_ID, kind="data", value={"late": True})
    _append_artifact_event(store, RUN_ID, extra, graph_task_id="post_completion")
    stale = client.get(
        f"/api/runs/{RUN_ID}/audit/detail",
        params={"kind": "report", "id": artifacts["report"], "v": original_sequence},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "audit_summary_stale"


def test_report_detail_enforces_inline_limit_and_unsupported_download(tmp_path) -> None:
    store = RunStore(tmp_path)
    _seed_audit_run(store)
    exact = store.store_artifact(
        RUN_ID,
        kind="report-final",
        value="x" * (256 * 1024),
        media_type="text/markdown",
    )
    _append_artifact_event(store, RUN_ID, exact)
    oversized = store.store_artifact(
        RUN_ID,
        kind="report-final",
        value="y" * (256 * 1024 + 1),
        media_type="text/markdown",
    )
    _append_artifact_event(store, RUN_ID, oversized)
    unsupported = store.store_artifact(
        RUN_ID,
        kind="methodology-report",
        value=b"%PDF-audit",
        media_type="application/pdf",
    )
    _append_artifact_event(store, RUN_ID, unsupported)
    sequence = store.read_snapshot(RUN_ID).latest_sequence
    client = TestClient(create_app(store=store))

    exact_response = client.get(
        f"/api/runs/{RUN_ID}/audit/detail",
        params={"kind": "report", "id": exact.artifact_id, "v": sequence},
    )
    oversized_response = client.get(
        f"/api/runs/{RUN_ID}/audit/detail",
        params={"kind": "report", "id": oversized.artifact_id, "v": sequence},
    )
    unsupported_response = client.get(
        f"/api/runs/{RUN_ID}/audit/detail",
        params={"kind": "report", "id": unsupported.artifact_id, "v": sequence},
    )

    assert exact_response.json()["content"]["mode"] == "inline"
    assert oversized_response.json()["reason_code"] == "content_too_large"
    assert oversized_response.json()["content"]["mode"] == "download"
    assert unsupported_response.json()["reason_code"] == "unsupported_artifact"
    assert unsupported_response.json()["content"]["mode"] == "download"
    for response in (oversized_response, unsupported_response):
        assert response.json()["content"]["download_url"].startswith(
            f"/api/runs/{RUN_ID}/artifacts/"
        )


def test_tool_detail_redacts_secret_path_and_long_arguments(tmp_path) -> None:
    store = RunStore(tmp_path)
    _seed_audit_run(store)
    sequence = store.read_snapshot(RUN_ID).latest_sequence

    response = TestClient(create_app(store=store)).get(
        f"/api/runs/{RUN_ID}/audit/detail",
        params={"kind": "tool", "id": TOOL_CALL_ID, "v": sequence},
    )

    assert response.status_code == 200
    serialized = response.text
    assert "tool-secret" not in serialized
    assert "/private/vendor/cache" not in serialized
    facts = {item["label"]: item["value"] for item in response.json()["facts"]}
    assert isinstance(facts.get("参数摘要"), str)


def test_summary_contract_is_closed_recursively(tmp_path) -> None:
    store = RunStore(tmp_path)
    _seed_audit_run(store)
    payload = TestClient(create_app(store=store)).get(f"/api/runs/{RUN_ID}/audit").json()
    forbidden = {"locator", "content_sha256", "raw", "arguments", "values"}

    def walk(value: object) -> None:
        if isinstance(value, Mapping):
            assert forbidden.isdisjoint(value)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(payload)
