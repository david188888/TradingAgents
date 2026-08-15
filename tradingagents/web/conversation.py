"""Deterministic, public-only responder for research-package conversations."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from tradingagents.research.conversation_models import (
    ConversationAnchorV1,
    ConversationMessageV1,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _contains(question: str, *values: str) -> bool:
    folded = question.casefold()
    return any(value and value.casefold() in folded for value in values)


def _number(value: float) -> str:
    return f"{value:g}"


def _requested_period(question: str) -> str | None:
    match = re.search(r"(?:20\d{2})(?:[-/]\d{2}[-/]\d{2})?", question)
    if match:
        return match.group(0).replace("/", "-")
    year = re.search(r"(20\d{2})年", question)
    return year.group(1) if year else None


def answer_from_package(
    package: dict[str, Any],
    *,
    sequence: int,
    question: str,
    request_id: str | None = None,
) -> ConversationMessageV1:
    """Answer only from the validated public package projection."""
    definitions = package.get("metric_definitions") or ()
    observations = package.get("observations") or ()
    comparisons = package.get("comparisons") or ()
    edges = package.get("logic_edges") or ()
    unknowns = tuple(str(item) for item in (package.get("unknowns") or ())[:8])
    definition_question = _contains(
        question,
        "口径",
        "定义",
        "是什么",
        "怎么计算",
        "公式",
        "含义",
        "解释",
        "definition",
        "formula",
        "meaning",
    )

    candidates: list[dict[str, Any]] = []
    folded_question = question.casefold()
    for definition in definitions:
        metric_id = str(definition.get("metric_id") or "")
        labels = (
            metric_id,
            str(definition.get("label_zh") or ""),
            str(definition.get("label_en") or ""),
        )
        matched_length = max(
            (len(value) for value in labels if value and value.casefold() in folded_question),
            default=0,
        )
        if matched_length == 0:
            continue
        candidates.append((definition, matched_length))
    candidates.sort(key=lambda item: item[1], reverse=True)
    for definition, _match_length in candidates:
        metric_id = str(definition.get("metric_id") or "")
        if definition_question:
            answer = (
                f"{definition.get('label_zh') or metric_id}（{metric_id}）的公开口径是："
                f"{definition.get('plain_explanation') or '研究包未提供解释'}。"
                f"计算式：{definition.get('formula_text') or '研究包未提供公式'}。"
            )
            if definition.get("pitfalls"):
                answer += " 注意：" + "；".join(str(item) for item in definition["pitfalls"][:3]) + "。"
            return ConversationMessageV1(
                sequence=sequence,
                created_at=_now(),
                question=question,
                answer=answer,
                availability="ready",
                anchors=(ConversationAnchorV1(kind="metric", anchor_id=metric_id),),
                request_id=request_id,
            )

        matching = [item for item in observations if item.get("metric_id") == metric_id]
        requested_period = _requested_period(question)
        if requested_period is not None:
            matching = [
                item
                for item in matching
                if str(item.get("period") or "").startswith(requested_period)
            ]
            if len(matching) != 1:
                return _unavailable(
                    sequence,
                    question,
                    request_id,
                    f"研究包没有提供 {metric_id} 在 {requested_period} 的唯一可验证观测；availability=unavailable，needs_evidence。",
                    (ConversationAnchorV1(kind="metric", anchor_id=metric_id),),
                    unknowns,
                )
        if not matching:
            return _unavailable(
                sequence,
                question,
                request_id,
                f"研究包没有提供 {metric_id} 的可验证观测值；availability=unavailable，needs_evidence。",
                (ConversationAnchorV1(kind="metric", anchor_id=metric_id),),
                unknowns,
            )
        observation = sorted(matching, key=lambda item: str(item.get("period") or ""))[-1]
        observation_id = str(observation.get("observation_id") or metric_id)
        refs = tuple(str(item) for item in (observation.get("source_evidence_ref_ids") or ()))
        anchor_ids = (
            ConversationAnchorV1(kind="metric", anchor_id=metric_id),
            ConversationAnchorV1(kind="observation", anchor_id=observation_id),
        )
        if observation.get("availability") != "available" or observation.get("value") is None:
            reason = str(observation.get("unavailable_reason") or "公开观测不可用")
            return _unavailable(
                sequence,
                question,
                request_id,
                f"{metric_id} 当前不能从研究包给出数值：{reason}；availability=unavailable，needs_evidence。",
                anchor_ids,
                refs,
            )
        value = _number(float(observation["value"]))
        answer = (
            f"研究包记录 {metric_id} 在报告期 {observation.get('period')} 的值为 "
            f"{value} {observation.get('unit')}（as_of={observation.get('as_of')}）。"
        )
        return ConversationMessageV1(
            sequence=sequence,
            created_at=_now(),
            question=question,
            answer=answer,
            availability="ready",
            anchors=anchor_ids,
            evidence_ref_ids=refs,
            request_id=request_id,
        )

    for comparison in comparisons:
        comparison_id = str(comparison.get("comparison_id") or "")
        metric_id = str(comparison.get("metric_id") or "")
        if not _contains(question, comparison_id, metric_id, "同行", "peer", "比较"):
            continue
        peer_set_id = str(comparison.get("peer_set_id") or "")
        peer_set = next(
            (item for item in package.get("peer_sets") or () if item.get("peer_set_id") == peer_set_id),
            None,
        )
        anchors = [ConversationAnchorV1(kind="comparison", anchor_id=comparison_id)]
        if peer_set is not None:
            anchors.append(ConversationAnchorV1(kind="peer_set", anchor_id=peer_set_id))
        refs = tuple(str(item) for item in ((peer_set or {}).get("source_evidence_ref_ids") or ()))
        if comparison.get("availability") == "available" and peer_set is None:
            return _unavailable(
                sequence,
                question,
                request_id,
                "同行比较缺少可验证的 peer set；availability=unavailable，needs_evidence。",
                tuple(anchors),
                unknowns,
            )
        if comparison.get("availability") == "available":
            answer = (
                f"研究包记录 {metric_id} 的同行比较：目标值 {comparison.get('target_value')} "
                f"{comparison.get('unit')}，同行中位数 {comparison.get('peer_median')} "
                f"{comparison.get('unit')}，样本数 {comparison.get('sample_size')}。"
            )
            availability = "ready"
            refusal = None
        else:
            answer = "该同行比较在研究包中不可用；availability=unavailable，needs_evidence。"
            availability = "unavailable"
            refusal = str(comparison.get("unavailable_reason") or "同行比较缺少可验证证据")
        return ConversationMessageV1(
            sequence=sequence,
            created_at=_now(),
            question=question,
            answer=answer,
            availability=availability,
            refusal_reason=refusal,
            anchors=tuple(anchors),
            evidence_ref_ids=refs,
            next_validation=unknowns,
            request_id=request_id,
        )

    for edge in edges:
        edge_id = str(edge.get("edge_id") or "")
        if not _contains(question, edge_id, str(edge.get("from_node") or ""), str(edge.get("to_node") or "")):
            continue
        status = str(edge.get("status") or "unknown")
        refs = tuple(str(item) for item in (edge.get("evidence_ref_ids") or ()))
        if status in {"supported", "conditional"}:
            answer = f"研究包中的逻辑边 {edge_id} 状态为 {status}：{edge.get('from_node')} -> {edge.get('to_node')}。"
            availability = "ready"
            refusal = None
        else:
            answer = f"研究包中的逻辑边 {edge_id} 当前状态为 {status}，不能作为已验证结论；needs_evidence。"
            availability = "unknown"
            refusal = str(edge.get("next_validation") or "需要补充验证")
        return ConversationMessageV1(
            sequence=sequence,
            created_at=_now(),
            question=question,
            answer=answer,
            availability=availability,
            refusal_reason=refusal,
            anchors=(ConversationAnchorV1(kind="edge", anchor_id=edge_id),),
            evidence_ref_ids=refs,
            next_validation=tuple(str(item) for item in (edge.get("missing_evidence") or ())[:8]),
            request_id=request_id,
        )

    return _unavailable(
        sequence,
        question,
        request_id,
        "研究包没有与该问题匹配的公开指标、同行比较或逻辑边；availability=unavailable，needs_evidence。",
        (),
        unknowns,
    )


def _unavailable(
    sequence: int,
    question: str,
    request_id: str | None,
    answer: str,
    anchors: tuple[ConversationAnchorV1, ...],
    next_validation: tuple[str, ...],
) -> ConversationMessageV1:
    return ConversationMessageV1(
        sequence=sequence,
        created_at=_now(),
        question=question,
        answer=answer,
        availability="unavailable",
        refusal_reason="required_public_evidence_unavailable",
        anchors=anchors,
        next_validation=next_validation,
        request_id=request_id,
    )


__all__ = ["answer_from_package"]
