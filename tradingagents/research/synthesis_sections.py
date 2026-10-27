"""Validated synthesis siblings, immutable main receipts and deterministic fallback."""

import hashlib
from copy import deepcopy

import rfc8785
from pydantic import ValidationError

from tradingagents.agents.schemas._native_stage import (
    SynthesisProposalV3,
    validate_synthesis_reference_surface,
)
from tradingagents.agents.schemas._numeric_stage import NumericStageEnvelopeV1
from tradingagents.agents.schemas._research_assessment import (
    ResearchAssessmentV3,
    SynthesisDimensionV1,
)
from tradingagents.agents.schemas._synthesis_sections import (
    SYNTHESIS_SECTIONS_POLICY,
    SectionedSynthesisProofV1,
    SynthesisAdjudicationV1,
    SynthesisConditionsV1,
    SynthesisOverallV1,
    SynthesisSectionsV1,
)
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.research.record_codec import parse_research_record

UNFINISHED_JUDGEMENT = "综合未完成；已保留通过校验的分段，暂未形成总体评级。"
UNFINISHED_NEXT = "完成标为未完成的综合分段，再复核总体判断。"
UNFINISHED_DIMENSION = "本维度综合分段未完成；已有事实与专项观点仍可查阅。"
UNFINISHED_ADJUDICATION = "本条综合裁决未完成；保留原挑战、代码核查与专项回应。"


def section_ids(record):
    from tradingagents.research.native_versions import UNIFIED_DIMENSIONS
    return [*("dimension:" + name for name in UNIFIED_DIMENSIONS),
            *("adjudication:" + c.challenge_id for c in record.challenges), "overall", "conditions"]


def fragment_schema(section_id):
    if section_id.startswith("dimension:"):
        return SynthesisDimensionV1
    if section_id.startswith("adjudication:"):
        return SynthesisAdjudicationV1
    return {"overall": SynthesisOverallV1, "conditions": SynthesisConditionsV1}[section_id]


def unfinished_sections(delivery):
    return {s.section_id for s in delivery.sections if s.status == "unavailable"}


def rating_blocked(record, delivery):
    missing = unfinished_sections(delivery)
    return "overall" in missing or any("adjudication:" + c.challenge_id in missing
                                       for c in record.challenges if c.severity == "critical")


def _fallback(record):
    from tradingagents.agents.schemas._research_assessment import DimensionAssessmentV1
    from tradingagents.research.native_versions import UNIFIED_DIMENSIONS
    return {
        "judgement": UNFINISHED_JUDGEMENT, "investment_stance": "insufficient_evidence",
        "next_check": UNFINISHED_NEXT, "key_claim_ids": [], "primary_challenge_id": None,
        "supporting_arguments": [], "opposing_arguments": [],
        "dimensions": [DimensionAssessmentV1(dimension=name, status="unresolved",
            judgement=UNFINISHED_DIMENSION, limitations=("synthesis_section_unavailable",)).model_dump(mode="json")
            for name in UNIFIED_DIMENSIONS],
        "adjudications": [{"challenge_id": r.challenge_id, "response_id": r.response_id,
                           "disposition": r.disposition, "rationale": UNFINISHED_ADJUDICATION}
                          for r in record.dialogue.responses],
        "change_conditions": [{"hypothesis_id": h.hypothesis_id, "invalidation_index": 0,
                               "text": h.invalidation_conditions[0]} for h in record.hypotheses[:3]],
        "challenge_assessments": [{"challenge_id": c.challenge_id, "outcome": "unresolved",
                                   "rationale": "局部核查由代码保存；经济挑战仍需判断。"} for c in record.challenges],
    }


