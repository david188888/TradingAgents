"""Reader-first, deterministic projections over committed web run facts.

The module deliberately has no agent or report-generation dependency. It reads
append-only events, committed snapshots, and typed public artifacts only. The
materialized files are caches: a damaged or stale file is rebuilt from the
same facts and never changes a run's audit history.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from tradingagents.observability.events import PersistedEvent
from tradingagents.observability.roles import ROLE_REGISTRY
from tradingagents.portfolio import ConvictionSignal, aggregate_risk_convictions
from tradingagents.research import build_holding_review_summary

from .debate_summary import DEBATE_SUMMARY_LOCATOR, ensure_debate_summary
from .run_models import RunSnapshot, RunSummary, utc_timestamp, validate_run_id
from .store import RunNotFound, RunStore, RunStoreCorruption, RunStoreError

SCHEMA_VERSION = 1
VIEW_CACHE_VERSION = 3
RUN_VIEW_LOCATOR = "projections/run-view-v1.json"
READER_BRIEF_LOCATOR = "projections/reader-brief-v1.json"
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})
RECENT_ELIGIBLE_STATUSES = frozenset(
    {"created", "running", "cancel_requested", "completed", "failed", "cancelled", "interrupted"}
)


class ProjectionError(RuntimeError):
    """A deterministic projection could not be read or rebuilt."""


class InvalidCursor(ProjectionError):
    pass


def run_summary_v1(snapshot: RunSnapshot, *, data_quality_level: str) -> dict[str, Any]:
    duration_ms = _duration_ms(snapshot)
    return {
        "run_id": snapshot.run_id,
        "ticker": snapshot.ticker,
        "status": snapshot.status,
        "mode": snapshot.mode or "company_research",
        "horizon": snapshot.horizon or "medium",
        "created_at": snapshot.created_at,
        "completed_at": snapshot.completed_at,
        "latest_sequence": snapshot.latest_sequence,
        "final_signal": snapshot.final_signal,
        "error_category": snapshot.error_category,
        "error_message": snapshot.error_message,
        "duration_ms": duration_ms,
        "data_quality_level": data_quality_level,
    }


def data_quality_v1(snapshot: RunSnapshot) -> dict[str, Any]:
    degraded = list(snapshot.degraded_data_sources)
    unavailable = list(dict.fromkeys(
        str(item.get("capability"))
        for item in degraded
        if isinstance(item, Mapping) and item.get("status") == "unavailable"
    ))
    degraded_capabilities = list(dict.fromkeys(
        str(item.get("capability"))
        for item in degraded
        if isinstance(item, Mapping) and item.get("status") == "degraded"
    ))
    level = "limited" if unavailable or degraded_capabilities else "unknown"
    return {
        "level": level,
        "degraded_capabilities": degraded_capabilities,
        "unavailable_capabilities": unavailable,
        "conflicts": [],
        "checks": [],
    }


def build_workflow(events: Iterable[PersistedEvent]) -> dict[str, Any]:
    actor_status = {role.actor_id: "waiting" for role in ROLE_REGISTRY}
    latest_turn: dict[str, str | None] = {role.actor_id: None for role in ROLE_REGISTRY}
    completed_turns: Counter[str] = Counter()
    for event in events:
        if event.type == "role.status_changed" and event.actor_id in actor_status:
            status = event.payload.get("new_status")
            if isinstance(status, str):
                actor_status[event.actor_id] = _workflow_status(status)
            turn_id = event.payload.get("turn_id")
            if isinstance(turn_id, str):
                latest_turn[event.actor_id] = turn_id
        elif event.type == "turn.completed" and event.actor_id in actor_status:
            completed_turns[event.actor_id] += 1
            turn_id = event.payload.get("turn_id")
            if isinstance(turn_id, str):
                latest_turn[event.actor_id] = turn_id

    stages = (
        ("analysts", ("analyst.market", "analyst.sentiment", "analyst.news", "analyst.fundamentals")),
        ("evidence", ("evidence.steward",)),
        ("research", ("researcher.bull", "researcher.bear", "manager.research")),
        ("trading", ("trader",)),
        ("risk", ("risk.aggressive", "risk.neutral", "risk.conservative")),
        ("portfolio", ("manager.portfolio",)),
    )
    rendered_stages: list[dict[str, Any]] = []
    active_actor_id: str | None = None
    completed_roles = 0
    for stage_id, actors in stages:
        values = [actor_status[actor] for actor in actors]
        if "running" in values:
            stage_status = "running"
            active_actor_id = active_actor_id or actors[values.index("running")]
        elif "failed" in values:
            stage_status = "failed"
        elif "cancelled" in values:
            stage_status = "cancelled"
        elif "interrupted" in values:
            stage_status = "interrupted"
        elif all(value in {"completed", "skipped"} for value in values):
            stage_status = "completed"
        else:
            stage_status = "waiting"
        completed_roles += sum(value in {"completed", "skipped"} for value in values)
        rendered_stages.append(
            {
                "stage_id": stage_id,
                "status": stage_status,
                "actors": [
                    {
                        "actor_id": actor,
                        "status": actor_status[actor],
                        "latest_turn_id": latest_turn[actor],
                        "completed_turns": completed_turns[actor],
                    }
                    for actor in actors
                ],
            }
        )
    return {
        "total_roles": len(ROLE_REGISTRY),
        "completed_roles": completed_roles,
        "active_actor_id": active_actor_id,
        "stages": rendered_stages,
    }


def build_debate_journey(
    workflow: Mapping[str, Any],
    events: Iterable[PersistedEvent],
    reader_brief: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Six-stage reading skeleton over committed facts.

    Stage statuses come from the workflow projection; actual debate round
    counts are measured from turn.completed events (not from the requested
    max-debate-rounds config, which may not have been reached). The global
    insight block only surfaces real typed outputs — never estimated
    conviction numbers, which belong to the summary artifact.
    """
    completed_turns: Counter[str] = Counter()
    for event in events:
        if event.type == "turn.completed" and event.actor_id:
            completed_turns[event.actor_id] += 1

    research_rounds = max(
        completed_turns.get("researcher.bull", 0),
        completed_turns.get("researcher.bear", 0),
    )
    risk_rounds = max(
        completed_turns.get("risk.aggressive", 0),
        completed_turns.get("risk.neutral", 0),
        completed_turns.get("risk.conservative", 0),
    )
    round_counts = {"research": research_rounds, "risk": risk_rounds}

    stages: list[dict[str, Any]] = []
    for stage in workflow.get("stages", []):
        stage_id = stage.get("stage_id")
        stages.append(
            {
                "stage_id": stage_id,
                "status": stage.get("status"),
                "rounds": round_counts.get(stage_id),
            }
        )

    brief = reader_brief or {}
    risk_consensus = brief.get("risk_consensus") or {}
    debate_digest = brief.get("debate_digest") or {}
    return {
        "stages": stages,
        "research_rating": brief.get("research_rating"),
        "disagreement_count": len(debate_digest.get("key_disagreements") or []),
        "risk_consensus": {
            "conviction": risk_consensus.get("conviction"),
            "disagreement": risk_consensus.get("disagreement", "unavailable"),
            "abstained_roles": list(risk_consensus.get("abstained_roles") or []),
        },
    }


