"""Model-local metadata; canonical paths remain exclusively host-owned."""

from copy import deepcopy

from tradingagents.agents.schemas._factual_premise import PremiseBindingV1
from tradingagents.agents.schemas._numeric_stage import NumericPlanV1, NumericStructuredBindingV1
from tradingagents.research.factual_premises import premise_path
from tradingagents.research.numeric_narrative import _TEXT_FIELDS, _plan_allowed


class InlineBindingError(ValueError):
    code = "inline_binding_shape"


def inline_binding_instructions(*, premises=True):
    text = (
        "\nUse the inline schema. Return only proposal and gaps where requested; never output "
        "field_path or top-level plans, structured_bindings or premises. The host derives all "
        "addresses from the actual field and array position. Text fields shown as objects keep "
        "their local annotations beside text; plain qualitative fields remain strings. Put each proposed plan in "
        "plans beside its own text, with alias and typed parameters, and refer to {{plan:p_alias}}. "
        "For each check.current/base, check.metric_id, check.predicate or challenge.observation_date "
        "shown as an object, put its original value in value and its {kind,alias} reference in binding. "
        "A future observation_date may declare its date plan in its own local plans. "
        "Every narrative quantity, date and numbered identity must use the exact supplied "
        "{{num:n_alias}} or {{meta:m_alias}} token; never type observed values, calculate numbers, "
        "change units, guess anchors or remove forecast/quote labels. Keep unknowns/limitations "
        "qualitative. Use qualitative text when no eligible anchor exists. Plans are proposed "
        "thresholds/dates, never company facts, and belong only to conditions or suggested checks. "
        "A predicate binding must reference the plan beside its condition text. Existing fact scope, "
        "reply/argument references, validation and invocation budgets remain unchanged."
    )
    if premises:
        text += (
            "\nEach statement, rationale, judgement, answer and alternative_explanation uses its own "
            "{text,premise:{observation_ids,pending_questions}} object. Select observations only from "
            "factual_observations and within the facts cited by that same item. Never invent or rewrite "
            "observations. Interpretations are not verified facts: put every unsupported premise into "
            "qualitative pending_questions phrased as questions. A direction claim needs a matching "
            "comparison observation; a revenue reference does not prove expense growth. Maintained/revised "
            "claims, supporting arguments and rated judgements require observations. Overall key_claim_ids "
            "must cover its observations. Empty observations are only for unresolved/open questions. "
            "Do not type host labels or claim semantic verification."
        )
    return text


def _invalid():
    raise InlineBindingError("inline binding payload invalid")


def _structured(path):
    parts = path.split(".")
    if len(parts) == 3 and parts[0] == "challenges" and parts[-1] == "observation_date":
        return True
    check = (len(parts) == 6 and parts[0] == "hypotheses" and parts[2] == "conditions"
             or len(parts) == 4 and parts[0] == "challenges")
    return check and parts[-2] == "check" and parts[-1] in {
        "current", "base", "metric_id", "predicate"}


def _local_schema(model):
    # All parameter types/bounds still come from the canonical Python schemas.
    result = model.model_json_schema()
    result["properties"].pop("field_path")
    result["required"] = [key for key in result.get("required", []) if key != "field_path"]
    return result


