"""Compile restricted quantity templates before IDs, and replay their receipts.

The lexer covers explicit supported quantity grammars. It does not validate
natural-language causality, implications, or implicit quantities/metaphors.
"""

import hashlib
import json
import re
import unicodedata
from copy import deepcopy
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

import rfc8785
from pydantic import ValidationError

from tradingagents.agents.schemas._numeric_narrative import NumericCatalogV1
from tradingagents.agents.schemas._numeric_stage import (
    NUMERIC_LEXER_VERSION,
    NUMERIC_NARRATIVE_POLICY,
    NumericStageEnvelopeV1,
    NumericStageProofV1,
)
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.research.numeric_catalog import (
    build_numeric_catalog,
    project_numeric_catalog,
    render_numeric_anchor,
)

_SPECIALISTS = {"operating_quality", "event_context", "market_context"}
_TOKEN = re.compile(r"\{\{(num|meta|plan):([a-zA-Z][a-zA-Z0-9_]{0,63})\}\}")
_CN_NUM = r"[零〇一二两兩三四五六七八九十百千万萬亿億兆壹贰貳叁肆伍陆陸柒捌玖拾佰仟点點半]+"
_CN_QUANTITY = re.compile(
    rf"(?:百分之|千分之|万分之|萬分之){_CN_NUM}|{_CN_NUM}(?:成|元|圆|圓|块|塊|股|吨|噸|辆|輛|倍|个百分点|個百分點|个基点|個基點|万|萬|亿|億)|{_CN_NUM}分之{_CN_NUM}|一半|对半|對半"
)
_EN_NUMBER = r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|trillion|half|quarter)"
_EN_QUANTITY = re.compile(
    rf"\b{_EN_NUMBER}(?:[\s-]+{_EN_NUMBER})*[\s-]*(?:percent|per\s+cent|basis\s+points?|dollars?|yuan|renminbi|cny|rmb|usd|euros?|pounds?|multiples?|times|shares?|tonnes?|tons?|vehicles?|quarters?)\b|\b(?:dollars?|yuan|cny|rmb|usd)\s+{_EN_NUMBER}\b",
    re.I,
)
_QUANTITY_ONLY_FIELDS = {"unknowns", "remaining_unknowns", "limitations"}
_TEXT_FIELDS = {
    "statement", "text", "alternative_explanation", "unknowns", "proposed_test",
    "rationale", "remaining_unknowns", "judgement", "next_check", "limitations",
    "answer", "suggested_next_check",
    "description", "new_risks",
}
_CODES = {
    "numeric_literal_unbound", "numeric_anchor_unknown", "numeric_anchor_scope",
    "numeric_basis_mismatch", "numeric_plan_mismatch", "numeric_render_limit",
    "premise_binding_invalid", "premise_binding_missing", "premise_observation_unknown",
        "premise_observation_scope", "premise_support_missing", "numeric_manifest_binding", "numeric_catalog_limit",
    "numeric_proposal_schema", "numeric_envelope_schema", "numeric_catalog_invalid",
    "numeric_cutoff_invalid", "numeric_condition_reference", "numeric_receipt_invalid",
}


BINDING_ISSUES = frozenset({
    "duplicate_path", "missing_path", "proposal_prefix", "index_out_of_range",
    "unexpected_field", "unknown_path",
})


class NumericNarrativeError(ValueError):
    """Safe diagnostics: never interpolate invalid model text or numbers."""

    def __init__(self, code, field_path="", *, index=None, binding_issue=None, validation_error=None, locations=()):
        if code not in _CODES:
            code = "numeric_manifest_binding"
        self.code, self.field_path, self.index = code, field_path, index
        self.validation_locations = tuple(issue["loc"] for issue in validation_error.errors(
            include_input=False, include_context=False, include_url=False)) if validation_error is not None else tuple(locations)
        parts = field_path.split(".") if isinstance(field_path, str) else []
        name = parts[-2] if len(parts) > 1 and parts[-1].isdigit() else parts[-1] if parts else None
        self.field_name = name if name in _TEXT_FIELDS else None
        # Closed shape label for a rejected binding path; never the path itself.
        self.binding_issue = binding_issue if binding_issue in BINDING_ISSUES else None
        super().__init__(code)


def binding_path_issue(path, proposal):
    """Classify an unexpected binding path without retaining model text."""
    if path.startswith("proposal."):
        return "proposal_prefix"
    value = proposal
    for part in path.split("."):
        if isinstance(value, list):
            if not part.isdigit():
                return "unknown_path"
            if int(part) >= len(value):
                return "index_out_of_range"
            value = value[int(part)]
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return "unknown_path"
    return "unexpected_field"


def collection_index(path, collection):
    match = re.match(rf"^{collection}\.(\d+)\.", path) if collection else None
    return int(match[1]) if match else None


def _plan_issue(paths, expected, proposal):
    if len(set(paths)) != len(paths):
        return "duplicate_path"
    extra = [p for p in paths if p not in expected]
    return binding_path_issue(extra[0], proposal) if extra else "missing_path"