def build_run_view(store: RunStore, run_id: str) -> dict[str, Any]:
    """Build a lightweight view without parsing any Markdown report body."""
    snapshot = store.read_snapshot(run_id)
    events = store.read_events(run_id, through=snapshot.latest_sequence)
    quality = data_quality_v1(snapshot)
    artifacts = _artifact_index(events)
    complete_report = next(
        (
            artifact_id
            for artifact_id, payload in artifacts.items()
            if payload.get("locator") == "reports/complete_report.md"
        ),
        snapshot.final_report_artifact_id,
    )
    reader_brief = _read_current_brief(store, run_id, snapshot.latest_sequence)
    if reader_brief is None:
        reader_brief = _build_reader_brief(store, run_id, snapshot, events, quality)
    status = "ready" if reader_brief is not None else "legacy_fallback"
    if snapshot.status not in TERMINAL_STATUSES and reader_brief is None:
        status = "partial"
    workflow = build_workflow(events)
    debate_journey = build_debate_journey(workflow, events, reader_brief)
    debate_summary = _read_debate_summary(store, run_id, snapshot)
    return {
        "schema_version": SCHEMA_VERSION,
        "projection_cache_version": VIEW_CACHE_VERSION,
        "projection_status": status,
        "reason_code": "legacy_no_typed_outputs" if reader_brief is None else None,
        "source_sequence": snapshot.latest_sequence,
        "terminal": snapshot.status in TERMINAL_STATUSES,
        "view": {
            "run": run_summary_v1(snapshot, data_quality_level=quality["level"]),
            "brief": {
                "availability": reader_brief.get("availability") if reader_brief else "unavailable",
                "reason_code": None if reader_brief else "legacy_no_typed_outputs",
                "value": reader_brief,
            },
            "workflow": workflow,
            "debate_journey": debate_journey,
            "debate_summary": debate_summary,
            "section_index": _section_index(events, complete_report),
            "data_quality": quality,
            "available_audit_counts": _audit_counts(events),
            "legacy_fallback": (
                {
                    "final_signal": snapshot.final_signal,
                    "portfolio_artifact_id": _latest_report_artifact(events, "portfolio"),
                    "complete_report_artifact_id": complete_report,
                }
                if reader_brief is None
                else None
            ),
        },
    }


