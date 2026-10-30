"""Closed diagnostic metadata; never retain response text or exception messages."""

import json

from pydantic import ValidationError

from tradingagents.agents.schemas._native_stage import SynthesisReferenceError
from tradingagents.execution.budget import BudgetExhausted

_BINDINGS = {
    "specialist reference outside supplied facts": "specialist_fact_reference",
    "condition references evidence outside its hypothesis": "condition_evidence_reference",
    "condition references a metric outside its hypothesis": "condition_metric_reference",
    "synthesis dimension references outside allowed claims": "dimension_claim_reference",
    "synthesis key claim invalid": "key_claim_reference",
    "synthesis primary challenge invalid": "primary_challenge_reference",
    "synthesis challenge coverage invalid": "challenge_coverage",
    "synthesis must contain each mode dimension exactly once": "dimension_coverage",
    "synthesis contains an invalid claim reference": "claim_reference",
    "synthesis uses facts from the wrong dimension": "dimension_fact_reference",
    "operating judgement requires cited financial evidence": "operating_financial_reference",
    "holding judgement requires cited original thesis": "holding_thesis_reference",
    "duplicate JSON key": "duplicate_json_key",
    "gap cutoff changed": "gap_cutoff_changed",
    "gap role changed": "gap_role_changed",
    "gap target outside supplied scope": "gap_target_scope",
    "critical economic challenge or missing anchor prohibits favorable": "investment_stance_ceiling",
}
_UPSTREAM_CODES = {
    "invalid_request_error", "context_length_exceeded", "insufficient_quota",
    "rate_limit_exceeded", "authentication_error", "model_not_found",
}
_PUBLIC_BINDINGS = {
    "Value error, revised argument must cite the reply's facts": "argument_reply_fact_reference",
    "Value error, judgement condition does not match the public hypothesis": "judgement_condition_reference",
    "Value error, adjudication cannot strengthen the specialist's reply": "adjudication_disposition_binding",
    "Value error, adjudication references another challenge's reply": "adjudication_reply_reference",
    "Value error, every challenge requires a separate adjudication": "adjudication_coverage",
    "Value error, investment argument contains invalid claims": "argument_claim_reference",
    "Value error, investment argument contains invalid replies": "argument_response_reference",
    "Value error, withdrawn or revised assertions cannot support the conclusion": "excluded_claim_reference",
    "Value error, duplicate or dangling research reference": "public_reference_integrity",
}


def _fields(schema):
    names = set()
    def visit(value):
        if isinstance(value, dict):
            names.update(value.get("properties", {}))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(schema.model_json_schema())
    return names


