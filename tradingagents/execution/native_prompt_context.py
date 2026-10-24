"""Smaller model views and exact reference choices; admission stays canonical."""

from copy import deepcopy


def legacy_check_schema(schema):
    """Retain the released check enum for prompts without the new policy."""
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "enum" and isinstance(value, list) and "financial_baseline" in value:
                schema[key] = [item for item in value if item not in {"financial_baseline", "cashflow_comparison"}]
            else:
                legacy_check_schema(value)
    elif isinstance(schema, list):
        for value in schema:
            legacy_check_schema(value)
    return schema


def compact_synthesis_context(context, *, delivery=False):
    value = deepcopy(context)
    record = value["record"]
    # Facts already contain the admitted observations. Raw source bodies repeat
    # them at length; preserve provenance and the complete claims instead.
    record["evidence"] = [{key: item[key] for key in (
        "evidence_id", "source_name", "source_kind" if delivery else "source_tier", "published_at",
        "usable_as_of", "availability", "public_url", "limitations") if key in item}
        for item in record["evidence"]]
    if record.get('schema_version') == 'research-record-v2':
        record['search_batches'] = [{
            'batch_id': batch['batch_id'], 'input_snapshot_id': batch['input_snapshot_id'],
            'tasks': [{'kind': r['kind'], 'round_id': r['round_id'], 'gap_id': r['gap_id'],
                       'capability': r['capability']} for r in batch['requests']],
            'stop_reasons': batch['stop_reasons']}
            for batch in record['search_batches']]
    # Verification contains a second full copy of the same record. Its actual
    # observations/outcomes are also supplied in local_check_assessments.
    if isinstance(value.get("verification"), dict):
        value["verification"].pop("record", None)
    return value


def reference_schema(schema, stage, context, *, delivery=False, complete_sections=False):
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
        from tradingagents.research.record_codec import parse_research_record
        # Derive excluded IDs using the complete canonical context before it is
        # compacted; the prompt itself is not a substitute for a saved record.
        record = parse_research_record(context["record"])
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
        if complete_sections:
            value["properties"]["dimensions"].update(minItems=len(dimensions), maxItems=len(dimensions))
            challenges = sorted(c.challenge_id for c in record.challenges)
            for field, definition in (("adjudications", "ChallengeAdjudicationV1"),
                                      ("challenge_assessments", "ChallengeAssessmentV1")):
                if field not in value.get("required", []):
                    value.setdefault("required", []).append(field)
                value["properties"][field].update(minItems=len(challenges), maxItems=len(challenges))
                if challenges:
                    definitions[definition]["properties"]["challenge_id"]["enum"] = challenges
    return value