class RunProjectionPublisher:
    """The sole writer for deterministic ReaderBrief and RunView caches."""

    def __init__(self, store: RunStore):
        self.store = store

    def publish_view(self, run_id: str) -> dict[str, Any]:
        with self.store.lock_for(run_id):
            snapshot = self.store.read_snapshot(run_id)
            events = self.store.read_events(run_id, through=snapshot.latest_sequence)
            brief = _build_reader_brief(
                self.store,
                run_id,
                snapshot,
                events,
                data_quality_v1(snapshot),
            )
            if brief is not None:
                self.store.write_fixed_json(run_id, READER_BRIEF_LOCATOR, brief)
            # Non-blocking lazy summary: if a background generation is already
            # running (lock held) this returns None immediately and the cache
            # lands as "pending"; after a restart the first reader of an old
            # completed run pays the one-shot LLM cost here.
            if snapshot.status == "completed":
                ensure_debate_summary(
                    self.store, run_id, snapshot=snapshot, events=events
                )
            view = build_run_view(self.store, run_id)
            self.store.write_fixed_json(run_id, RUN_VIEW_LOCATOR, view)
            return view

    def read_or_rebuild_view(self, run_id: str) -> dict[str, Any]:
        snapshot = self.store.read_snapshot(run_id)
        try:
            cached = self.store.read_fixed_json(run_id, RUN_VIEW_LOCATOR)
            if _valid_view(cached, snapshot.latest_sequence):
                return cached
        except (RunNotFound, RunStoreCorruption):
            pass
        return self.publish_view(run_id)