def _payload(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else deepcopy(value)


def _text_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record(context):
    return _payload(context.get("record", {}))


def _facts(context):
    record = _record(context)
    return {f["claim_id"]: f for f in (record.get("claims", []) or context.get("facts", []))}


def _dependencies(ids, context):
    facts = _facts(context)
    result, pending = set(), list(ids)
    while pending:
        fid = pending.pop()
        if fid in result:
            continue
        fact = facts.get(fid)
        if fact is None or fact.get("kind") == "unknown":
            continue
        result.add(fid)
        pending.extend(fact.get("supporting_fact_ids", []))
    return result


def _stage_fact_ids(stage, context):
    if stage in _SPECIALISTS or stage.startswith(("response", "search_review.")):
        return {f["claim_id"] for f in context.get("facts", [])}
    record = _record(context)
    return {f["claim_id"] for f in record.get("claims", []) if f.get("kind") != "unknown"}


def prepare_numeric_context(stage, context, record, *, identity=None):
    """Freeze a stage view; foundation metadata never grants fact permission."""
    value = deepcopy(context)
    catalog = build_numeric_catalog(record)
    value["numeric_catalog"] = project_numeric_catalog(catalog, _stage_fact_ids(stage, context))
    value["numeric_narrative_policy"] = NUMERIC_NARRATIVE_POLICY
    if record.schema_version == 'research-record-v2':
        value['numeric_input_snapshot_id'] = record.snapshots[-1].snapshot_id
    value["numeric_analysis_date"] = str(_payload(record)["analysis_date"])
    value["numeric_aliases"] = {
        f"n_{index:04d}": a["anchor_id"]
        for index, a in enumerate(value["numeric_catalog"]["anchors"])
    }
    value["numeric_meta"] = {
        f"m_{index:04d}": m for index, m in enumerate(value["numeric_catalog"]["metadata"])
    }
    from tradingagents.research.factual_premises import prepare_premise_context
    return prepare_premise_context(stage, value, record, identity)


def numeric_prompt_schema(base_schema, *, premises=False):
    schema = NumericStageEnvelopeV1.model_json_schema()
    if not premises:
        schema["properties"].pop("premises", None)
        for name in ("PremiseBindingV1",):
            schema.get("$defs", {}).pop(name, None)
    else:
        schema.setdefault("required", []).append("premises")
    proposal = deepcopy(base_schema)
    definitions = proposal.pop("$defs", {})
    schema.setdefault("$defs", {}).update(definitions)
    schema["properties"]["proposal"] = proposal
    return schema


def _schema_validate(schema, proposal):
    # Pydantic remains authoritative even when the transport constrains JSON shape.
    try:
        return schema.model_validate(proposal).model_dump(mode="json")
    except ValidationError as exc:
        raise NumericNarrativeError("numeric_proposal_schema", validation_error=exc) from None
    except (ValueError, TypeError, KeyError):
        raise NumericNarrativeError("numeric_proposal_schema") from None


def _scan_literal(text, path):
    normalized = unicodedata.normalize("NFKC", text)
    # Reject format controls rather than silently rewriting canonical text.
    if any(unicodedata.category(char) in {"Cf", "Cs"} for char in normalized):
        raise NumericNarrativeError("numeric_literal_unbound", path)
    if (any(char.isnumeric() for char in normalized)
            or _CN_QUANTITY.search(normalized) or _EN_QUANTITY.search(normalized)):
        # isnumeric also covers Chinese numeral chars; exempt ordinary idioms
        # by applying it only to non-CJK numeric characters.
        non_cjk_numeric = any(char.isnumeric() and not ('\u3400' <= char <= '\u9fff')
                              for char in normalized)
        if non_cjk_numeric or _CN_QUANTITY.search(normalized) or _EN_QUANTITY.search(normalized):
            raise NumericNarrativeError("numeric_literal_unbound", path)
    if "{{" in normalized or "}}" in normalized:
        raise NumericNarrativeError("numeric_anchor_unknown", path)


def _target_facts(hid, context):
    record = _record(context)
    hypotheses = record.get("hypotheses", []) or context.get("hypotheses", [])
    hypothesis = next((h for h in hypotheses if h["hypothesis_id"] == hid), None)
    if hypothesis is None:
        return set()
    claims = _facts(context)
    assertion = claims.get(hypothesis["claim_id"])
    if assertion is None:
        assertion = next((c for c in context.get("assertions", [])
                          if c["claim_id"] == hypothesis["claim_id"]), {})
    return _dependencies(assertion.get("supporting_fact_ids", []), context)


def _challenge_facts(cid, context):
    record = _record(context)
    challenge = next((c for c in record.get("challenges", []) if c["challenge_id"] == cid), None)
    if challenge is None:
        challenge = next((c for c in context.get("challenges", []) if c["challenge_id"] == cid), {})
    return (_dependencies(challenge.get("target_claim_ids", []), context)
            | _dependencies((challenge.get("test") or {}).get("supporting_fact_ids", []), context))


def _reply_facts(rid, context):
    replies = (_record(context).get("dialogue") or {}).get("responses", [])
    reply = next((r for r in replies if r["response_id"] == rid), {})
    return _dependencies(reply.get("supporting_fact_ids", []), context)


def _field_scope(stage, path, proposal, context):
    if stage.startswith('search_review.'):
        return _dependencies(proposal.get('supporting_fact_ids', []), context)
    parts = path.split(".")
    parent, index = parts[0], int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    if parent == "hypotheses":
        return _dependencies(proposal[parent][index]["supporting_fact_ids"], context)
    if parent == "challenges":
        item = proposal[parent][index]
        return _target_facts(item["hypothesis_id"], context) | _dependencies(item.get("supporting_fact_ids", []), context)
    if parent == "reviews":
        item = proposal[parent][index]
        return _target_facts(item["hypothesis_id"], context) | _dependencies(item.get("supporting_fact_ids", []), context)
    if parent == "responses":
        reply = proposal[parent][index]
        allowed = set(context.get("allowed_facts_by_challenge", {}).get(reply["challenge_id"], []))
        return _dependencies(reply.get("supporting_fact_ids", []), context) & allowed
    if stage == "focus_response" or "answer" in proposal:
        facts = _dependencies(proposal.get("claim_ids", []), context)
        selected_evidence = set(proposal.get("evidence_ids", []))
        facts.update(fid for fid, fact in _facts(context).items()
                     if fact.get("kind") == "fact" and fact.get("evidence_ids")
                     and set(fact["evidence_ids"]) <= selected_evidence)
        return facts
    if parent == "dimensions":
        dimension = proposal[parent][index]
        allowed = set(context.get("dimension_claim_ids", {}).get(dimension["dimension"], []))
        selected = set(dimension.get("claim_ids", []))
        if allowed and not selected <= allowed:
            raise NumericNarrativeError("numeric_anchor_scope", path)
        return _dependencies(selected, context)
    if parent in {"supporting_arguments", "opposing_arguments"}:
        item = proposal[parent][index]
        allowed = _dependencies(item["claim_ids"], context)
        for rid in item.get("response_ids", []):
            allowed &= _reply_facts(rid, context)
        return allowed
    if parent == "adjudications":
        item = proposal[parent][index]
        return _challenge_facts(item["challenge_id"], context) | _reply_facts(item["response_id"], context)
    if parent == "challenge_assessments":
        return _challenge_facts(proposal[parent][index]["challenge_id"], context)
    if parent == "change_conditions":
        return _target_facts(proposal[parent][index]["hypothesis_id"], context)
    return _dependencies(proposal.get("key_claim_ids", []), context)


def _fields(value, prefix="", text_field=False):
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            yield from _fields(child, path, key in _TEXT_FIELDS)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _fields(child, f"{prefix}.{index}", text_field)
    elif text_field and isinstance(value, str):
        yield prefix, value


def _set_path(value, path, replacement):
    parts = path.split(".")
    for part in parts[:-1]:
        value = value[int(part)] if isinstance(value, list) else value[part]
    if isinstance(value, list):
        value[int(parts[-1])] = replacement
    else:
        value[parts[-1]] = replacement


def _no_quantity(path):
    return any(part in _QUANTITY_ONLY_FIELDS for part in path.split("."))


def _plan_allowed(path):
    return path.endswith((".text", ".proposed_test", ".observation_date")) and (
        ".conditions." in path or path.startswith("challenges.")) or path in {"next_check", "suggested_next_check"}


def _cutoff(context):
    raw = context.get("numeric_analysis_date") or _record(context).get("analysis_date")
    if raw is None:
        raise NumericNarrativeError("numeric_cutoff_invalid", locations=[("numeric_analysis_date",)])
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise NumericNarrativeError("numeric_cutoff_invalid", locations=[("numeric_analysis_date",)]) from None


def _render_plan(plan, context, path):
    if not _plan_allowed(path) or plan["field_path"] != path:
        raise NumericNarrativeError("numeric_plan_mismatch", path)
    if plan["kind"] == "date":
        try:
            target = date.fromisoformat(plan["date"])
        except ValueError:
            raise NumericNarrativeError("numeric_plan_mismatch", path) from None
        if target <= _cutoff(context):
            raise NumericNarrativeError("numeric_plan_mismatch", path)
        return f"模型提出的观察日期{target.isoformat()}（非已披露事实）"
    number = Decimal(plan["threshold"])
    units = {"CNY": "元", "CNY/share": "元/股", "ratio": "%", "percent": "%", "multiple": "倍", "count": "个"}
    if plan["unit"] == "ratio":
        number *= 100
    shown = format(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN), "f")
    operator = {"lt": "小于", "le": "不高于", "eq": "等于", "ge": "不低于", "gt": "大于"}[plan["operator"]]
    return f"模型提出的观察阈值{operator}{shown}{units[plan['unit']]}（非已披露事实）"


