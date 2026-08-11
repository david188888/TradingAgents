"""Read-only projections for the terminal-run Audit Center."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import quote

from tradingagents.observability.events import PersistedEvent
from tradingagents.observability.redaction import redact_recursive
from tradingagents.observability.roles import ROLE_REGISTRY
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore

from .audit_models import (
    AuditArtifactSummary,
    AuditCapabilitySummary,
    AuditContent,
    AuditCounts,
    AuditDetailDTO,
    AuditFact,
    AuditPromptConfigSummary,
    AuditRoleSummary,
    AuditRunSummary,
    AuditSectionSummary,
    AuditSelection,
    AuditStageSummary,
    AuditSummaryDTO,
    AuditToolSummary,
)
from .projections import build_workflow

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})
INLINE_LIMIT_BYTES = 256 * 1024
SAFE_INLINE_KINDS = frozenset({"report-final", "report-revision"})
DOWNLOAD_ONLY_KINDS = frozenset({"methodology-report"})
REPORT_KINDS = SAFE_INLINE_KINDS | DOWNLOAD_ONLY_KINDS
TEXT_MEDIA_TYPES = frozenset({"application/json", "text/markdown", "text/plain"})
CONFIG_ALLOWLIST = frozenset(
    {
        "checkpoint_enabled",
        "deep_think_llm",
        "horizon",
        "llm_provider",
        "max_debate_rounds",
        "max_risk_discuss_rounds",
        "mode",
        "output_language",
        "quick_think_llm",
        "research_depth",
        "selected_analysts",
    }
)
STAGE_LABELS = {
    "analysts": "分析师",
    "evidence": "证据治理",
    "research": "研究辩论",
    "trading": "研究结论",
    "risk": "风险辩论",
    "portfolio": "组合审议",
}


class AuditItemNotFound(LookupError):
    pass


class AuditSummaryStale(RuntimeError):
    pass


class AuditTerminalRequired(RuntimeError):
    pass


def _artifact_exposure(kind: str) -> str:
    if kind in SAFE_INLINE_KINDS:
        return "safe_inline"
    if kind in DOWNLOAD_ONLY_KINDS:
        return "download_only"
    return "prohibited"


def _artifact_index(events: list[PersistedEvent]) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.type != "artifact.written":
            continue
        payload = event.payload
        artifact_id = payload.get("artifact_id")
        if not isinstance(artifact_id, str):
            continue
        kind = str(payload.get("kind") or "data")
        artifacts.setdefault(
            artifact_id,
            {
                "artifact_id": artifact_id,
                "kind": kind,
                "media_type": str(payload.get("media_type") or "application/octet-stream"),
                "byte_size": max(0, int(payload.get("byte_size") or 0)),
                "producer_stage": _optional_text(payload.get("graph_task_id")),
                "content_exposure": _artifact_exposure(kind),
                "is_report": kind in REPORT_KINDS,
            },
        )
    return artifacts


def _input_index(
    events: list[PersistedEvent],
    artifacts: Mapping[str, dict[str, Any]],
    event_type: str,
) -> dict[str, dict[str, Any]]:
    captured: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.type != event_type:
            continue
        artifact_id = event.payload.get("artifact_id")
        if not isinstance(artifact_id, str) or artifact_id not in artifacts:
            continue
        manifest = event.payload.get("redaction_manifest")
        captured.setdefault(
            artifact_id,
            {
                "artifact_id": artifact_id,
                "actor_id": event.actor_id,
                "model_call_id": _optional_text(event.payload.get("model_call_id")),
                "redaction_status": "redacted" if isinstance(manifest, list) and manifest else "clean",
            },
        )
    return captured


def _role_summaries(events: list[PersistedEvent]) -> tuple[AuditRoleSummary, ...]:
    statuses: dict[str, str] = {role.actor_id: "not_reached" for role in ROLE_REGISTRY}
    turn_ids: dict[str, set[str]] = defaultdict(set)
    model_ids: dict[str, set[str]] = defaultdict(set)
    durations: Counter[str] = Counter()
    has_duration: set[str] = set()
    for event in events:
        actor = event.actor_id
        if not actor:
            continue
        if event.type == "role.status_changed":
            status = event.payload.get("new_status")
            if isinstance(status, str):
                statuses[actor] = status
        if event.type.startswith("turn."):
            turn_id = event.payload.get("turn_id")
            if isinstance(turn_id, str):
                turn_ids[actor].add(turn_id)
            duration = event.payload.get("duration_ms")
            if isinstance(duration, int) and duration >= 0:
                durations[actor] += duration
                has_duration.add(actor)
        if event.type.startswith("model."):
            model_id = event.payload.get("model_call_id")
            if isinstance(model_id, str):
                model_ids[actor].add(model_id)
    return tuple(
        AuditRoleSummary(
            item_id=role.actor_id,
            actor_id=role.actor_id,
            label=role.display_name,
            status=statuses[role.actor_id],
            turn_count=len(turn_ids[role.actor_id]),
            model_call_count=len(model_ids[role.actor_id]),
            duration_ms=durations[role.actor_id] if role.actor_id in has_duration else None,
        )
        for role in ROLE_REGISTRY
    )


def _capability_summaries(snapshot: RunSnapshot) -> tuple[AuditCapabilitySummary, ...]:
    rendered: list[AuditCapabilitySummary] = []
    for item in snapshot.degraded_data_sources:
        capability = item.get("capability")
        if not isinstance(capability, str) or not capability:
            continue
        reasons = item.get("reasons")
        reason_codes = tuple(
            str(reason.get("code"))
            for reason in reasons
            if isinstance(reasons, list)
            and isinstance(reason, Mapping)
            and reason.get("code")
        ) if isinstance(reasons, list) else ()
        affected = item.get("affected_sections")
        rendered.append(
            AuditCapabilitySummary(
                item_id=capability,
                label=capability,
                status=str(item.get("status") or "degraded"),
                reason_codes=reason_codes,
                affected_sections=tuple(str(value) for value in affected)
                if isinstance(affected, list)
                else (),
            )
        )
    return tuple(rendered)


def _tool_summaries(events: list[PersistedEvent]) -> tuple[AuditToolSummary, ...]:
    tools: dict[str, dict[str, Any]] = {}
    for event in events:
        if not event.type.startswith("tool."):
            continue
        tool_id = event.payload.get("tool_call_id")
        if not isinstance(tool_id, str):
            continue
        item = tools.setdefault(
            tool_id,
            {
                "tool_name": str(event.payload.get("tool_name") or "unknown"),
                "status": "requested",
                "execution_count": 0,
                "failure_code": None,
            },
        )
        if event.type.startswith("tool.execution_"):
            item["execution_count"] += 1
        if event.type == "tool.committed":
            item["status"] = "committed"
        elif event.type in {"tool.cancelled", "tool.execution_failed"}:
            item["status"] = "failed" if event.type.endswith("failed") else "cancelled"
            item["failure_code"] = _optional_text(event.payload.get("reason"))
        elif event.type == "tool.execution_started":
            item["status"] = "running"
    return tuple(
        AuditToolSummary(
            item_id=tool_id,
            tool_name=value["tool_name"],
            status=value["status"],
            execution_count=value["execution_count"],
            cache_status="not_recorded",
            failure_code=value["failure_code"],
        )
        for tool_id, value in tools.items()
    )


def _artifact_summaries(
    artifacts: Mapping[str, dict[str, Any]],
) -> tuple[AuditArtifactSummary, ...]:
    return tuple(
        AuditArtifactSummary(
            item_id=item["artifact_id"],
            label=_artifact_label(item["kind"]),
            artifact_kind=item["kind"],
            media_type=item["media_type"],
            byte_size=item["byte_size"],
            producer_stage=item["producer_stage"],
            content_exposure=item["content_exposure"],
            is_report=item["is_report"],
        )
        for item in artifacts.values()
    )


def _prompt_config_summaries(
    captured: Mapping[str, dict[str, Any]],
    artifacts: Mapping[str, dict[str, Any]],
    *,
    label: str,
) -> tuple[AuditPromptConfigSummary, ...]:
    return tuple(
        AuditPromptConfigSummary(
            item_id=artifact_id,
            label=label,
            actor_id=item["actor_id"],
            model_call_id=item["model_call_id"],
            redaction_status=item["redaction_status"],
            byte_size=artifacts[artifact_id]["byte_size"],
        )
        for artifact_id, item in captured.items()
    )


def _stage_navigation(
    events: list[PersistedEvent],
    roles: tuple[AuditRoleSummary, ...],
    *,
    legacy: bool,
) -> tuple[AuditStageSummary, ...]:
    role_index = {item.item_id: item for item in roles}
    if legacy:
        return tuple(
            AuditStageSummary(
                stage_id=stage_id,
                label=label,
                status="unknown",
                availability="not_recorded",
                reason_code="legacy_event_gap",
            )
            for stage_id, label in STAGE_LABELS.items()
        )
    workflow = build_workflow(events)
    stages: list[AuditStageSummary] = []
    for stage in workflow["stages"]:
        stage_id = str(stage["stage_id"])
        status = "not_started" if stage["status"] == "waiting" else str(stage["status"])
        related = tuple(
            AuditSelection(kind="role", id=str(actor["actor_id"]))
            for actor in stage["actors"]
            if str(actor["actor_id"]) in role_index
            and role_index[str(actor["actor_id"])].status != "not_reached"
        )
        stages.append(
            AuditStageSummary(
                stage_id=stage_id,
                label=STAGE_LABELS.get(stage_id, stage_id),
                status=status,
                availability="ready",
                related_selections=related,
            )
        )
    return tuple(stages)


def _duration_ms(snapshot: RunSnapshot) -> int | None:
    if snapshot.completed_at is None:
        return None
    try:
        start = datetime.fromisoformat(snapshot.created_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(snapshot.completed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, round((end - start).total_seconds() * 1000))


def _data_quality(snapshot: RunSnapshot) -> str:
    statuses = {str(item.get("status")) for item in snapshot.degraded_data_sources}
    if "unavailable" in statuses or "degraded" in statuses:
        return "limited"
    return "unknown" if snapshot.mode is None else "healthy"


def _build_summary(
    snapshot: RunSnapshot,
    events: list[PersistedEvent],
) -> AuditSummaryDTO:
    artifacts = _artifact_index(events)
    prompt_index = _input_index(events, artifacts, "input.prompt_snapshot")
    config_index = _input_index(events, artifacts, "input.config_snapshot")
    roles = _role_summaries(events)
    capabilities = _capability_summaries(snapshot)
    tools = _tool_summaries(events)
    artifact_summaries = _artifact_summaries(artifacts)
    prompts = _prompt_config_summaries(prompt_index, artifacts, label="Prompt snapshot")
    configs = _prompt_config_summaries(config_index, artifacts, label="Effective config")
    legacy = snapshot.mode is None or snapshot.horizon is None
    stages = _stage_navigation(events, roles, legacy=legacy)
    report_count = sum(item.is_report for item in artifact_summaries)
    turn_count = len(
        {
            str(event.payload["turn_id"])
            for event in events
            if event.type.startswith("turn.") and isinstance(event.payload.get("turn_id"), str)
        }
    )
    model_count = len(
        {
            str(event.payload["model_call_id"])
            for event in events
            if event.type.startswith("model.")
            and isinstance(event.payload.get("model_call_id"), str)
        }
    )
    section_values = (
        ("overview", 1),
        ("roles", len(roles)),
        ("capabilities", len(capabilities)),
        ("tools", len(tools)),
        ("artifacts", len(artifact_summaries)),
        ("prompt_config", len(prompts) + len(configs)),
    )
    sections = tuple(
        AuditSectionSummary(
            section_id=section_id,
            availability="ready" if count else "not_recorded",
            reason_code=None if count else "not_recorded",
            item_count=count,
        )
        for section_id, count in section_values
    )
    partial = any(section.availability != "ready" for section in sections)
    availability = "legacy" if legacy else "partial" if partial else "ready"
    reason_code = "legacy_event_gap" if legacy else "terminal_data_incomplete" if partial else None
    return AuditSummaryDTO(
        run_id=snapshot.run_id,
        source_sequence=snapshot.latest_sequence,
        availability=availability,
        reason_code=reason_code,
        run=AuditRunSummary(
            status=snapshot.status,
            ticker=snapshot.ticker,
            mode=snapshot.mode,
            horizon=snapshot.horizon,
            created_at=snapshot.created_at,
            completed_at=snapshot.completed_at,
            duration_ms=_duration_ms(snapshot),
            llm_provider=snapshot.llm_provider,
            quick_think_llm=snapshot.quick_think_llm,
            deep_think_llm=snapshot.deep_think_llm,
            data_quality=_data_quality(snapshot),
        ),
        counts=AuditCounts(
            stages=len(stages),
            roles=len(roles),
            turns=turn_count,
            model_calls=model_count,
            tool_calls=len(tools),
            artifacts=len(artifact_summaries),
            prompts=len(prompts),
            configs=len(configs),
            reports=report_count,
        ),
        sections=sections,
        stage_navigation=stages,
        roles=roles,
        capabilities=capabilities,
        tools=tools,
        artifacts=artifact_summaries,
        prompts=prompts,
        configs=configs,
    )


def _terminal_snapshot(store: RunStore, run_id: str) -> RunSnapshot:
    snapshot = store.read_snapshot(run_id)
    if snapshot.status not in TERMINAL_STATUSES:
        raise AuditTerminalRequired(run_id)
    return snapshot


def project_audit_summary(store: RunStore, run_id: str) -> dict[str, Any]:
    snapshot = _terminal_snapshot(store, run_id)
    try:
        summary = _build_summary(snapshot, store.read_events(run_id))
    except Exception:  # noqa: BLE001 - the public envelope hides storage details
        summary = _unavailable_summary(snapshot)
    return summary.model_dump(mode="json")


def _unavailable_summary(snapshot: RunSnapshot) -> AuditSummaryDTO:
    sections = tuple(
        AuditSectionSummary(
            section_id=section_id,
            availability="unavailable",
            reason_code="projection_failed",
            item_count=0,
        )
        for section_id in (
            "overview",
            "roles",
            "capabilities",
            "tools",
            "artifacts",
            "prompt_config",
        )
    )
    return AuditSummaryDTO(
        run_id=snapshot.run_id,
        source_sequence=snapshot.latest_sequence,
        availability="unavailable",
        reason_code="projection_failed",
        run=AuditRunSummary(
            status=snapshot.status,
            ticker=snapshot.ticker,
            mode=snapshot.mode,
            horizon=snapshot.horizon,
            created_at=snapshot.created_at,
            completed_at=snapshot.completed_at,
            duration_ms=_duration_ms(snapshot),
            llm_provider=snapshot.llm_provider,
            quick_think_llm=snapshot.quick_think_llm,
            deep_think_llm=snapshot.deep_think_llm,
            data_quality="unknown",
        ),
        counts=AuditCounts(
            stages=0,
            roles=0,
            turns=0,
            model_calls=0,
            tool_calls=0,
            artifacts=0,
            prompts=0,
            configs=0,
            reports=0,
        ),
        sections=sections,
    )


def _selection_exists(summary: AuditSummaryDTO, selection: AuditSelection) -> bool:
    indexes = {
        "run": {summary.run.item_id},
        "role": {item.item_id for item in summary.roles},
        "capability": {item.item_id for item in summary.capabilities},
        "tool": {item.item_id for item in summary.tools},
        "artifact": {item.item_id for item in summary.artifacts},
        "prompt": {item.item_id for item in summary.prompts},
        "config": {item.item_id for item in summary.configs},
        "report": {item.item_id for item in summary.artifacts if item.is_report},
    }
    return selection.id in indexes[selection.kind]


def _empty_content(redaction_status: str = "clean") -> AuditContent:
    return AuditContent(mode="none", redaction_status=redaction_status)


def _facts(**values: Any) -> tuple[AuditFact, ...]:
    return tuple(AuditFact(label=label, value=value) for label, value in values.items())


def _structured_detail(
    snapshot: RunSnapshot,
    selection: AuditSelection,
    title: str,
    facts: tuple[AuditFact, ...],
) -> AuditDetailDTO:
    return AuditDetailDTO(
        run_id=snapshot.run_id,
        source_sequence=snapshot.latest_sequence,
        selection=selection,
        availability="ready",
        title=title,
        facts=facts,
        content=_empty_content(),
    )


def _unavailable_detail(
    snapshot: RunSnapshot,
    selection: AuditSelection,
    title: str,
    reason: str,
    *,
    media_type: str | None = None,
    byte_size: int | None = None,
) -> AuditDetailDTO:
    return AuditDetailDTO(
        run_id=snapshot.run_id,
        source_sequence=snapshot.latest_sequence,
        selection=selection,
        availability="unavailable",
        reason_code=reason,
        title=title,
        content=AuditContent(
            mode="none",
            media_type=media_type,
            byte_size=byte_size,
            redaction_status="metadata_only",
        ),
    )


def _artifact_detail(
    store: RunStore,
    snapshot: RunSnapshot,
    selection: AuditSelection,
    artifact: Mapping[str, Any],
    *,
    redaction_status: str = "clean",
) -> AuditDetailDTO:
    title = _artifact_label(str(artifact["kind"]))
    exposure = artifact["content_exposure"]
    media_type = str(artifact["media_type"])
    byte_size = int(artifact["byte_size"])
    if exposure == "prohibited":
        return _unavailable_detail(
            snapshot,
            selection,
            title,
            "content_sensitive",
            media_type=media_type,
            byte_size=byte_size,
        )
    download_url = _download_url(snapshot.run_id, selection.id)
    if exposure == "download_only" or media_type not in TEXT_MEDIA_TYPES:
        return AuditDetailDTO(
            run_id=snapshot.run_id,
            source_sequence=snapshot.latest_sequence,
            selection=selection,
            availability="ready",
            reason_code="unsupported_artifact",
            title=title,
            content=AuditContent(
                mode="download",
                media_type=media_type,
                byte_size=byte_size,
                redaction_status=redaction_status,
                download_url=download_url,
            ),
        )
    if byte_size > INLINE_LIMIT_BYTES:
        return AuditDetailDTO(
            run_id=snapshot.run_id,
            source_sequence=snapshot.latest_sequence,
            selection=selection,
            availability="ready",
            reason_code="content_too_large",
            title=title,
            content=AuditContent(
                mode="download",
                media_type=media_type,
                byte_size=byte_size,
                redaction_status=redaction_status,
                download_url=download_url,
            ),
        )
    try:
        text = store.read_artifact(snapshot.run_id, selection.id).decode("utf-8")
    except UnicodeDecodeError:
        return AuditDetailDTO(
            run_id=snapshot.run_id,
            source_sequence=snapshot.latest_sequence,
            selection=selection,
            availability="ready",
            reason_code="unsupported_artifact",
            title=title,
            content=AuditContent(
                mode="download",
                media_type=media_type,
                byte_size=byte_size,
                redaction_status=redaction_status,
                download_url=download_url,
            ),
        )
    return AuditDetailDTO(
        run_id=snapshot.run_id,
        source_sequence=snapshot.latest_sequence,
        selection=selection,
        availability="ready",
        title=title,
        content=AuditContent(
            mode="inline",
            media_type=media_type,
            byte_size=byte_size,
            redaction_status=redaction_status,
            text=text,
        ),
    )


def _prompt_detail(
    store: RunStore,
    snapshot: RunSnapshot,
    selection: AuditSelection,
    artifact: Mapping[str, Any],
    input_item: Mapping[str, Any],
) -> AuditDetailDTO:
    byte_size = int(artifact["byte_size"])
    redaction_status = str(input_item["redaction_status"])
    if byte_size > INLINE_LIMIT_BYTES:
        return AuditDetailDTO(
            run_id=snapshot.run_id,
            source_sequence=snapshot.latest_sequence,
            selection=selection,
            availability="ready",
            reason_code="content_too_large",
            title="Prompt snapshot",
            content=AuditContent(
                mode="download",
                media_type=str(artifact["media_type"]),
                byte_size=byte_size,
                redaction_status=redaction_status,
                download_url=_download_url(snapshot.run_id, selection.id),
            ),
        )
    raw = store.read_artifact(snapshot.run_id, selection.id).decode("utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        safe_text = raw
    else:
        safe = redact_recursive(parsed)
        safe_text = json.dumps(safe.value, ensure_ascii=False, indent=2)
        if safe.manifest:
            redaction_status = "redacted"
    return AuditDetailDTO(
        run_id=snapshot.run_id,
        source_sequence=snapshot.latest_sequence,
        selection=selection,
        availability="ready",
        title="Prompt snapshot",
        facts=_facts(所属角色=input_item.get("actor_id"), 模型调用=input_item.get("model_call_id")),
        content=AuditContent(
            mode="inline",
            media_type=str(artifact["media_type"]),
            byte_size=byte_size,
            redaction_status=redaction_status,
            text=safe_text,
        ),
    )


def _config_detail(
    store: RunStore,
    snapshot: RunSnapshot,
    selection: AuditSelection,
    artifact: Mapping[str, Any],
    input_item: Mapping[str, Any],
) -> AuditDetailDTO:
    raw = store.read_artifact(snapshot.run_id, selection.id)
    if len(raw) > INLINE_LIMIT_BYTES:
        return _unavailable_detail(
            snapshot,
            selection,
            "Effective config",
            "content_sensitive",
            media_type=str(artifact["media_type"]),
            byte_size=len(raw),
        )
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _unavailable_detail(
            snapshot,
            selection,
            "Effective config",
            "detail_not_available",
            media_type=str(artifact["media_type"]),
            byte_size=len(raw),
        )
    values = parsed.get("values") if isinstance(parsed, Mapping) else None
    source = values if isinstance(values, Mapping) else parsed if isinstance(parsed, Mapping) else {}
    allowed = {key: source[key] for key in sorted(source) if key in CONFIG_ALLOWLIST}
    return AuditDetailDTO(
        run_id=snapshot.run_id,
        source_sequence=snapshot.latest_sequence,
        selection=selection,
        availability="ready",
        title="Effective config",
        facts=_facts(所属角色=input_item.get("actor_id")),
        content=AuditContent(
            mode="inline",
            media_type="application/json",
            byte_size=len(raw),
            redaction_status=str(input_item["redaction_status"]),
            text=json.dumps(allowed, ensure_ascii=False, indent=2),
        ),
    )


def _tool_arguments(events: list[PersistedEvent], tool_id: str) -> Mapping[str, Any]:
    for event in events:
        if event.type == "tool.requested" and event.payload.get("tool_call_id") == tool_id:
            arguments = event.payload.get("arguments")
            return arguments if isinstance(arguments, Mapping) else {}
    return {}


def _safe_argument_summary(arguments: Mapping[str, Any]) -> str:
    def sanitize(key: str, value: Any) -> Any:
        lowered = key.lower()
        if any(token in lowered for token in ("key", "token", "secret", "password", "cookie", "path", "locator")):
            return "[redacted]"
        if isinstance(value, Mapping):
            return {str(nested): sanitize(str(nested), child) for nested, child in value.items()}
        if isinstance(value, list):
            return [sanitize(key, child) for child in value[:20]]
        if isinstance(value, str) and len(value) > 160:
            return value[:157] + "…"
        return value

    safe = {str(key): sanitize(str(key), value) for key, value in arguments.items()}
    return json.dumps(safe, ensure_ascii=False, sort_keys=True)


def project_audit_detail(
    store: RunStore,
    run_id: str,
    selection: AuditSelection,
    source_sequence: int,
) -> dict[str, Any]:
    snapshot = _terminal_snapshot(store, run_id)
    if snapshot.latest_sequence != source_sequence:
        raise AuditSummaryStale(run_id)
    events = store.read_events(run_id, through=source_sequence)
    summary = _build_summary(snapshot, events)
    if not _selection_exists(summary, selection):
        raise AuditItemNotFound(selection.id)
    artifacts = _artifact_index(events)
    prompts = _input_index(events, artifacts, "input.prompt_snapshot")
    configs = _input_index(events, artifacts, "input.config_snapshot")

    if selection.kind == "run":
        detail = _structured_detail(
            snapshot,
            selection,
            f"运行 {snapshot.run_id}",
            _facts(
                状态=snapshot.status,
                标的=snapshot.ticker,
                模式=snapshot.mode,
                周期=snapshot.horizon,
                模型提供方=snapshot.llm_provider,
                密钥状态=json.dumps(snapshot.configured_keys, ensure_ascii=False, sort_keys=True),
            ),
        )
    elif selection.kind == "role":
        role = next(item for item in summary.roles if item.item_id == selection.id)
        if role.status == "not_reached":
            detail = _unavailable_detail(snapshot, selection, role.label, "not_recorded")
        else:
            detail = _structured_detail(
                snapshot,
                selection,
                role.label,
                _facts(
                    状态=role.status,
                    轮次=role.turn_count,
                    模型调用=role.model_call_count,
                    耗时毫秒=role.duration_ms,
                ),
            )
    elif selection.kind == "capability":
        item = next(item for item in summary.capabilities if item.item_id == selection.id)
        detail = _structured_detail(
            snapshot,
            selection,
            item.label,
            _facts(
                状态=item.status,
                原因="、".join(item.reason_codes) or None,
                影响分区="、".join(item.affected_sections) or None,
            ),
        )
    elif selection.kind == "tool":
        item = next(item for item in summary.tools if item.item_id == selection.id)
        detail = _structured_detail(
            snapshot,
            selection,
            item.tool_name,
            _facts(
                状态=item.status,
                执行次数=item.execution_count,
                缓存状态=item.cache_status,
                错误分类=item.failure_code,
                参数摘要=_safe_argument_summary(_tool_arguments(events, selection.id)),
            ),
        )
    elif selection.kind == "prompt":
        detail = _prompt_detail(store, snapshot, selection, artifacts[selection.id], prompts[selection.id])
    elif selection.kind == "config":
        detail = _config_detail(store, snapshot, selection, artifacts[selection.id], configs[selection.id])
    else:
        detail = _artifact_detail(store, snapshot, selection, artifacts[selection.id])
    return detail.model_dump(mode="json")


def _artifact_label(kind: str) -> str:
    return kind.replace("-", " ").title()


def _download_url(run_id: str, artifact_id: str) -> str:
    return f"/api/runs/{run_id}/artifacts/{quote(artifact_id, safe='')}"


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
