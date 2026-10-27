"""Host-owned factual premises over frozen facts and qualified calculations.

These checks prove reference, scope and arithmetic, not free-prose entailment.
No network, model calls, user-data mutation or new financial formula.
"""

from copy import deepcopy
from decimal import Decimal

from tradingagents.agents.schemas._factual_premise import (
    FACTUAL_PREMISE_POLICY,
    FactualObservationV1,
    PremiseReceiptV1,
)
from tradingagents.agents.schemas._verification_plan import canonical_sha256

LABELS = {"interpretation": "解释假设：", "open_question": "待研究问题："}


def premise_enabled(identity):
    from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict
    policy = identity.get("factual_premise_policy")
    if policy is not None and (
        policy != FACTUAL_PREMISE_POLICY
        or identity.get("numeric_narrative_policy") != "anchored-narrative-v1"
    ):
        raise CatalystCheckpointConflict("native factual premise policy mismatch")
    return policy is not None


def observation_catalog(record, catalog, fact_ids):
    """Select facts verbatim; directions derive only from existing bounded checks."""
    raw = record.model_dump(mode="json") if hasattr(record, "model_dump") else record
    sources = {s["evidence_id"]: s for s in raw["evidence"]}
    facts = {f["claim_id"]: f for f in raw["claims"] if f["kind"] == "fact"
             and f["claim_id"] in fact_ids and f["evidence_ids"]
             and all(sources[e]["availability"] == "available" and sources[e].get("content")
                     and sources[e].get("usable_as_of") for e in f["evidence_ids"])}
    checks = (raw.get("evidence_checks") or {}).get("checks", [])
    conflicts = {e for c in checks if c["status"] == "conflict" for e in c["evidence_ids"]}
    result = []

    def add(kind, text, fids, eids, *, anchor=None, limits=()):
        value = {"kind": kind, "text": text, "fact_ids": sorted(fids), "evidence_ids": sorted(eids),
                     "anchor_id": anchor, "limitations": list(limits)}
        result.append(FactualObservationV1(
            observation_id="o." + canonical_sha256(value), **value).model_dump(mode="json"))

    for fid, fact in sorted(facts.items()):
        limits = list(dict.fromkeys(["来源转述，不保证来源真实或完整", *fact.get("limitations", []),
                     *(limit for eid in fact["evidence_ids"] for limit in sources[eid].get("limitations", []))]))
        if conflicts.intersection(fact["evidence_ids"]):
            limits.append("相关来源存在冲突，不作为无争议的统一事实")
        add("source", fact["statement"], [fid], fact["evidence_ids"], limits=limits)
    for anchor in catalog["anchors"]:
        if not set(anchor["required_fact_ids"]) <= facts.keys():
            continue
        meta, key = anchor["metadata"], anchor["definition_key"]
        if conflicts.intersection(anchor["input_evidence_ids"]):
            continue
        if meta.get("check_status") not in {None, "passed"}:
            continue
        official = key.startswith(("official.", "recovered.")) and key.endswith(".difference")
        structured = key.startswith(("check.financial_baseline.", "check.cashflow_comparison."))
        change = official or (structured and key.endswith("_change"))
        sign = anchor["basis"] == "actual_reported" or (structured and key.endswith(("_current", "_previous")))
        if not change and not sign:
            continue
        value = Decimal(anchor["value"])
        if change:
            direction = "增加" if value > 0 else "减少" if value < 0 else "不变"
            label = anchor["label"].removesuffix("同比金额变化").removesuffix("同比变化")
            text = f"{label}：{meta['report_period']}较{meta['prior_period']}金额{direction}。"
        else:
            direction = "为正" if value > 0 else "为负" if value < 0 else "为零"
            period = meta.get("prior_period") if structured and key.endswith("_previous") else meta.get("report_period")
            text = f"{anchor['label']}（{period or '保存期次'}）：保存数值{direction}。"
        text += f" 口径：{meta.get('source_basis', meta.get('frequency', '保存字段'))}；单位：{anchor['unit']}。"
        add("comparison" if change else "sign", text, anchor["required_fact_ids"],
            anchor["input_evidence_ids"], anchor=anchor["anchor_id"],
            limits=(*anchor["limitations"], "数值关系不证明经营改善、原因或持续性"))
    return sorted(result, key=lambda o: o["observation_id"])


