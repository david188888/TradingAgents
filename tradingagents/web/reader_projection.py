"""Pure-function projection of a run into the read-only learning reader.

``project_reader`` is deterministic and side-effect free: it reads persisted run
facts from the store, chooses a reader family (typed / legacy / unavailable),
and returns a plain dict (``model_dump(mode="json")``).  It never calls an LLM,
never touches the network, and never writes files.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import cast

from tradingagents.agents.schemas._research_case import ResearchCaseV2
from tradingagents.research.valuation import ValuationAssessmentV1
from tradingagents.runtime.store import RunStore

from .reader_models import (
    AuditEntryDTO,
    CompanionDTO,
    CompanionSelection,
    LearningReaderV2,
    LegacyDataQualityDTO,
    LegacyReaderV1,
    ReaderEvidenceRef,
    ReaderUnavailableV1,
    ResearchMode,
    ThesisDiffDTO,
)

logger = logging.getLogger(__name__)

_TYPED_MODES = frozenset({"company_research", "holding_review"})
_RESEARCH_CASE_CONTRACT = "research-case-v2"
_RESEARCH_PACKAGE_CONTRACT = "research-package-v1"
_VALUATION_CONTRACT = "valuation-assessment-v1"

_IMPACT_LABELS = {
    "supports": "支持当前研究结论",
    "opposes": "对当前研究结论形成反向约束",
    "limits": "限制当前结论的适用范围或置信度",
    "neutral": "暂不改变当前研究结论",
}


class ResearchPackageNotFound(LookupError):
    """The public research package is not available for the current run."""


class CompanionNotFound(LookupError):
    """The requested public selection is not available in the current run."""


def project_reader(store: RunStore, run_id: str) -> dict:
    """Project a run into a reader dict (one of the three reader kinds)."""
    # RunNotFound propagates to the API layer, which maps it to 404.
    snapshot = store.read_snapshot(run_id)
    events = store.read_events(run_id)
    audit = _audit_entry(events)

    if snapshot.mode in _TYPED_MODES:
        case_ref = _latest_research_case(events)
        if case_ref is None:
            model = ReaderUnavailableV1(
                run_id=run_id,
                ticker=snapshot.ticker,
                reason_code="research_case_unavailable",
                audit_entry=audit,
            )
            return model.model_dump(mode="json")
        try:
            raw = store.read_artifact(run_id, case_ref)
            payload = json.loads(raw)
            case = ResearchCaseV2.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - projection must not raise
            logger.warning("reader projection failed for run %s: %s", run_id, exc)
            model = ReaderUnavailableV1(
                run_id=run_id,
                ticker=snapshot.ticker,
                reason_code="reader_projection_failed",
                audit_entry=audit,
            )
            return model.model_dump(mode="json")
        model = _project_typed(
            snapshot.mode,
            case,
            audit,
            _load_thesis_diff(store, run_id, events),
            _load_valuation(store, run_id, events),
        )
        return model.model_dump(mode="json")

    model = _project_legacy(snapshot.run_id, snapshot.ticker, snapshot.analysis_date, snapshot.final_signal, audit)
    return model.model_dump(mode="json")


def _latest_research_package(events) -> str | None:
    """Return the highest committed research-package-v1 artifact."""
    best: tuple[int, str] | None = None
    for event in events:
        if event.type != "artifact.written":
            continue
        payload = event.payload
        if payload.get("public_contract") != _RESEARCH_PACKAGE_CONTRACT:
            continue
        sequence = payload.get("committed_sequence")
        artifact_id = payload.get("artifact_id")
        if isinstance(sequence, int) and isinstance(artifact_id, str) and (
            best is None or sequence > best[0]
        ):
            best = (sequence, artifact_id)
    return best[1] if best is not None else None


def project_research_package(store: RunStore, run_id: str) -> dict:
    """Return the validated package without provider or model calls."""
    from tradingagents.research.research_package import ResearchPackageV1

    snapshot = store.read_snapshot(run_id)
    artifact_id = _latest_research_package(store.read_events(run_id))
    if artifact_id is None:
        raise ResearchPackageNotFound(run_id)
    try:
        package = ResearchPackageV1.model_validate_json(store.read_artifact(run_id, artifact_id))
    except Exception as exc:  # noqa: BLE001 - stable public 404 boundary
        raise ResearchPackageNotFound(run_id) from exc
    if package.run_id != run_id or package.ticker != snapshot.ticker:
        raise ResearchPackageNotFound(run_id)
    return package.model_dump(mode="json")


def _latest_research_case(events) -> str | None:
    """Return the artifact_id of the highest committed_sequence research-case-v2."""
    best: tuple[int, str] | None = None
    for event in events:
        if event.type != "artifact.written":
            continue
        payload = event.payload
        if payload.get("public_contract") != _RESEARCH_CASE_CONTRACT:
            continue
        sequence = payload.get("committed_sequence")
        artifact_id = payload.get("artifact_id")
        if not isinstance(sequence, int) or not isinstance(artifact_id, str):
            continue
        if best is None or sequence > best[0]:
            best = (sequence, artifact_id)
    return best[1] if best is not None else None


def _audit_entry(events) -> AuditEntryDTO:
    artifact_count = 0
    tool_call_count = 0
    degradation_count = 0
    for event in events:
        if event.type == "artifact.written":
            artifact_count += 1
        elif event.type == "tool.committed":
            tool_call_count += 1
        elif event.type.startswith("degradation"):
            degradation_count += 1
    return AuditEntryDTO(
        route="reader",
        artifact_count=artifact_count,
        tool_call_count=tool_call_count,
        degradation_count=degradation_count,
    )


def _load_thesis_diff(store, run_id: str, events) -> dict | None:
    """Return the highest-sequence thesis-diff-v1 artifact, if any."""
    best: tuple[int, str] | None = None
    for event in events:
        if event.type != "artifact.written":
            continue
        payload = event.payload
        if payload.get("public_contract") != "thesis-diff-v1":
            continue
        sequence = payload.get("committed_sequence")
        artifact_id = payload.get("artifact_id")
        if (
            isinstance(sequence, int)
            and isinstance(artifact_id, str)
            and (best is None or sequence > best[0])
        ):
            best = (sequence, artifact_id)
    if best is None:
        return None
    try:
        raw = store.read_artifact(run_id, best[1])
        value = json.loads(raw)
        if not isinstance(value, dict):
            return None
        public_value = {
            key: item
            for key, item in value.items()
            if key
            not in {
                "current_research_case_artifact_id",
                "previous_research_case_artifact_id",
            }
        }
        return ThesisDiffDTO.model_validate(public_value)
    except Exception as exc:  # noqa: BLE001 - reader stays available without diff
        logger.warning("failed to read thesis diff %s: %s", best[1], exc)
        return None


def _load_valuation(store, run_id: str, events) -> ValuationAssessmentV1 | None:
    """Return the highest-sequence valuation-assessment artifact, if any."""
    best: tuple[int, str] | None = None
    for event in events:
        if event.type != "artifact.written":
            continue
        payload = event.payload
        if payload.get("public_contract") != _VALUATION_CONTRACT:
            continue
        sequence = payload.get("committed_sequence")
        artifact_id = payload.get("artifact_id")
        if (
            isinstance(sequence, int)
            and isinstance(artifact_id, str)
            and (best is None or sequence > best[0])
        ):
            best = (sequence, artifact_id)
    if best is None:
        return None
    try:
        raw = store.read_artifact(run_id, best[1])
        return ValuationAssessmentV1.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001 - reader stays available without valuation
        logger.warning("failed to read valuation assessment %s: %s", best[1], exc)
        return None


def _project_typed(
    mode: str,
    case: ResearchCaseV2,
    audit: AuditEntryDTO,
    thesis_diff: ThesisDiffDTO | None,
    valuation: ValuationAssessmentV1 | None,
) -> LearningReaderV2:
    evidence_refs = tuple(
        ReaderEvidenceRef(
            ref_id=ref.ref_id,
            source_label=_source_label(ref.artifact_id),
            resolution_status="available",
        )
        for ref in case.evidence_refs
        if ref.resolution_status == "available"
    )
    return LearningReaderV2(
        run_id=case.run_id,
        mode=cast(ResearchMode, mode),
        ticker=case.ticker,
        horizon=case.horizon,
        as_of=case.as_of,
        availability=case.availability,
        decision_eligibility=case.decision_eligibility,
        evidence_verdict=case.evidence_verdict,
        research_tilt=case.research_rating,
        rating_confidence=case.rating_confidence,
        claims=case.claims,
        scenarios=case.scenarios,
        catalysts=case.catalysts,
        invalidation_conditions=case.invalidation_conditions,
        review_plan=case.review_plan,
        analyst_cards=case.analyst_cards,
        data_quality=case.data_quality,
        evidence_refs=evidence_refs,
        coverage_refs=case.coverage_refs,
        omissions=case.omissions,
        thesis_diff=thesis_diff,
        valuation=valuation,
        audit_entry=audit,
    )


def _project_legacy(
    run_id: str,
    ticker: str,
    analysis_date: str,
    final_signal: str | None,
    audit: AuditEntryDTO,
) -> LegacyReaderV1:
    return LegacyReaderV1(
        run_id=run_id,
        ticker=ticker,
        as_of=_legacy_as_of(analysis_date),
        final_signal=final_signal,
        portfolio_report_markdown=None,
        data_quality=LegacyDataQualityDTO(
            level="unknown",
            summary="Legacy run without typed data quality.",
            degradation_count=0,
        ),
        stage_refs=(),
        audit_entry=audit,
        reason_codes=("legacy_run", "legacy_markdown_not_projected"),
    )


def _source_label(artifact_id: str) -> str:
    """Derive a human-friendly source label without leaking locator/hashes."""
    if ":" in artifact_id:
        return artifact_id.split(":", 1)[0]
    return artifact_id


def project_companion(
    store: RunStore,
    run_id: str,
    selection: CompanionSelection,
) -> dict:
    """Project one current-run public Reader entity into a bounded companion."""
    snapshot = store.read_snapshot(run_id)
    if snapshot.mode not in _TYPED_MODES:
        raise CompanionNotFound(selection.id)
    events = store.read_events(run_id)
    case_ref = _latest_research_case(events)
    if case_ref is None:
        raise CompanionNotFound(selection.id)
    try:
        case = ResearchCaseV2.model_validate_json(store.read_artifact(run_id, case_ref))
    except Exception as exc:  # noqa: BLE001 - public 404 hides storage details
        raise CompanionNotFound(selection.id) from exc
    if case.run_id != run_id:
        raise CompanionNotFound(selection.id)

    resolver = {
        "role": _companion_for_role,
        "claim": _companion_for_claim,
        "evidence": _companion_for_evidence,
        "risk": _companion_for_risk,
    }[selection.kind]
    companion = resolver(case, selection)
    return companion.model_dump(mode="json")


def _companion_for_role(
    case: ResearchCaseV2,
    selection: CompanionSelection,
) -> CompanionDTO:
    card = next((item for item in case.analyst_cards if item.lens == selection.id), None)
    if card is None:
        raise CompanionNotFound(selection.id)
    coverage = tuple(
        f"{status.capability}：{status.status}"
        for status in card.capability_statuses
    ) or (f"视角可用性：{card.availability}",)
    claim_index = {claim.claim_key: claim for claim in case.claims}
    impacts = tuple(
        dict.fromkeys(
            _IMPACT_LABELS[claim_index[key].action_impact]
            for key in card.finding_claim_keys
            if key in claim_index
        )
    )
    limited = tuple(
        status.capability
        for status in card.capability_statuses
        if status.status != "ok"
    )
    next_validation = (
        f"补齐或复核受限能力：{'、'.join(limited)}。"
        if limited
        else "在下一次同周期研究中复核该视角的覆盖与结论。"
    )
    return CompanionDTO(
        run_id=case.run_id,
        selection=selection,
        summary=card.summary,
        actual_coverage=coverage,
        conclusion_impact="；".join(impacts) if impacts else "未绑定可改变结论的公开论点。",
        next_validation=next_validation,
    )


def _companion_for_claim(
    case: ResearchCaseV2,
    selection: CompanionSelection,
) -> CompanionDTO:
    claim = next((item for item in case.claims if item.claim_key == selection.id), None)
    if claim is None:
        raise CompanionNotFound(selection.id)
    evidence_index = {ref.ref_id: ref for ref in case.evidence_refs}
    coverage_index = {ref.coverage_ref_id: ref for ref in case.coverage_refs}
    coverage = tuple(
        dict.fromkeys(
            (
                *(
                    f"来源：{_source_label(evidence_index[ref_id].artifact_id)}"
                    for ref_id in claim.evidence_ref_ids
                    if ref_id in evidence_index
                    and evidence_index[ref_id].resolution_status == "available"
                ),
                *(
                    f"{coverage_index[ref_id].capability}：{coverage_index[ref_id].envelope.bundle_completeness}"
                    for ref_id in claim.coverage_ref_ids
                    if ref_id in coverage_index
                ),
            )
        )
    ) or ("当前没有可公开展示的证据覆盖。",)
    next_validation = _claim_next_validation(case, claim.claim_key)
    if claim.claim_type == "unknown":
        required = "、".join(claim.required_evidence)
        next_validation = f"{claim.review_trigger}；需要：{required}。"
    return CompanionDTO(
        run_id=case.run_id,
        selection=selection,
        summary=claim.text,
        actual_coverage=coverage,
        conclusion_impact=_IMPACT_LABELS[claim.action_impact],
        next_validation=next_validation,
    )


def _companion_for_evidence(
    case: ResearchCaseV2,
    selection: CompanionSelection,
) -> CompanionDTO:
    reference = next(
        (
            item
            for item in case.evidence_refs
            if item.ref_id == selection.id
            and item.run_id == case.run_id
            and item.resolution_status == "available"
        ),
        None,
    )
    if reference is None:
        raise CompanionNotFound(selection.id)
    linked_claims = tuple(
        claim for claim in case.claims if reference.ref_id in claim.evidence_ref_ids
    )
    observed = reference.source_observed_at or reference.captured_at
    impact_labels = tuple(
        dict.fromkeys(_IMPACT_LABELS[claim.action_impact] for claim in linked_claims)
    )
    review_items = tuple(
        item
        for item in (*case.catalysts, *case.invalidation_conditions)
        if reference.ref_id in item.evidence_ref_ids
    )
    next_validation = (
        f"按{review_items[0].trigger_kind}触发器“{review_items[0].trigger_value}”复核。"
        if review_items
        else "在下一次研究更新中检查该来源的时效与覆盖。"
    )
    return CompanionDTO(
        run_id=case.run_id,
        selection=selection,
        summary=f"公开证据来源：{_source_label(reference.artifact_id)}。",
        actual_coverage=(
            f"媒体类型：{reference.media_type}",
            f"观测截至：{observed.date().isoformat()}",
        ),
        conclusion_impact=(
            "；".join(impact_labels)
            if impact_labels
            else "尚未绑定到可改变结论的公开论点。"
        ),
        next_validation=next_validation,
    )


def _companion_for_risk(
    case: ResearchCaseV2,
    selection: CompanionSelection,
) -> CompanionDTO:
    risk = next(
        (item for item in case.invalidation_conditions if item.item_id == selection.id),
        None,
    )
    if risk is None:
        raise CompanionNotFound(selection.id)
    evidence_index = {ref.ref_id: ref for ref in case.evidence_refs}
    coverage = tuple(
        dict.fromkeys(
            f"来源：{_source_label(evidence_index[ref_id].artifact_id)}"
            for ref_id in risk.evidence_ref_ids
            if ref_id in evidence_index
            and evidence_index[ref_id].resolution_status == "available"
        )
    ) or (f"关联公开论点：{len(risk.claim_keys)} 条。",)
    return CompanionDTO(
        run_id=case.run_id,
        selection=selection,
        summary=risk.text,
        actual_coverage=coverage,
        conclusion_impact=(
            "若该失效条件被满足，关联论点需要降级或撤销；"
            f"当前状态：{risk.status}。"
        ),
        next_validation=f"按{risk.trigger_kind}触发器“{risk.trigger_value}”复核。",
    )


def _claim_next_validation(case: ResearchCaseV2, claim_key: str) -> str:
    review = next(
        (
            item
            for item in (*case.catalysts, *case.invalidation_conditions)
            if claim_key in item.claim_keys
        ),
        None,
    )
    if review is None:
        return "在下一次同周期研究中复核该论点。"
    return f"按{review.trigger_kind}触发器“{review.trigger_value}”复核。"


def _legacy_as_of(analysis_date: str) -> datetime:
    """Best-effort research date for a legacy run; never crashes."""
    try:
        return datetime.fromisoformat(analysis_date).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