def assemble_sections(record, receipts, failures):
    value = _fallback(record)
    accepted = {item["section_id"]: item for item in receipts}
    for item in receipts:
        proposal = item["proposal"]
        if item["section_id"].startswith("dimension:"):
            name = item["section_id"].split(":", 1)[1]
            index = next(i for i, d in enumerate(value["dimensions"]) if d["dimension"] == name)
            value["dimensions"][index] = proposal["dimensions"][0]
        elif item["section_id"].startswith("adjudication:"):
            cid = item["section_id"].split(":", 1)[1]
            index = next(i for i, a in enumerate(value["adjudications"]) if a["challenge_id"] == cid)
            value["adjudications"][index] = proposal["adjudications"][0]
        else:
            value.update(proposal)
    value["synthesis_sections"] = SynthesisSectionsV1(sections=[
        {"section_id": key, "status": "accepted", "phase": accepted[key]["phase"]} if key in accepted else
        {"section_id": key, "status": "unavailable", "reason_code": failures.get(key, "missing_section")}
        for key in section_ids(record)]).model_dump(mode="json")
    return SynthesisProposalV3.model_validate(value).model_dump(mode="json")


def validate_section_proposal(record, proposal, context):
    """Use the same complete record gates as ordinary synthesis admission."""
    from tradingagents.research.minimum_evidence import challenge_assessments
    from tradingagents.research.native_policy import gate_dimensions
    from tradingagents.research.unified_synthesis import investment_fields
    model = SynthesisProposalV3.model_validate(proposal)
    for dimension in model.dimensions:
        if not set(dimension.claim_ids) <= set(context["dimension_claim_ids"][dimension.dimension]):
            raise ValueError("synthesis dimension references outside allowed claims")
    dimensions = gate_dimensions(record, model.dimensions, scoped=True, valuation=True, sections=model.synthesis_sections)
    fields = investment_fields(record, model, dimensions)
    fields.pop("force_insufficient", None)
    assessment = ResearchAssessmentV3(input_snapshot_id=record.snapshots[-1].snapshot_id,
        research_question=context["question"], judgement=model.judgement, next_check=model.next_check,
        key_claim_ids=model.key_claim_ids, primary_challenge_id=model.primary_challenge_id,
        dimensions=dimensions, challenge_assessments=challenge_assessments(record),
        completeness="partial", quality="LOW_CONFIDENCE", **fields)
    parse_research_record({**record.model_dump(mode="json"), "numeric_attribution": None,
                                   "assessment": assessment.model_dump(mode="json")})


def _extract(envelope, section_id):
    raw = envelope["proposal"]
    prefix = None
    if section_id.startswith(("dimension:", "adjudication:")):
        dimension = section_id.startswith("dimension:")
        key, identifier = ("dimensions", "dimension") if dimension else ("adjudications", "challenge_id")
        target = section_id.split(":", 1)[1]
        items = raw.get(key, [])
        if not isinstance(items, list):
            raise ValueError("section shape invalid")
        matches = [(i, item) for i, item in enumerate(items) if isinstance(item, dict) and item.get(identifier) == target]
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError("duplicate section")
        index, item = matches[0]
        value, prefix = {key: [deepcopy(item)]}, (f"{key}.{index}.", f"{key}.0.")
    else:
        keys = fragment_schema(section_id).model_fields
        value = {key: deepcopy(raw[key]) for key in keys if key in raw}
        if not value:
            return None
    result = {"proposal": value, "plans": [], "structured_bindings": []}
    if "premises" in envelope:
        result["premises"] = []
    for key in ("plans", "structured_bindings", *(("premises",) if "premises" in envelope else ())):
        for binding in envelope.get(key, []):
            path = binding["field_path"]
            if prefix and path.startswith(prefix[0]):
                result[key].append({**binding, "field_path": prefix[1] + path[len(prefix[0]):]})
            elif prefix is None and path.split(".")[0] in value:
                result[key].append(deepcopy(binding))
    return result