def _compile_field(stage, path, template, proposal, context, plans, counts):
    if stage == "synthesis" and path.startswith("change_conditions.") and path.endswith(".text"):
        item = proposal["change_conditions"][int(path.split(".")[1])]
        parent = next((h for h in _record(context).get("hypotheses", [])
                       if h["hypothesis_id"] == item["hypothesis_id"]), None)
        index = item["invalidation_index"]
        if parent is None or not 0 <= index < len(parent["invalidation_conditions"]):
            raise NumericNarrativeError("numeric_condition_reference", path,
                locations=[tuple(int(p) if p.isdigit() else p for p in path.split("."))])
        text = parent["invalidation_conditions"][index]
        return text, {"path": path, "segments": [{"kind": "inherited", "text": text,
            "parameters": {"hypothesis_id": item["hypothesis_id"], "invalidation_index": index}}],
            "text_sha256": _text_hash(text), "lexer_version": NUMERIC_LEXER_VERSION}
    scope = _field_scope(stage, path, proposal, context)
    anchors = {a["anchor_id"]: a for a in context["numeric_catalog"]["anchors"]}
    aliases = context.get("numeric_aliases", {})
    metadata = context.get("numeric_meta", {})
    segments, cursor = [], 0
    for token_count, match in enumerate(_TOKEN.finditer(template), 1):
        literal = template[cursor:match.start()]
        _scan_literal(literal, path)
        if literal:
            segments.append({"kind": "literal", "text": literal})
        kind, alias = match.groups()
        counts[0] += 1
        if token_count > 8 or counts[0] > 64:
            raise NumericNarrativeError("numeric_render_limit", path)
        if kind in {"num", "plan"} and _no_quantity(path):
            raise NumericNarrativeError("numeric_anchor_scope", path)
        if kind == "num":
            anchor_id = aliases.get(alias)
            anchor = anchors.get(anchor_id)
            if anchor is None:
                raise NumericNarrativeError("numeric_anchor_unknown", path)
            if not set(anchor["required_fact_ids"]) <= scope:
                raise NumericNarrativeError("numeric_anchor_scope", path)
            text = render_numeric_anchor(anchor)
            segments.append({"kind": kind, "alias": alias, "anchor_id": anchor_id, "text": text})
        elif kind == "meta":
            meta = metadata.get(alias)
            if meta is None:
                raise NumericNarrativeError("numeric_anchor_unknown", path)
            if meta.get("required_fact_ids") and not set(meta["required_fact_ids"]) <= scope:
                raise NumericNarrativeError("numeric_anchor_scope", path)
            label = {"identity": "身份", "period": "期次", "source_title": "来源标题"}.get(meta["kind"])
            if label is None:
                raise NumericNarrativeError("numeric_basis_mismatch", path)
            text = f"{label}：{meta['text']}"
            segments.append({"kind": kind, "alias": alias, "text": text})
        else:
            plan = plans.get(alias)
            if plan is None:
                raise NumericNarrativeError("numeric_plan_mismatch", path)
            text = _render_plan(plan, context, path)
            segments.append({"kind": kind, "alias": alias, "text": text, "parameters": plan})
        cursor = match.end()
    literal = template[cursor:]
    _scan_literal(literal, path)
    if literal or not segments:
        segments.append({"kind": "literal", "text": literal})
    text = "".join(segment["text"] for segment in segments)
    return text, {"path": path, "segments": segments, "text_sha256": _text_hash(text), "lexer_version": NUMERIC_LEXER_VERSION}


