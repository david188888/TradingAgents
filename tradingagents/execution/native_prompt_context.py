"""Smaller model views and exact reference choices; admission stays canonical."""

from copy import deepcopy


def compact_synthesis_context(context, *, delivery=False):
    value = deepcopy(context)
    record = value["record"]
    # Facts already contain the admitted observations. Raw source bodies repeat
    # them at length; preserve provenance and the complete claims instead.
    record["evidence"] = [{key: item[key] for key in (
        "evidence_id", "source_name", "source_kind" if delivery else "source_tier", "published_at",
        "usable_as_of", "availability", "public_url", "limitations") if key in item}
        for item in record["evidence"]]
    # Verification contains a second full copy of the same record. Its actual
    # observations/outcomes are also supplied in local_check_assessments.
    if isinstance(value.get("verification"), dict):
        value["verification"].pop("record", None)
    return value


def reference_schema(schema, stage, context, *, delivery=False):
    """Enumerate only supplied choices; never add a fact or change validation."""
    value = deepcopy(schema)

    def choices(field, ids):
        ids = sorted(set(ids))
        if ids:
            field["items"] = {"type": "string", "enum": ids}
        else:
            field["maxItems"] = 0

    definitions = value.get("$defs", {})
    if stage in {"operating_quality", "event_context", "market_context"}:
        choices(definitions["HypothesisProposalV1"]["properties"]["supporting_fact_ids"],
                [fact["claim_id"] for fact in context["facts"]])
    elif stage == "synthesis":
        if delivery:
            for definition, fields in (("JudgementConditionV1", ("text",)),
                                       ("ChallengeAdjudicationV1", ("response_id", "disposition"))):
                target = definitions[definition]
                for field in fields:
                    target["properties"].pop(field, None)
                target["required"] = [field for field in target.get("required", []) if field not in fields]
        from tradingagents.agents.schemas._research_dialogue import excluded_support
        from tradingagents.agents.schemas._research_record import ResearchRecordV1
        # Derive excluded IDs using the complete canonical context before it is
        # compacted; the prompt itself is not a substitute for a saved record.
        record = ResearchRecordV1.model_validate(context["record"])
        excluded = excluded_support(record)
        allowed = [c.claim_id for c in record.claims if c.kind != "unknown" and c.claim_id not in excluded]
        choices(value["properties"]["key_claim_ids"], allowed)
        choices(definitions["InvestmentArgumentV1"]["properties"]["claim_ids"], allowed)
        dimensions = []
        for name, ids in context["dimension_claim_ids"].items():
            dimension = deepcopy(definitions["DimensionAssessmentV1"])
            dimension["properties"]["dimension"] = {"const": name, "type": "string"}
            choices(dimension["properties"]["claim_ids"], ids)
            dimensions.append(dimension)
        value["properties"]["dimensions"]["items"] = {"oneOf": dimensions}
    return value