def inline_prompt_schema(base_schema, *, premises=True):
    """Derive path-free prompt schemas, including context-specific shared refs."""
    source = deepcopy(base_schema)
    definitions = source.pop("$defs", {})
    output = {
        "title": "InlineStageEnvelopeV1", "type": "object", "additionalProperties": False,
        "properties": {}, "required": ["proposal"], "$defs": {
            "InlineLocalPlanV1": _local_schema(NumericPlanV1),
            "InlineLocalBindingV1": _local_schema(NumericStructuredBindingV1),
        },
    }
    if premises:
        output["$defs"]["InlineLocalPremiseV1"] = _local_schema(PremiseBindingV1)
    cache = {}

    def ref(value, path, depth):
        if not value.startswith("#/$defs/") or value[8:] not in definitions:
            _invalid()
        key = value, path
        if key not in cache:
            name = f"Inline_{len(cache)}_{value[8:]}"
            cache[key] = "#/$defs/" + name
            output["$defs"][name] = visit(definitions[value[8:]], path, depth + 1, wrap=False)
        return cache[key]

    def plans():
        return {"type": "array", "items": {"$ref": "#/$defs/InlineLocalPlanV1"},
                "maxItems": 64, "default": []}

    def visit(node, path=(), depth=0, *, wrap=True):
        if depth > 64:
            _invalid()
        node = deepcopy(node)
        dotted = ".".join("0" if part == "*" else part for part in path)
        if wrap and _structured(dotted):
            nullable = [x for x in node.get("anyOf", []) if x.get("type") == "null"]
            if nullable:
                node["anyOf"] = [x for x in node["anyOf"] if x.get("type") != "null"]
                node.pop("default", None)
            result = {"type": "object", "additionalProperties": False,
                "properties": {"value": visit(node, path, depth + 1, wrap=False),
                               "binding": {"$ref": "#/$defs/InlineLocalBindingV1"}},
                "required": ["value", "binding"]}
            if _plan_allowed(dotted):
                result["properties"]["plans"] = plans()
            return {"anyOf": [result, {"type": "null"}], "default": None} if nullable else result
        is_text = path and path[-1] in _TEXT_FIELDS
        required_premise = premises and premise_path(dotted)
        if wrap and is_text and (required_premise or _plan_allowed(dotted)):
            result = {"type": "object", "additionalProperties": False,
                "properties": {"text": visit(node, path, depth + 1, wrap=False)}, "required": ["text"]}
            if required_premise:
                result["properties"]["premise"] = {"$ref": "#/$defs/InlineLocalPremiseV1"}
                result["required"].append("premise")
            if _plan_allowed(dotted):
                result["properties"]["plans"] = plans()
            return result if required_premise else {"anyOf": [visit(node, path, depth + 1, wrap=False), result]}
        if "$ref" in node:
            node["$ref"] = ref(node["$ref"], path, depth)
        if "properties" in node:
            node["properties"] = {key: visit(child, (*path, key), depth + 1)
                                  for key, child in node["properties"].items()}
        if isinstance(node.get("items"), dict):
            node["items"] = visit(node["items"], (*path, "*"), depth + 1)
        for key in ("anyOf", "oneOf", "allOf"):
            if key in node:
                node[key] = [visit(child, path, depth + 1, wrap=False) for child in node[key]]
        discriminator = node.get("discriminator")
        if isinstance(discriminator, dict) and "mapping" in discriminator:
            discriminator["mapping"] = {key: ref(value, path, depth)
                                         for key, value in discriminator["mapping"].items()}
        return node

    output["properties"]["proposal"] = visit(source)
    return output


def decode_inline_envelope(value, *, premises=True):
    """Generate canonical bindings without choosing evidence or fixing addresses.

    Canonical proposal/schema, item isolation, scope, quantity and proof checks
    remain downstream. No raw response or new input format enters saved proofs.
    """
    if not isinstance(value, dict) or set(value) - {"proposal", "gaps"} or not isinstance(value.get("proposal"), dict):
        _invalid()

    def no_paths(node, depth=0):
        if depth > 64:
            _invalid()
        if isinstance(node, dict):
            if "field_path" in node:
                _invalid()
            for child in node.values():
                no_paths(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                no_paths(child, depth + 1)

    no_paths(value)
    result = {"proposal": None, "plans": [], "structured_bindings": []}
    if premises:
        result["premises"] = []
    if "gaps" in value:
        result["gaps"] = deepcopy(value["gaps"])

    def entry(raw, path):
        if not isinstance(raw, dict):
            _invalid()
        return {**deepcopy(raw), "field_path": path}

    def local_plans(node, path):
        raw = node.get("plans", [])
        if not isinstance(raw, list) or raw and not _plan_allowed(path):
            _invalid()
        result["plans"].extend(entry(item, path) for item in raw)

    def walk(node, parts=(), *, text=False, unwrap=True):
        path = ".".join(parts)
        if unwrap and _structured(path) and isinstance(node, dict) and "value" in node:
            if set(node) - {"value", "binding", "plans"}:
                _invalid()
            if "binding" in node:
                result["structured_bindings"].append(entry(node["binding"], path))
            local_plans(node, path)
            return walk(node["value"], parts, unwrap=False)
        if text and isinstance(node, dict) and "text" in node:
            if set(node) - {"text", "premise", "plans"}:
                _invalid()
            if "premise" in node:
                if not premises:
                    _invalid()
                if premise_path(path):
                    result["premises"].append(entry(node["premise"], path))
                # Existing non-premise text ignores unused annotation contents.
            local_plans(node, path)
            return deepcopy(node["text"])
        if isinstance(node, dict):
            return {key: walk(child, (*parts, key), text=key in _TEXT_FIELDS)
                    for key, child in node.items()}
        if isinstance(node, list):
            return [walk(child, (*parts, str(index)), text=text) for index, child in enumerate(node)]
        return deepcopy(node)

    result["proposal"] = walk(value["proposal"])
    for key in ("plans", "structured_bindings", *(("premises",) if premises else ())):
        result[key].sort(key=lambda item: (item["field_path"], str(item.get("alias", ""))))
    return result
