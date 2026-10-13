"""Host-owned report assembly and copied bindings; never invent analysis."""

from copy import deepcopy

from tradingagents.agents.schemas._research_assessment import DimensionAssessmentV1
from tradingagents.agents.schemas._research_dialogue import excluded_support
from tradingagents.research.native_policy import (
    dimension_claim_ids,
    dimension_policy,
    gate_dimensions,
)
from tradingagents.research.native_versions import REPORT_DELIVERY_POLICY


def delivery_enabled(record):
    return REPORT_DELIVERY_POLICY in record.limitations


def normalize_synthesis_bindings(value, record):
    """Restore only fields owned by saved hypotheses and challenge replies."""
    result = deepcopy(value)
    hypotheses = {h.hypothesis_id: h for h in record.hypotheses}
    conditions = []
    for item in result.get("change_conditions", []):
        if not isinstance(item, dict):
            continue
        hypothesis = hypotheses.get(item.get("hypothesis_id"))
        index = item.get("invalidation_index")
        if hypothesis is not None and type(index) is int and 0 <= index < len(hypothesis.invalidation_conditions):
            conditions.append({"hypothesis_id": hypothesis.hypothesis_id, "invalidation_index": index,
                               "text": hypothesis.invalidation_conditions[index]})
    conditions = list({(item["hypothesis_id"], item["invalidation_index"]): item for item in conditions}.values())
    result["change_conditions"] = conditions[:3]
    replies = {r.challenge_id: r for r in record.dialogue.responses}
    for item in result.get("adjudications", []):
        if not isinstance(item, dict):
            continue
        reply = replies.get(item.get("challenge_id"))
        if reply is not None:
            item["response_id"] = reply.response_id
            item["disposition"] = reply.disposition
    return result


def retained_summary(record):
    """Keep actual effective specialist statements and code-selected facts."""
    allowed = dimension_claim_ids(record)
    claims = {c.claim_id: c for c in record.claims}
    excluded = excluded_support(record)
    dimensions, keys = [], []
    for name, (ceiling, gap) in dimension_policy(record, scoped=True, valuation=True).items():
        ids = [h.claim_id for h in record.hypotheses if h.claim_id in allowed[name] and h.claim_id not in excluded][:2]
        label = "已保存专项观点："
        if not ids:
            ids = [cid for cid in allowed[name] if claims[cid].kind == "fact"][:2]
            label = "已保存基础观察："
        if ceiling == "unresolved" or not ids:
            dimensions.append(DimensionAssessmentV1(dimension=name, status="unresolved",
                judgement="此项具体判断仍待补充；已有基础资料和其他专项结果已保留。", limitations=(gap,)))
        else:
            statement = label + "；".join(claims[cid].statement for cid in ids)
            dimensions.append(DimensionAssessmentV1(dimension=name, status="conditional", judgement=statement[:400],
                claim_ids=tuple(ids), limitations=("host_retained_findings_not_synthesis",)))
            keys.extend(ids)
    return gate_dimensions(record, dimensions, scoped=True, valuation=True), tuple(dict.fromkeys(keys))[:3]