def recent_runs_page(
    summaries: Iterable[RunSummary],
    *,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise ValueError("invalid_limit")
    eligible = [summary for summary in summaries if summary.status in RECENT_ELIGIBLE_STATUSES]
    eligible.sort(key=lambda item: (item.created_at, item.run_id), reverse=True)
    if cursor:
        marker = _decode_cursor(cursor)
        eligible = [
            item
            for item in eligible
            if (item.created_at, item.run_id) < (marker["created_at"], marker["run_id"])
        ]
    selected = eligible[:limit]
    next_cursor = None
    if len(eligible) > len(selected) and selected:
        tail = selected[-1]
        next_cursor = _encode_cursor(tail.created_at, tail.run_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "items": [
            {
                "run_id": item.run_id,
                "ticker": item.ticker,
                "status": item.status,
                "created_at": item.created_at,
                "completed_at": None,
                "latest_sequence": item.latest_sequence,
                "final_signal": item.final_signal,
                "error_category": item.error_category,
                "duration_ms": None,
                "data_quality_level": "unknown",
            }
            for item in selected
        ],
        "next_cursor": next_cursor,
    }


def _build_reader_brief(
    store: RunStore,
    run_id: str,
    snapshot: RunSnapshot,
    events: list[PersistedEvent],
    quality: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Build the L1 view from committed public JSON, never from report prose."""
    if snapshot.mode in {"company_research", "holding_review"}:
        return _build_learning_reader_brief(store, snapshot, events, quality)
    outputs: dict[str, Mapping[str, Any]] = {}
    risk_outputs: dict[str, Mapping[str, Any]] = {}
    for event in events:
        if event.type != "artifact.written":
            continue
        output_kind = event.payload.get("public_output_kind")
        artifact_id = event.payload.get("artifact_id")
        if output_kind not in {"research", "trader", "portfolio", "risk"} or not isinstance(artifact_id, str):
            continue
        try:
            decoded = json.loads(store.read_artifact(run_id, artifact_id).decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, RunStoreError):
            continue
        if isinstance(decoded, Mapping) and decoded.get("run_id") == run_id and decoded.get("turn_id") == event.payload.get("turn_id"):
            if output_kind == "risk":
                role = decoded.get("role")
                if isinstance(role, str):
                    risk_outputs[role] = decoded
            else:
                outputs[str(output_kind)] = decoded

    portfolio = outputs.get("portfolio")
    if portfolio is None:
        return None
    research = outputs.get("research")
    evidence_refs = _evidence_ref_index(run_id, events)
    omissions: list[str] = []
    if research is None:
        omissions.append("research_output_missing")
    if "trader" not in outputs:
        omissions.append("trader_output_missing")
    if quality.get("level") == "unknown":
        omissions.append("data_quality_unknown")

    def claims(value: object, *, limit: int | None = None) -> list[dict[str, Any]]:
        raw_items = value if isinstance(value, list) else []
        result: list[dict[str, Any]] = []
        for item in raw_items[:limit]:
            if not isinstance(item, Mapping):
                continue
            text = item.get("text")
            ref_ids = item.get("evidence_ref_ids")
            if not isinstance(text, str) or not text or not isinstance(ref_ids, list) or not ref_ids:
                continue
            refs = [ref_id for ref_id in ref_ids if isinstance(ref_id, str) and ref_id in evidence_refs]
            if len(refs) != len(ref_ids):
                continue
            claim_id = hashlib.sha256(
                json.dumps({"text": text, "evidence_ref_ids": refs}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            result.append({"claim_id": claim_id, "text": text, "evidence_ref_ids": refs})
        return result

    reader_fields = portfolio.get("reader_fields")
    executive_summary: dict[str, Any] | None = None
    catalysts: list[dict[str, Any]] = []
    invalidation_conditions: list[dict[str, Any]] = []
    if isinstance(reader_fields, Mapping):
        executive = claims([reader_fields.get("executive_summary")])
        executive_summary = executive[0] if executive else None
        catalysts = claims(reader_fields.get("catalysts"), limit=3)
        invalidation_conditions = claims(reader_fields.get("invalidation_conditions"), limit=3)
        if executive_summary is None:
            omissions.append("executive_summary_missing")
    else:
        omissions.extend(["portfolio_reader_fields_missing", "executive_summary_missing", "catalysts_missing", "invalidation_conditions_missing"])

    drivers: list[dict[str, Any]] = []
    raw_drivers = portfolio.get("top_drivers")
    if not isinstance(raw_drivers, list):
        raw_drivers = []
    for driver in raw_drivers[:5]:
        if not isinstance(driver, Mapping):
            continue
        driver_claims = claims([{"text": driver.get("label"), "evidence_ref_ids": driver.get("evidence_ref_ids")}])
        if not driver_claims:
            continue
        claim = driver_claims[0]
        claim["direction"] = driver.get("direction")
        claim["importance"] = driver.get("importance")
        drivers.append(claim)
    if raw_drivers and not drivers:
        omissions.append("driver_refs_missing")
    risks = [dict(driver) for driver in sorted(
        (driver for driver in drivers if driver.get("direction") == "risk"),
        key=lambda driver: driver.get("importance") if isinstance(driver.get("importance"), (int, float)) else 0,
        reverse=True,
    )]
    for risk in risks:
        risk.pop("direction", None)
        risk.pop("importance", None)

    analyst_cards: list[dict[str, Any]] = []
    digest = {"agreed_facts": [], "key_disagreements": [], "changed_views": [], "remaining_uncertainties": []}
    if research is not None:
        for signal in research.get("strategy_signals", []):
            if not isinstance(signal, Mapping):
                continue
            findings_raw = signal.get("key_findings")
            findings = claims(findings_raw, limit=3)
            if findings_raw is None:
                omissions.append("analyst_findings_missing")
            analyst_cards.append({
                "lens": signal.get("strategy_id"),
                "conviction": signal.get("conviction"),
                "confidence": signal.get("confidence"),
                "abstain": signal.get("abstain"),
                "findings": findings,
            })
        public_digest = research.get("public_digest")
        if isinstance(public_digest, Mapping):
            digest = {key: claims(public_digest.get(key), limit=5) for key in digest}
        else:
            omissions.append("debate_digest_missing")

    if not risk_outputs:
        omissions.append("risk_signals_missing")
    risk_signals: list[ConvictionSignal] = []
    seen_risk_roles: set[str] = set()
    for signal in risk_outputs.values():
        role = signal.get("role")
        conviction = signal.get("conviction")
        confidence = signal.get("confidence")
        abstain = signal.get("abstain")
        if role not in {"aggressive", "conservative", "neutral"} or role in seen_risk_roles:
            continue
        if not isinstance(confidence, (int, float)) or not isinstance(abstain, bool):
            continue
        if abstain:
            conviction = None
        elif not isinstance(conviction, (int, float)):
            continue
        seen_risk_roles.add(role)
        if signal.get("evidence_summary_ref") is None:
            omissions.append("risk_signal_refs_missing")
        risk_signals.append(ConvictionSignal(role=role, conviction=conviction, confidence=float(confidence), evidence_summary=str(signal.get("evidence_summary", ""))))
    if len(seen_risk_roles) < 3:
        omissions.append("risk_signals_missing")
    risk_consensus = {"conviction": None, "disagreement": "unavailable", "abstained_roles": []}
    if risk_signals:
        aggregate = aggregate_risk_convictions(risk_signals)
        risk_consensus = {
            "conviction": aggregate.conviction,
            "disagreement": aggregate.disagreement,
            "abstained_roles": list(aggregate.abstained_roles),
        }

    execution = portfolio.get("execution_outcome")
    if not isinstance(execution, Mapping):
        execution = {
            "availability": "unavailable",
            "requested_action": portfolio.get("execution_action"),
            "requested_quantity": portfolio.get("requested_quantity"),
            "effective_action": None,
            "effective_quantity": None,
            "reason_code": "typed_constraint_outcome_missing",
        }
        omissions.append("typed_constraint_outcome_missing")
    unique_omissions = list(dict.fromkeys(omissions))
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "ticker": snapshot.ticker,
        "source_sequence": snapshot.latest_sequence,
        "generated_at": utc_timestamp(),
        "availability": "full" if not unique_omissions else "partial",
        "omissions": unique_omissions,
        "research_rating": portfolio.get("rating"),
        "execution": execution,
        "executive_summary": executive_summary,
        "price_target": portfolio.get("price_target"),
        "time_horizon": portfolio.get("time_horizon"),
        "drivers": drivers,
        "risks": risks,
        "catalysts": catalysts,
        "invalidation_conditions": invalidation_conditions,
        "analyst_cards": analyst_cards,
        "debate_digest": digest,
        "risk_consensus": risk_consensus,
        "data_quality": dict(quality),
        "evidence_refs": list(evidence_refs.values()),
    }


def _build_learning_reader_brief(
    store: RunStore,
    snapshot: RunSnapshot,
    events: list[PersistedEvent],
    quality: Mapping[str, Any],
) -> dict[str, Any]:
    """Project the committed learning summary without parsing report Markdown.

    The initial learning summary is a public, validated synthesis.  It is not
    yet a full ResearchCase: the latter additionally binds every fact to an
    evidence reference.  That limitation stays visible in ``omissions``.
    """
    learning_summary = _read_learning_summary(store, snapshot, events)
    omissions = (
        ["research_case.typed_output_missing"]
        if learning_summary is None
        else ["research_case.evidence_refs_unavailable"]
    )
    holding_review = _read_learning_holding_review(store, snapshot, events)
    if snapshot.mode == "holding_review":
        if holding_review is not None:
            pass
        elif snapshot.holding_context is None:
            omissions.append("holding_review.context_missing")
        else:
            holding_review = build_holding_review_summary(
                snapshot.holding_context,
                analysis_date=snapshot.analysis_date,
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": snapshot.run_id,
        "ticker": snapshot.ticker,
        "source_sequence": snapshot.latest_sequence,
        "generated_at": utc_timestamp(),
        "availability": "partial",
        "omissions": omissions,
        "research_rating": learning_summary.get("research_tilt") if learning_summary else None,
        "execution": {
            "availability": "unavailable",
            "requested_action": None,
            "requested_quantity": None,
            "effective_action": None,
            "effective_quantity": None,
            "reason_code": "learning_mode_no_execution",
        },
        "executive_summary": None,
        "price_target": None,
        "time_horizon": snapshot.horizon or "medium",
        "drivers": [],
        "risks": [],
        "catalysts": [],
        "invalidation_conditions": [],
        "analyst_cards": [],
        "debate_digest": {
            "agreed_facts": [],
            "key_disagreements": [],
            "changed_views": [],
            "remaining_uncertainties": [],
        },
        "risk_consensus": {
            "conviction": None,
            "disagreement": "unavailable",
            "abstained_roles": [],
        },
        "data_quality": dict(quality),
        "evidence_refs": [],
        "holding_review": holding_review,
        "learning_summary": learning_summary,
    }


def _read_learning_holding_review(
    store: RunStore,
    snapshot: RunSnapshot,
    events: Iterable[PersistedEvent],
) -> dict[str, Any] | None:
    """Use a committed holding review instead of recalculating it in Reader."""
    for event in reversed(list(events)):
        if event.type != "artifact.written" or event.payload.get("public_output_kind") != "portfolio":
            continue
        artifact_id = event.payload.get("artifact_id")
        if not isinstance(artifact_id, str):
            continue
        try:
            output = json.loads(store.read_artifact(snapshot.run_id, artifact_id).decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, RunStoreError):
            continue
        review = output.get("holding_review") if isinstance(output, Mapping) and output.get("kind") == "learning_holding_review" else None
        if isinstance(review, Mapping) and review.get("mode") == "holding_review":
            return dict(review)
    return None


def _read_learning_summary(
    store: RunStore,
    snapshot: RunSnapshot,
    events: Iterable[PersistedEvent],
) -> dict[str, Any] | None:
    """Read the latest committed learning summary with a deliberately closed shape."""
    for event in reversed(list(events)):
        if event.type != "artifact.written" or event.payload.get("public_output_kind") != "research":
            continue
        artifact_id = event.payload.get("artifact_id")
        if not isinstance(artifact_id, str):
            continue
        try:
            output = json.loads(store.read_artifact(snapshot.run_id, artifact_id).decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, RunStoreError):
            continue
        if not isinstance(output, Mapping) or output.get("run_id") != snapshot.run_id:
            continue
        if output.get("kind") != "learning_research_summary":
            continue
        summary = output.get("summary")
        if not isinstance(summary, Mapping) or not _valid_learning_summary(summary):
            continue
        return dict(summary)
    return None


def _valid_learning_summary(value: Mapping[str, Any]) -> bool:
    """Keep malformed public artifacts out of Reader without hidden coercion."""
    if value.get("research_tilt") not in {"favorable", "neutral", "cautious", "insufficient_evidence"}:
        return False
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        return False
    text_lists = ("facts", "inferences", "unknowns", "catalysts", "invalidation_conditions")
    if any(
        not isinstance(value.get(field), list)
        or any(not isinstance(item, str) or not item for item in value[field])
        for field in text_lists
    ):
        return False
    for field in ("upside", "base", "downside"):
        scenario = value.get(field)
        if not isinstance(scenario, Mapping) or any(
            not isinstance(scenario.get(key), str) or not scenario[key]
            for key in ("title", "condition", "implication")
        ):
            return False
    assessment = value.get("holding_thesis_assessment")
    if assessment is not None and (
        not isinstance(assessment, Mapping)
        or assessment.get("status") not in {"supported", "challenged", "not_assessable"}
        or any(
            not isinstance(assessment.get(field), str) or not assessment[field]
            for field in ("rationale", "current_research_hypothesis")
        )
    ):
        return False
    return isinstance(value.get("next_review"), str) and bool(value["next_review"])


def _evidence_ref_index(run_id: str, events: Iterable[PersistedEvent]) -> dict[str, dict[str, Any]]:
    """Create browser-safe artifact references from committed event metadata only."""
    refs: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.type != "artifact.written":
            continue
        artifact_id = event.payload.get("artifact_id")
        if not isinstance(artifact_id, str):
            continue
        target = {"kind": "artifact", "artifact_id": artifact_id}
        ref_id = hashlib.sha256(
            json.dumps(target, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        refs[ref_id] = {
            "ref_id": ref_id,
            "run_id": run_id,
            "label": str(event.payload.get("kind") or "artifact"),
            "target": target,
            "resolution_status": "available",
        }
    return refs


def _read_current_brief(store: RunStore, run_id: str, source_sequence: int) -> dict[str, Any] | None:
    try:
        brief = store.read_fixed_json(run_id, READER_BRIEF_LOCATOR)
    except (RunNotFound, RunStoreCorruption):
        return None
    if brief.get("schema_version") != SCHEMA_VERSION or brief.get("source_sequence") != source_sequence:
        return None
    return brief


def _read_debate_summary(store: RunStore, run_id: str, snapshot: RunSnapshot) -> dict[str, Any]:
    """Read a committed summary projection without ever invoking an LLM.

    Generation happens in a background thread scheduled after run.completed,
    or lazily via RunProjectionPublisher.publish_view when a completed run's
    summary cache is missing (e.g. service restarted). The read path itself
    stays a pure file read.
    """
    if snapshot.status != "completed":
        return {"availability": "unavailable", "reason_code": "run_not_completed", "value": None}
    try:
        value = store.read_fixed_json(run_id, DEBATE_SUMMARY_LOCATOR)
    except (RunNotFound, RunStoreCorruption):
        value = None
    if value:
        return {"availability": "ready", "reason_code": None, "value": value}
    return {"availability": "pending", "reason_code": "summary_not_generated", "value": None}


def _artifact_index(events: Iterable[PersistedEvent]) -> dict[str, Mapping[str, Any]]:
    artifacts: dict[str, Mapping[str, Any]] = {}
    for event in events:
        if event.type != "artifact.written":
            continue
        artifact_id = event.payload.get("artifact_id")
        if isinstance(artifact_id, str):
            artifacts.setdefault(artifact_id, event.payload)
    return artifacts


def _section_index(events: list[PersistedEvent], complete_report: str | None) -> list[dict[str, Any]]:
    sections: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.type != "report.updated":
            continue
        report_kind = event.payload.get("report_kind")
        artifact_id = event.payload.get("artifact_id")
        turn_id = event.payload.get("turn_id")
        if not isinstance(report_kind, str) or not isinstance(artifact_id, str):
            continue
        section = _section_for_report(report_kind)
        current = sections.setdefault(
            section,
            {"section_id": section, "label": _section_label(section), "availability": "ready", "artifact_ids": [], "turn_ids": []},
        )
        current["artifact_ids"].append(artifact_id)
        if isinstance(turn_id, str):
            current["turn_ids"].append(turn_id)
    if complete_report:
        sections["complete_report"] = {
            "section_id": "complete_report",
            "label": "完整审计报告",
            "availability": "ready",
            "artifact_ids": [complete_report],
            "turn_ids": [],
        }
    return list(sections.values())


def _audit_counts(events: Iterable[PersistedEvent]) -> dict[str, int]:
    counts = {"turns": 0, "prompts": 0, "tool_calls": 0, "data_calls": 0, "artifacts": 0, "reports": 0}
    seen_turns: set[str] = set()
    for event in events:
        if event.type == "turn.started":
            turn_id = event.payload.get("turn_id")
            if isinstance(turn_id, str):
                seen_turns.add(turn_id)
        elif event.type == "artifact.written":
            counts["artifacts"] += 1
            kind = event.payload.get("kind")
            if kind == "prompt":
                counts["prompts"] += 1
        elif event.type == "tool.requested":
            counts["tool_calls"] += 1
        elif event.type.startswith("data."):
            counts["data_calls"] += 1
        elif event.type == "report.updated":
            counts["reports"] += 1
    counts["turns"] = len(seen_turns)
    return counts


def _latest_report_artifact(events: Iterable[PersistedEvent], report_kind: str) -> str | None:
    for event in reversed(list(events)):
        if event.type == "report.updated" and event.payload.get("report_kind") == report_kind:
            artifact_id = event.payload.get("artifact_id")
            return artifact_id if isinstance(artifact_id, str) else None
    return None


def _workflow_status(value: str) -> str:
    return {
        "pending": "waiting",
        "skipped": "skipped",
        "completed": "completed",
        "running": "running",
        "failed": "failed",
        "cancelled": "cancelled",
        "interrupted": "interrupted",
    }.get(value, "waiting")


def _section_for_report(report_kind: str) -> str:
    return {
        "market": "market",
        "fundamentals": "fundamentals",
        "news": "news",
        "sentiment": "sentiment",
        "trader": "trading",
        "portfolio": "portfolio",
    }.get(report_kind, "audit")


def _section_label(section_id: str) -> str:
    return {
        "market": "市场与技术",
        "fundamentals": "基本面",
        "news": "新闻与事件",
        "sentiment": "情绪与资金",
        "trading": "交易计划",
        "portfolio": "组合决策",
        "audit": "审计记录",
    }.get(section_id, section_id)


def _duration_ms(snapshot: RunSnapshot) -> int | None:
    if snapshot.completed_at is None:
        return None
    try:
        started = datetime.fromisoformat(snapshot.created_at.replace("Z", "+00:00"))
        ended = datetime.fromisoformat(snapshot.completed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, round((ended - started).total_seconds() * 1000))


def _valid_view(value: Mapping[str, Any], source_sequence: int) -> bool:
    return (
        value.get("schema_version") == SCHEMA_VERSION
        and value.get("projection_cache_version") == VIEW_CACHE_VERSION
        and value.get("source_sequence") == source_sequence
        and isinstance(value.get("view"), Mapping)
    )


def _encode_cursor(created_at: str, run_id: str) -> str:
    payload = f"v1|recent|{created_at}|{run_id}".encode()
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> dict[str, str]:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")
        version, view, created_at, run_id = decoded.split("|", 3)
        if version != "v1" or view != "recent":
            raise ValueError
        validate_run_id(run_id)
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception as exc:
        raise InvalidCursor("invalid_cursor") from exc
    return {"created_at": created_at, "run_id": run_id}