def parse_sections(envelope, context, *, phase, previous=None, on_progress=None):
    from tradingagents.research.numeric_narrative import (
        NumericNarrativeError,
        compile_numeric_stage,
        numeric_validation_context,
    )
    context = numeric_validation_context(context, sectioned=True)
    from tradingagents.research.factual_premises import discard_redundant_bindings, premise_enabled
    if premise_enabled(context):
        envelope = discard_redundant_bindings(envelope, partitioned_collections=("dimensions", "adjudications"))
    # Invalid shared JSON/envelope shape is not salvaged. No unowned metadata.
    envelope = NumericStageEnvelopeV1.model_validate(envelope).model_dump(mode="json")
    if set(envelope["proposal"]) - (SynthesisProposalV3.model_fields.keys() - {"synthesis_sections"}):
        raise ValueError("unknown synthesis fields")
    record = parse_research_record(context["record"])
    receipts = deepcopy(previous["receipts"]) if previous else []
    accepted = {r["section_id"] for r in receipts}
    failures = dict(previous["failures"]) if previous else {}
    # Overall depends on dimension gates, so validate it after other fragments.
    order = [key for key in section_ids(record) if key != "overall"] + ["overall"]
    for section_id in order:
        if section_id in accepted:
            continue
        try:
            fragment = _extract(envelope, section_id)
            if fragment is None:
                failures[section_id] = "missing_section"
                continue
            if section_id.startswith("dimension:"):
                validate_synthesis_reference_surface(fragment["proposal"], context["dimension_claim_ids"], [])
            proposal, proof = compile_numeric_stage("synthesis", fragment, context, fragment_schema(section_id))
            receipt = {"section_id": section_id, "phase": phase, "proposal": proposal, "proof": proof}
            if _token_count([*receipts, receipt]) > 64:
                raise NumericNarrativeError("numeric_render_limit")
            candidate = assemble_sections(record, [*receipts, receipt], failures)
            validate_section_proposal(record, candidate, context)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            failures[section_id] = (exc.code if isinstance(exc, NumericNarrativeError) else
                                    "schema_validation" if isinstance(exc, (ValidationError, TypeError)) else "reference_validation")
        else:
            receipts.append(receipt)
            accepted.add(section_id)
            failures.pop(section_id, None)
        if on_progress is not None and receipts:
            on_progress({"policy": SYNTHESIS_SECTIONS_POLICY, "context_sha256": _context_hash(context),
                "receipts": deepcopy(receipts), "failures": {key: failures.get(key, "missing_section")
                    for key in section_ids(record) if key not in accepted}})
    return {"policy": SYNTHESIS_SECTIONS_POLICY, "context_sha256": _context_hash(context),
            "receipts": receipts, "failures": failures}


def _token_count(receipts):
    return sum(segment["kind"] in {"num", "meta", "plan"} for receipt in receipts
               for field in receipt["proof"]["fields"] for segment in field["segments"])


def _context_hash(context):
    from tradingagents.research.numeric_narrative import numeric_validation_context
    # Match run-store numeric canonicalization (e.g. 2.0 -> 2) while retaining
    # exact source-content strings and frozen decimal anchor values.
    return hashlib.sha256(rfc8785.dumps(numeric_validation_context(context, sectioned=True))).hexdigest()


def candidate_result(candidate, context):
    """Replay accepted siblings, derive every placeholder and final text afresh."""
    from tradingagents.research.numeric_narrative import (
        numeric_validation_context,
        validate_numeric_stage,
    )
    context = numeric_validation_context(context, sectioned=True)
    if candidate.get("policy") != SYNTHESIS_SECTIONS_POLICY or candidate["context_sha256"] != _context_hash(context):
        raise ValueError("synthesis section context changed")
    record = parse_research_record(context["record"])
    expected = section_ids(record)
    receipts = candidate["receipts"]
    if not receipts:
        raise ValueError("no accepted synthesis sections")
    if _token_count(receipts) > 64:
        raise ValueError("synthesis section token limit exceeded")
    keys = [r["section_id"] for r in receipts]
    if len(set(keys)) != len(keys) or set(keys) | set(candidate["failures"]) != set(expected) or set(keys) & set(candidate["failures"]):
        raise ValueError("synthesis section coverage changed")
    for receipt in receipts:
        validate_numeric_stage("synthesis", receipt["proposal"], receipt["proof"], context,
                               fragment_schema(receipt["section_id"]))
    proposal = assemble_sections(record, receipts, candidate["failures"])
    validate_section_proposal(record, proposal, context)
    fields = []
    for receipt in receipts:
        prefix = None
        section = receipt["section_id"]
        if section.startswith("dimension:"):
            index = next(i for i, d in enumerate(proposal["dimensions"]) if d["dimension"] == section.split(":", 1)[1])
            prefix = ("dimensions.0.", f"dimensions.{index}.")
        elif section.startswith("adjudication:"):
            index = next(i for i, a in enumerate(proposal["adjudications"]) if a["challenge_id"] == section.split(":", 1)[1])
            prefix = ("adjudications.0.", f"adjudications.{index}.")
        for field in receipt["proof"]["fields"]:
            field = deepcopy(field)
            if prefix:
                if not field["path"].startswith(prefix[0]):
                    raise ValueError("synthesis fragment field outside section")
                field["path"] = prefix[1] + field["path"][len(prefix[0]):]
            fields.append(field)
    proof = SectionedSynthesisProofV1(context_sha256=_context_hash(context),
        proposal_sha256=canonical_sha256(proposal), receipts=receipts,
        delivery=proposal["synthesis_sections"], fields=fields).model_dump(mode="json")
    return proposal, proof