def safe_model_diagnostic(stage, phase, category, exc, *, schema=None, envelope_schema=None, response=None):
    """Only host-owned labels, declared field names and numeric metadata escape."""
    value = {"version": 1, "stage": stage, "phase": phase, "category": category}
    status = getattr(exc, "status_code", None)
    diagnostic = getattr(exc, "diagnostic", None)
    if diagnostic is not None:
        status = diagnostic.upstream_status
    if type(status) is int and 100 <= status <= 599:
        value["upstream_status"] = status
    code = getattr(exc, "code", None)
    if diagnostic is not None:
        code = diagnostic.upstream_code
    if isinstance(code, str) and code in _UPSTREAM_CODES:
        value["upstream_code"] = code
    if isinstance(exc, SynthesisReferenceError) or getattr(exc, "section_issues", None):
        sections = exc.issues if isinstance(exc, SynthesisReferenceError) else exc.section_issues
        value.update(category="reference_validation", detail_code="section_validation",
                     detail_codes=sorted({code for code, _ in sections}),
                     **{"synthesis_reference_issues" if stage == "synthesis" else "section_reference_issues":
                        [{"code": code, "path": list(path)} for code, path in sections[:8]]})
        if getattr(exc, "field_name", None):
            from tradingagents.research.numeric_narrative import _TEXT_FIELDS
            if exc.field_name in _TEXT_FIELDS:
                value["field_name"] = exc.field_name
    elif isinstance(exc, json.JSONDecodeError):
        value.update(category="invalid_json", json_error_offset=exc.pos)
    elif isinstance(exc, BudgetExhausted):
        value.update(category="budget_refused", budget_bucket=exc.hit.bucket.value,
                     budget_limit=exc.hit.limit, budget_consumed=exc.hit.consumed)
    elif getattr(exc, "code", None) in {
        "inline_binding_shape", "numeric_literal_unbound", "numeric_anchor_unknown", "numeric_anchor_scope",
        "numeric_basis_mismatch", "numeric_plan_mismatch", "numeric_render_limit",
        "premise_binding_invalid", "premise_binding_missing", "premise_observation_unknown",
        "premise_observation_scope", "premise_support_missing",
        "numeric_manifest_binding", "numeric_catalog_limit",
        "numeric_proposal_schema", "numeric_envelope_schema", "numeric_catalog_invalid",
        "numeric_cutoff_invalid", "numeric_condition_reference", "numeric_receipt_invalid",
        "challenge_review_coverage", "challenge_schema_invalid", "challenge_fact_reference", "challenge_check_scope",
        "challenge_future_date", "challenge_check_unavailable", "challenge_requirement_invalid",
        "challenge_target_reference", "challenge_condition_reference",
    }:
        value.update(category="reference_validation", detail_code=exc.code)
        from tradingagents.research.numeric_narrative import BINDING_ISSUES
        if getattr(exc, "binding_issue", None) in BINDING_ISSUES:
            value["binding_issue"] = exc.binding_issue
        from tradingagents.research.numeric_narrative import _TEXT_FIELDS
        if getattr(exc, "field_name", None) in _TEXT_FIELDS:
            value["field_name"] = exc.field_name
    elif isinstance(exc, TimeoutError) or type(exc).__name__ in {"APITimeoutError", "ReadTimeout", "ConnectTimeout"}:
        value["category"] = "request_timeout"
    elif type(exc).__name__ == "APIConnectionError":
        value["category"] = "transport_failed"
    elif isinstance(exc, ValidationError) and schema is not None:
        names = _fields(schema)
        if envelope_schema is not None:
            names.update(_fields(envelope_schema))
        value["category"] = "schema_validation"
        issues = []
        # Context is inspected only for whitelisted integer bounds below; never
        # copy validator messages, exception objects or arbitrary context values.
        for issue in exc.errors(include_input=False, include_context=True, include_url=False)[:8]:
            path = [part if type(part) is int or part in names else "<undeclared>"
                    for part in issue["loc"]]
            # Custom validators can define arbitrary error types; only built-in
            # schema codes are exposed, with a fixed fallback for custom errors.
            code = issue["type"]
            allowed = {"missing", "extra_forbidden", "too_long", "too_short", "string_too_long",
                       "string_too_short", "literal_error", "value_error", "int_parsing",
                       "float_parsing", "string_type", "tuple_type", "list_type", "model_type",
                       "date_parsing", "date_from_datetime_parsing", "enum", "greater_than_equal",
                       "less_than_equal", "finite_number"}
            item = {"path": path, "code": code if code in allowed else "validation_error"}
            if code in {"too_long", "too_short", "string_too_long", "string_too_short"}:
                bounds = (issue.get("ctx") or {})
                for target, source in (("limit", "max_length" if "long" in code else "min_length"),
                                       ("actual", "actual_length")):
                    number = bounds.get(source)
                    if type(number) is int and number >= 0:
                        item[target] = number
            issues.append(item)
            if not issue["loc"] and code == "value_error" and issue["msg"] in _PUBLIC_BINDINGS:
                value.update(category="reference_validation", detail_code=_PUBLIC_BINDINGS[issue["msg"]])
        value["issues"] = issues
    elif isinstance(exc, ValueError) and str(exc) in _BINDINGS:
        value.update(category="invalid_json" if str(exc) == "duplicate JSON key" else "reference_validation",
                     detail_code=_BINDINGS[str(exc)])
    locations = getattr(exc, "validation_locations", ())
    if locations:
        from tradingagents.agents.schemas._numeric_narrative import NumericCatalogV1
        from tradingagents.agents.schemas._numeric_stage import (
            NumericFieldProofV1,
            NumericStageEnvelopeV1,
        )
        names = {"numeric_catalog", "numeric_analysis_date", "change_conditions", "text"}
        for model in (schema, envelope_schema, NumericStageEnvelopeV1, NumericFieldProofV1, NumericCatalogV1):
            if model is not None:
                names.update(_fields(model))
        value["issues"] = [{"path": [p if type(p) is int or p in names else "<undeclared>" for p in path]}
                           for path in locations[:8]]
    metadata = getattr(response, "response_metadata", None)
    if (isinstance(metadata, dict) and isinstance(metadata.get("finish_reason"), str)
            and metadata["finish_reason"] in {"length", "stop", "content_filter", "tool_calls"}):
        value["finish_reason"] = metadata["finish_reason"]
    return value