def numeric_validation_context(context, *, sectioned=False):
    """Public data actually needed for replay, without prompts or recursive output."""
    keys = {
        "numeric_narrative_policy", "numeric_catalog", "numeric_aliases", "numeric_meta",
        "factual_premise_policy", "factual_observations",
        "numeric_analysis_date", "numeric_input_snapshot_id", "facts", "assertions", "hypotheses", "challenges",
        "allowed_facts_by_challenge", "assigned", "dimension_claim_ids", "local_checks",
        "challenge_check_policy",
    }
    value = {key: deepcopy(context[key]) for key in keys if key in context}
    if context.get("challenge_check_policy"):
        for key in ("verifications", "challenge_outcomes"):
            if key in context:
                value[key] = deepcopy(context[key])
    if "record" in context:
        record = _record(context)
        value["record"] = {key: record[key] for key in (
            "analysis_date", "claims", "hypotheses", "challenges", "dialogue",
        ) if key in record}
        if record.get("challenge_check_policy"):
            for key in ("challenge_check_policy", "challenge_outcomes", "verifications"):
                if key in record:
                    value["record"][key] = deepcopy(record[key])
        if sectioned:
            value["record"] = record
            value["record"].pop("assessment", None)
            value["record"].pop("numeric_attribution", None)
            value["question"] = context["question"]
            value["synthesis_sections_policy"] = "synthesis-sections-v1"
    return json.loads(rfc8785.dumps(value)) if sectioned else value