def prepare_premise_context(stage, context, record, identity=None):
    attribution = getattr(record, "numeric_attribution", None)
    identity = identity if identity is not None else (attribution.input_identity if attribution else {})
    if not premise_enabled(identity):
        return context
    from tradingagents.research.numeric_narrative import _stage_fact_ids
    context["factual_premise_policy"] = FACTUAL_PREMISE_POLICY
    context["factual_observations"] = observation_catalog(
        record, context["numeric_catalog"], _stage_fact_ids(stage, context))
    return context


def premise_path(path):
    # Questions, conditions and limitations are never labelled verified observations.
    return path.split(".")[-1] in {"statement", "rationale", "judgement", "answer", "alternative_explanation"}


def discard_redundant_bindings(envelope, *, proposal=None, partitioned_collections=None):
    """Drop resolvable non-premise bindings before validating their unused contents.

    Unaddressable paths and required bindings remain subject to full validation.
    The caller gates this normalization on the factual-premise policy.
    """
    from tradingagents.research.numeric_narrative import (
        NumericNarrativeError,
        binding_path_issue,
        collection_index,
    )

    if not isinstance(envelope, dict):
        return envelope
    proposal = envelope.get("proposal") if proposal is None else proposal
    bindings = envelope.get("premises")
    if not isinstance(proposal, dict) or not isinstance(bindings, (list, tuple)):
        return envelope
    result = deepcopy(envelope)
    kept = []
    for binding in result["premises"]:
        path = binding.get("field_path") if isinstance(binding, dict) else None
        if not isinstance(path, str):
            kept.append(binding)
            continue
        issue = binding_path_issue(path, proposal)
        if partitioned_collections is not None and (
            issue in {"proposal_prefix", "index_out_of_range"}
            or issue == "unknown_path" and not any(
                collection_index(path, collection) is not None for collection in partitioned_collections)
        ):
            # Partitioning must not erase a shared invalid address. Bad fields
            # inside an existing item still go to that item's own validator.
            raise NumericNarrativeError("premise_binding_invalid", binding_issue=issue)
        if premise_path(path) or issue != "unexpected_field":
            kept.append(binding)
    result["premises"] = kept
    return result


def prepare_bindings(envelope, context, paths, *, proposal=None, collection=None):
    """Return (bindings, invalid item indices -> closed issue label).

    Redundant bindings on existing non-premise fields are discarded, including
    from the canonical envelope saved for replay. Wrong paths inside an existing
    item invalidate that item; out-of-range and unaddressable paths still reject.
    """
    from tradingagents.research.numeric_narrative import (
        NumericNarrativeError,
        binding_path_issue,
        collection_index,
    )
    bindings = envelope.get("premises")
    if not premise_enabled(context):
        if bindings is not None:
            raise NumericNarrativeError("premise_binding_invalid")
        return {}, {}
    if bindings is None:
        raise NumericNarrativeError("premise_binding_missing")
    allowed = {p for p in paths if premise_path(p)}
    result, invalid = {}, {}
    for binding in bindings:
        path = binding["field_path"]
        issue = ("duplicate_path" if path in result else None if path in allowed
                 else binding_path_issue(path, proposal or {}))
        if issue is None:
            result[path] = binding
            continue
        if issue == "unexpected_field":
            continue
        index = collection_index(path, collection)
        if index is None or issue == "index_out_of_range":
            raise NumericNarrativeError("premise_binding_invalid", binding_issue=issue)
        invalid.setdefault(index, issue)
    envelope["premises"] = [binding for binding in bindings
                            if binding["field_path"] in allowed]
    # Missing bindings are checked per field so valid specialist siblings survive.
    return result, invalid