def validate_sectioned_proof(proposal, proof, context):
    saved = SectionedSynthesisProofV1.model_validate(proof).model_dump(mode="json")
    candidate = {"policy": SYNTHESIS_SECTIONS_POLICY, "context_sha256": saved["context_sha256"],
                 "receipts": saved["receipts"], "failures": {s["section_id"]: s["reason_code"]
                     for s in saved["delivery"]["sections"] if s["status"] == "unavailable"}}
    actual, rebuilt = candidate_result(candidate, context)
    if actual != proposal or rebuilt != saved:
        raise ValueError("synthesis section proof changed")


def saved_section_candidate(journal, context):
    if journal.state.get("native.reference_schema.synthesis") != 3:
        return None
    for phase in ("repair", "main"):
        candidate = (journal.ledger.cached_result("native.synthesis_sections." + phase)
                     or journal.state.get("native.synthesis_sections.progress." + phase))
        if candidate is not None:
            if candidate.get("prompt_sha256") != journal.state.get("native.prompt.synthesis"):
                raise ValueError("synthesis section prompt changed")
            if not candidate["receipts"]:
                continue
            return candidate_result(candidate, context)
    return None


def failure_issues(candidate, record):
    result = []
    expected = section_ids(record)
    for key in expected:
        if key not in candidate["failures"]:
            continue
        if key.startswith("dimension:"):
            path = ("dimensions", expected.index(key))
        elif key.startswith("adjudication:"):
            path = ("adjudications", expected.index(key) - 4)
        else:
            path = (key,)
        result.append((candidate["failures"][key], path))
    return result


def request_schema(schema, context, targets=None):
    """The host owns delivery metadata and local check outcomes, not the model."""
    schema = deepcopy(schema)
    properties = schema["properties"]
    properties.pop("challenge_assessments", None)
    schema["required"] = [key for key in schema.get("required", []) if key != "challenge_assessments"]
    if targets is None:
        if "change_conditions" not in schema["required"]:
            schema["required"].append("change_conditions")
        return schema
    dimensions = [key.split(":", 1)[1] for key in targets if key.startswith("dimension:")]
    adjudications = [key.split(":", 1)[1] for key in targets if key.startswith("adjudication:")]
    keep = set(SynthesisOverallV1.model_fields) if "overall" in targets else set()
    if "conditions" in targets:
        keep.add("change_conditions")
    if dimensions:
        keep.add("dimensions")
        field = properties["dimensions"]
        field["items"]["oneOf"] = [item for item in field["items"]["oneOf"]
            if item["properties"]["dimension"]["const"] in dimensions]
        field.update(minItems=len(dimensions), maxItems=len(dimensions))
    if adjudications:
        keep.add("adjudications")
        properties["adjudications"].update(minItems=len(adjudications), maxItems=len(adjudications))
        schema["$defs"]["ChallengeAdjudicationV1"]["properties"]["challenge_id"]["enum"] = adjudications
    schema["properties"] = {key: value for key, value in properties.items() if key in keep}
    schema["required"] = sorted(keep)
    return schema