def validate_numeric_field(field, catalog, *, metadata=None):
    """Replay ordered public segments; source token-looking text is never executed."""
    from tradingagents.agents.schemas._numeric_stage import NumericFieldProofV1

    try:
        receipt = NumericFieldProofV1.model_validate(field).model_dump(mode="json")
        NumericCatalogV1.model_validate(catalog)
    except ValidationError as exc:
        raise NumericNarrativeError("numeric_receipt_invalid", validation_error=exc) from None
    except (ValueError, TypeError):
        raise NumericNarrativeError("numeric_receipt_invalid") from None
    anchors = {a["anchor_id"]: a for a in catalog["anchors"]}
    meta_values = [m for key, m in (metadata or {}).items()
                   if key != "inherited_conditions"] or catalog.get("metadata", [])
    pieces = []
    for segment in receipt["segments"]:
        kind, text = segment["kind"], segment["text"]
        if kind == "literal":
            _scan_literal(text, receipt["path"])
        elif kind == "num":
            anchor = anchors.get(segment["anchor_id"])
            if anchor is None or text != render_numeric_anchor(anchor):
                raise NumericNarrativeError("numeric_receipt_invalid", receipt["path"])
        elif kind == "meta":
            labels = {"identity": "身份", "period": "期次", "source_title": "来源标题"}
            candidates = [f"{labels[m['kind']]}：{m['text']}" for m in meta_values if m["kind"] in labels]
            if text not in candidates:
                raise NumericNarrativeError("numeric_receipt_invalid", receipt["path"])
        elif kind == "inherited":
            inherited = (metadata or {}).get("inherited_conditions", {})
            parameters = segment["parameters"] or {}
            key = (parameters.get("hypothesis_id"), parameters.get("invalidation_index"))
            if inherited.get(key) != text:
                raise NumericNarrativeError("numeric_receipt_invalid", receipt["path"])
        else:
            plan = segment["parameters"]
            if plan is None:
                raise NumericNarrativeError("numeric_receipt_invalid", receipt["path"])
            # Stage replay checks the cutoff; field replay still checks exact rendering.
            context = {"numeric_analysis_date": "0001-01-01"}
            if text != _render_plan(plan, context, receipt["path"]):
                raise NumericNarrativeError("numeric_receipt_invalid", receipt["path"])
        pieces.append(text)
    rendered = "".join(pieces)
    if _text_hash(rendered) != receipt["text_sha256"]:
        raise NumericNarrativeError("numeric_receipt_invalid", receipt["path"])
    return rendered


def _required_bindings(proposal):
    result = {}
    for hi, hypothesis in enumerate(proposal.get("hypotheses", [])):
        for ci, condition in enumerate(hypothesis["conditions"]):
            check = condition.get("check")
            if check is None:
                continue
            root = f"hypotheses.{hi}.conditions.{ci}.check"
            if check["kind"] == "financial":
                result[root+".current"] = ("operand", check["current"], check)
                if check.get("base") is not None:
                    result[root+".base"] = ("operand", check["base"], check)
            else:
                result[root+".metric_id"] = ("metric", check["metric_id"], check)
            result[root+".predicate"] = ("predicate", check["predicate"], check)
    for ci, challenge in enumerate(proposal.get("challenges", [])):
        check = challenge.get("check")
        if check is not None:
            root = f"challenges.{ci}.check"
            if check["kind"] == "financial":
                result[root+".current"] = ("operand", check["current"], check)
                if check.get("base") is not None:
                    result[root+".base"] = ("operand", check["base"], check)
            else:
                result[root+".metric_id"] = ("metric", check["metric_id"], check)
            result[root+".predicate"] = ("predicate", check["predicate"], check)
        if challenge.get("observation_date") is not None:
            result[f"challenges.{ci}.observation_date"] = ("date", challenge["observation_date"], challenge)
    return result


def _anchor_for_binding(binding, anchors, aliases, scope, path):
    if binding["kind"] != "num":
        raise NumericNarrativeError("numeric_plan_mismatch", path)
    anchor = anchors.get(aliases.get(binding["alias"]))
    if anchor is None:
        raise NumericNarrativeError("numeric_anchor_unknown", path)
    if not set(anchor["required_fact_ids"]) <= scope:
        raise NumericNarrativeError("numeric_anchor_scope", path)
    return anchor


def _check_frequency(current, base, path, operation):
    accepted = {"annual", "full_year", "year", "yearly", "FY", "H1", "half_year", "semiannual", "half-year"}
    cm, bm = current["metadata"], base["metadata"]
    frequency = cm.get("frequency")
    cs, bs = current["lineage"].get("source_selector", {}), base["lineage"].get("source_selector", {})
    if (frequency not in accepted or bm.get("frequency") != frequency
            or not current["lineage"].get("source_family_id")
            or current["lineage"].get("source_family_id") != base["lineage"].get("source_family_id")
            or (cs.get("table"), cs.get("field")) != (bs.get("table"), bs.get("field"))
            or operation == "growth" and Decimal(base["value"]) <= 0):
        raise NumericNarrativeError("numeric_basis_mismatch", path)