def bind_field(stage, path, text, proof, proposal, context, bindings):
    from tradingagents.research.numeric_narrative import (
        NumericNarrativeError,
        _field_scope,
        _scan_literal,
        _text_hash,
    )
    if not premise_enabled(context) or not premise_path(path):
        return text, proof
    binding = bindings.get(path)
    if binding is None:
        raise NumericNarrativeError("premise_binding_missing", path)
    catalog = {o["observation_id"]: o for o in context["factual_observations"]}
    scope = _field_scope(stage, path, proposal, context)
    selected = []
    for oid in binding["observation_ids"]:
        observation = catalog.get(oid)
        if observation is None:
            raise NumericNarrativeError("premise_observation_unknown", path)
        if not set(observation["fact_ids"]) <= scope:
            raise NumericNarrativeError("premise_observation_scope", path)
        selected.append(observation)
    # A maintained inference / rated overall cannot be based on an empty selection.
    required = (path.startswith("hypotheses.") and path.endswith(".statement")
                or path.startswith(("supporting_arguments.", "opposing_arguments."))
                or path == "judgement" and proposal.get("investment_stance") not in {None, "insufficient_evidence"})
    if path.startswith("responses."):
        required = proposal["responses"][int(path.split(".")[1])]["disposition"] in {"maintained", "revised"}
    if path.startswith("reviews."):
        required = True
    if path.startswith("dimensions."):
        required = proposal["dimensions"][int(path.split(".")[1])]["status"] != "unresolved"
    if stage.startswith('search_review.') and path == 'rationale':
        required = proposal.get('disposition') in {'maintained', 'revised'}
    if required and not selected:
        raise NumericNarrativeError("premise_support_missing", path)
    for question in binding["pending_questions"]:
        _scan_literal(question, path)
        if "{{" in question or "}}" in question:
            raise NumericNarrativeError("premise_binding_invalid", path)
    receipt = PremiseReceiptV1(status="interpretation" if selected else "open_question",
        observations=selected, pending_questions=binding["pending_questions"]).model_dump(mode="json")
    label = LABELS[receipt["status"]]
    result = label + text
    proof = {**proof, "segments": [{"kind": "literal", "text": label}, *proof["segments"]],
             "text_sha256": _text_hash(result), "premise": receipt}
    return result, proof


def validate_context(record, stage, context, identity):
    from tradingagents.research.numeric_narrative import _stage_fact_ids
    enabled = premise_enabled(identity)
    if enabled != premise_enabled(context):
        raise ValueError("factual premise context policy mismatch")
    if enabled:
        if record.schema_version == 'research-record-v2':
            from tradingagents.research.record_codec import snapshot_view
            record = snapshot_view(record, context['numeric_input_snapshot_id'])
        actual = observation_catalog(record, context["numeric_catalog"], _stage_fact_ids(stage, context))
        if context.get("factual_observations") != actual:
            raise ValueError("factual premise observations changed")
    elif "factual_observations" in context:
        raise ValueError("factual observations without policy")


def public_premises(record):
    """Read-only projection keyed by exact accepted text, including partial delivery."""
    attribution = record.numeric_attribution
    if attribution is None or not premise_enabled(attribution.input_identity):
        return []
    result, seen = [], set()
    for stage in attribution.stages:
        for field in stage.proof["fields"]:
            premise = field.get("premise")
            if premise is None:
                continue
            text = "".join(s["text"] for s in field["segments"])
            key = canonical_sha256({"text": text, "premise": premise})
            if key not in seen:
                seen.add(key)
                result.append({"text": text, **deepcopy(premise)})
    return result


def stage_premises(proof):
    from tradingagents.agents.schemas._factual_premise import PublicPremiseV1
    return [PublicPremiseV1(text="".join(s["text"] for s in field["segments"]), **field["premise"])
            for field in proof.get("fields", []) if field.get("premise") is not None]