def _validate_bindings(stage, proposal, envelope, context, *, prefix=None):
    expected = _required_bindings(proposal)
    entries = envelope["structured_bindings"]
    if prefix is not None:
        expected = {p: value for p, value in expected.items() if p.startswith(prefix)}
        entries = [b for b in entries if b["field_path"].startswith(prefix)]
    bindings = {b["field_path"]: b for b in entries}
    if len(bindings) != len(entries) or bindings.keys() != expected.keys():
        raise NumericNarrativeError("numeric_plan_mismatch",
            binding_issue=_plan_issue([b["field_path"] for b in entries], expected.keys(), proposal))
    anchors = {a["anchor_id"]: a for a in context["numeric_catalog"]["anchors"]}
    aliases = context.get("numeric_aliases", {})
    plans = {p["alias"]: p for p in envelope["plans"]}
    bound = {}
    for path, (kind, value, owner) in expected.items():
        if prefix is not None and not path.startswith(prefix):
            continue
        binding = bindings[path]
        scope = _field_scope(stage, path, proposal, context)
        if kind == "predicate":
            plan = plans.get(binding["alias"]) if binding["kind"] == "plan" else None
            text_path = path.rsplit(".check.predicate", 1)[0] + (
                ".proposed_test" if path.startswith("challenges.") else ".text")
            if (plan is None or plan["kind"] != "quantity" or plan["field_path"] != text_path
                    or any(plan[key] != value[key] for key in ("threshold", "unit", "operator"))):
                raise NumericNarrativeError("numeric_plan_mismatch", path)
            _render_plan(plan, context, text_path)
            continue
        if kind == "date" and binding["kind"] == "plan":
            plan = plans.get(binding["alias"])
            if plan is None or plan["kind"] != "date" or plan["date"] != value:
                raise NumericNarrativeError("numeric_plan_mismatch", path)
            _render_plan(plan, context, path)
            continue
        anchor = _anchor_for_binding(binding, anchors, aliases, scope, path)
        selector = anchor["lineage"].get("source_selector", {})
        if kind == "operand":
            if (anchor["basis"] != "actual_reported" or value["evidence_id"] not in anchor["input_evidence_ids"]
                    or any(selector.get(k) != value[k] for k in ("table", "field", "report_period"))):
                raise NumericNarrativeError("numeric_basis_mismatch", path)
            bound[path] = anchor
        elif kind == "metric":
            if selector.get("metric_id") != value:
                raise NumericNarrativeError("numeric_basis_mismatch", path)
            unit = "ratio" if anchor["unit"] in {"ratio", "fraction"} else anchor["unit"]
            if owner["predicate"]["unit"] != unit:
                raise NumericNarrativeError("numeric_plan_mismatch", path)
        else:
            observed = anchor["metadata"].get("as_of") or anchor["metadata"].get("report_period")
            if (str(observed) != value or date.fromisoformat(value) > _cutoff(context)
                    or not owner.get("check_id")
                    or anchor["metadata"].get("check_id") != owner["check_id"]):
                raise NumericNarrativeError("numeric_basis_mismatch", path)
    for path, (_, _, owner) in expected.items():
        if (path.endswith(".current") and owner["operation"] != "value"
                and (prefix is None or path.startswith(prefix))):
            _check_frequency(bound[path], bound[path[:-len("current")]+"base"], path, owner["operation"])


def _canonical_envelope(envelope, schema, *, discard_extra_premises=False):
    if discard_extra_premises and isinstance(envelope, dict) and isinstance(envelope.get("proposal"), dict):
        from tradingagents.research.factual_premises import discard_redundant_bindings
        proposal = _schema_validate(schema, envelope["proposal"])
        envelope = discard_redundant_bindings(envelope, proposal=proposal)
    try:
        result = NumericStageEnvelopeV1.model_validate(envelope).model_dump(mode="json")
    except ValidationError as exc:
        raise NumericNarrativeError("numeric_envelope_schema", validation_error=exc) from None
    except (ValueError, TypeError):
        raise NumericNarrativeError("numeric_envelope_schema") from None
    result["proposal"] = _schema_validate(schema, result["proposal"])
    plans = result["plans"]
    if len({p["alias"] for p in plans}) != len(plans):
        raise NumericNarrativeError("numeric_plan_mismatch")
    # No unused parameter escape hatch. Plans must be consumed by their own
    # text or an explicit structured binding, not silently attached to a stage.
    text = "\n".join(t for _, t in _fields(result["proposal"]))
    consumed = {alias for kind, alias in _TOKEN.findall(text) if kind == "plan"}
    consumed.update(b["alias"] for b in result["structured_bindings"] if b["kind"] == "plan")
    if consumed != {p["alias"] for p in plans}:
        raise NumericNarrativeError("numeric_plan_mismatch")
    return result


def _remap_path(path, indices, *, reverse=False):
    match = re.match(r"^(hypotheses|challenges)\.(\d+)(\..*)$", path)
    if not match:
        return path
    index = int(match[2])
    mapping = {old: new for new, old in enumerate(indices)} if reverse else dict(enumerate(indices))
    if index not in mapping:
        return None
    return f"{match[1]}.{mapping[index]}{match[3]}"


def _compile(stage, envelope, context, schema, *, isolate=False, indices=None, rejections=None, issues=None):
    if context.get("numeric_narrative_policy") != NUMERIC_NARRATIVE_POLICY:
        raise NumericNarrativeError("numeric_manifest_binding")
    try:
        NumericCatalogV1.model_validate(context["numeric_catalog"])
    except ValidationError as exc:
        raise NumericNarrativeError("numeric_catalog_invalid",
            locations=[("numeric_catalog", *issue["loc"]) for issue in exc.errors()]) from None
    except (KeyError, ValueError, TypeError):
        raise NumericNarrativeError("numeric_catalog_invalid", locations=[("numeric_catalog",)]) from None
    if stage == "synthesis" and isinstance(envelope, dict) and isinstance(envelope.get("proposal"), dict):
        envelope = deepcopy(envelope)
        raw = envelope["proposal"]
        parents = {h["hypothesis_id"]: h for h in _record(context).get("hypotheses", [])}
        for item in raw.get("change_conditions", []):
            parent, index = parents.get(item.get("hypothesis_id")), item.get("invalidation_index")
            if parent is not None and type(index) is int and 0 <= index < len(parent["invalidation_conditions"]):
                item["text"] = parent["invalidation_conditions"][index]
        replies = {r["challenge_id"]: r for r in (_record(context).get("dialogue") or {}).get("responses", [])}
        for item in raw.get("adjudications", []):
            reply = replies.get(item.get("challenge_id"))
            if reply is not None:
                item["response_id"], item["disposition"] = reply["response_id"], reply["disposition"]
    from tradingagents.research.factual_premises import (
        bind_field,
        premise_enabled,
        prepare_bindings,
    )
    envelope = _canonical_envelope(envelope, schema, discard_extra_premises=premise_enabled(context))
    proposal, compiled = envelope["proposal"], deepcopy(envelope["proposal"])
    plans = {p["alias"]: p for p in envelope["plans"]}
    collection = ("hypotheses" if stage in _SPECIALISTS else "challenges"
                  if stage == "challenge" and context.get("challenge_check_policy") else None)
    premise_bindings, invalid_premises = prepare_bindings(envelope, context, [p for p, _ in _fields(proposal)],
        proposal=proposal, collection=collection)
    def compile_field(path, template):
        text, field = _compile_field(stage, path, template, proposal, context, plans, counts)
        return bind_field(stage, path, text, field, proposal, context, premise_bindings)
    counts, fields, accepted, rejected = [0], [], [], list(rejections or [])
    # Malformed main schemas and unaddressable binding paths are never isolated;
    # an isolated item's own binding set is compared within its prefix below.
    expected_paths = _required_bindings(proposal).keys()
    binding_paths = [b["field_path"] for b in envelope["structured_bindings"]]
    if collection and isolate:
        for path in binding_paths:
            index = collection_index(path, collection)
            if index is None or index >= len(proposal[collection]):
                raise NumericNarrativeError("numeric_plan_mismatch",
                    binding_issue="index_out_of_range" if index is not None else binding_path_issue(path, proposal))
    elif len(set(binding_paths)) != len(binding_paths) or set(binding_paths) != set(expected_paths):
        raise NumericNarrativeError("numeric_plan_mismatch", binding_issue=_plan_issue(binding_paths, expected_paths, proposal))
    if collection:
        # Shared unknowns are validated first; a bad shared field rejects all.
        for path, template in _fields(proposal):
            if not path.startswith(collection + "."):
                text, field = compile_field(path, template)
                _set_path(compiled, path, text)
                fields.append(field)
        for index, hypothesis in enumerate(proposal[collection]):
            local_fields, prior_count = [], counts[0]
            try:
                if index in invalid_premises:
                    raise NumericNarrativeError("premise_binding_invalid", binding_issue=invalid_premises[index])
                _validate_bindings(stage, proposal, envelope, context, prefix=f"{collection}.{index}.")
                for path, template in _fields(hypothesis, f"{collection}.{index}"):
                    text, field = compile_field(path, template)
                    _set_path(compiled, path, text)
                    local_fields.append(field)
                # Validate expanded hypothesis lengths before accepting siblings.
                local_proposal = {**compiled, collection: [compiled[collection][index]]}
                _schema_validate(schema, local_proposal)
            except NumericNarrativeError as exc:
                counts[0] = prior_count
                if not isolate:
                    exc.index = index
                    exc.hypothesis_index = index
                    raise
                rejected.append({"index": index, "code": exc.code})
                if issues is not None and exc.validation_locations:
                    issues.append({"index": index, "locations": [
                        (collection, index, *path[2:]) if path[:2] == (collection, 0) else path
                        for path in exc.validation_locations]})
                if issues is not None and exc.binding_issue:
                    # Diagnostics only; the saved proof keeps its closed rejection shape.
                    issues.append({"index": index, "binding_issue": exc.binding_issue})
                if issues is not None and exc.code == "numeric_literal_unbound" and exc.field_name:
                    issues.append({"index": index, "field_name": exc.field_name})
            else:
                accepted.append(index)
                fields.extend(local_fields)
        compiled[collection] = [compiled[collection][i] for i in accepted]
        saved = deepcopy(envelope)
        saved["proposal"][collection] = [proposal[collection][i] for i in accepted]
        for name in ("plans", "structured_bindings", *(("premises",) if "premises" in saved else ())):
            saved[name] = [dict(item, field_path=mapped) for item in saved[name]
                           if (mapped := _remap_path(item["field_path"], accepted, reverse=True)) is not None]
        if indices is None:
            indices = accepted
        else:
            fields = [{**field, "path": _remap_path(field["path"], indices)} for field in fields]
    else:
        _validate_bindings(stage, proposal, envelope, context)
        for path, template in _fields(proposal):
            text, field = compile_field(path, template)
            _set_path(compiled, path, text)
            fields.append(field)
        saved = envelope
        indices = []
    compiled = _schema_validate(schema, compiled)
    proof = {
        "policy": NUMERIC_NARRATIVE_POLICY, "stage": stage,
        "context_sha256": canonical_sha256(numeric_validation_context(context)),
        "proposal_sha256": canonical_sha256(compiled),
        "catalog_hash": canonical_sha256(context["numeric_catalog"]),
        "envelope": saved, "fields": fields,
        "indices": list(indices), "rejections": rejected,
    }
    return compiled, NumericStageProofV1.model_validate(proof).model_dump(mode="json")


def compile_numeric_stage(stage, envelope, context, schema, *, isolate=False, issues=None):
    """Compile a full stage or lawful specialist siblings with original indices.

    ``issues`` optionally collects closed binding-shape labels of isolated
    rejections for diagnostics; it never changes the compiled result or proof.
    """
    if stage == "challenge" and context.get("challenge_check_policy") and isolate:
        from tradingagents.research.challenge_checks import parse_challenge_items
        from tradingagents.research.factual_premises import (
            discard_redundant_bindings,
            premise_enabled,
        )
        if premise_enabled(context):
            envelope = discard_redundant_bindings(envelope, partitioned_collections=("challenges",))
        envelope = NumericStageEnvelopeV1.model_validate(envelope).model_dump(mode="json")
        proposal, indices, rejections = parse_challenge_items(envelope["proposal"])
        envelope["proposal"] = proposal.model_dump(mode="json")
        for key in ("plans", "structured_bindings", *(("premises",) if "premises" in envelope else ())):
            envelope[key] = [dict(item, field_path=path) for item in envelope[key]
                if (path := _remap_path(item["field_path"], indices, reverse=True)) is not None]
        compiled, proof = _compile(stage, envelope, context, schema, isolate=True, issues=issues)
        original_indices = [indices[i] for i in proof["indices"]]
        rejected = [*rejections, *({**r, "index": indices[r["index"]]} for r in proof["rejections"])]
        return _compile(stage, proof["envelope"], context, schema,
            indices=original_indices, rejections=sorted(rejected, key=lambda r: r["index"]))
    return _compile(stage, envelope, context, schema, isolate=isolate, issues=issues)


def validate_numeric_stage(stage, proposal, proof, context, schema):
    """Saved output must rebuild exactly; no repair calls or missing-proof fallback."""
    if isinstance(proof, dict) and proof.get("kind") == "synthesis-sections-v1":
        from tradingagents.agents.schemas._native_stage import SynthesisProposalV3
        from tradingagents.research.synthesis_sections import validate_sectioned_proof
        if stage != "synthesis" or schema is not SynthesisProposalV3:
            raise NumericNarrativeError("numeric_manifest_binding")
        validate_sectioned_proof(proposal, proof, context)
        return
    try:
        saved = NumericStageProofV1.model_validate(proof).model_dump(mode="json")
        indices, rejections = saved["indices"], saved["rejections"]
        if stage in _SPECIALISTS or stage == "challenge" and context.get("challenge_check_policy"):
            collection = "challenges" if stage == "challenge" else "hypotheses"
            all_indices = [*indices, *(r["index"] for r in rejections)]
            if (len(indices) != len(saved["envelope"]["proposal"][collection])
                    or indices != sorted(set(indices)) or sorted(all_indices) != list(range(len(all_indices)))
                    or len(all_indices) > 3):
                raise NumericNarrativeError("numeric_manifest_binding")
        elif indices or rejections:
            raise NumericNarrativeError("numeric_manifest_binding")
        actual, rebuilt = _compile(stage, saved["envelope"], context, schema,
                                   indices=indices, rejections=rejections)
        if actual != _schema_validate(schema, proposal) or rebuilt != saved:
            raise NumericNarrativeError("numeric_manifest_binding")
    except (ValidationError, ValueError, KeyError, TypeError, IndexError):
        raise NumericNarrativeError("numeric_manifest_binding") from None
