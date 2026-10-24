"""Numeric policy gates shared by execution, publication and saved readers."""

import hashlib
import json
from copy import deepcopy

from tradingagents.agents.schemas._numeric_attribution import NumericAttributionV1
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.research.native_versions import NUMERIC_NARRATIVE_POLICY
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict

CATALOG_LIMIT_NOTICE = "数值目录超过容量，模型输出仅保留定性表述。"


def numeric_enabled(identity):
    policy = identity.get("numeric_narrative_policy")
    if policy is not None and policy != NUMERIC_NARRATIVE_POLICY:
        raise CatalystCheckpointConflict("native numeric policy mismatch")
    return policy is not None


def stage_schema(stage, identity=None):
    from tradingagents.agents.schemas._native_stage import (
        ChallengesProposalV2,
        ChallengesProposalV3,
        SpecialistProposalV1,
        SynthesisProposalV3,
    )
    from tradingagents.agents.schemas._research_dialogue import ResponsesProposalV1
    from tradingagents.agents.schemas._research_focus import FocusProposalV1

    if stage.startswith('search_review.'):
        from tradingagents.agents.schemas._search import SearchReviewProposalV1
        return SearchReviewProposalV1
    if stage in {"operating_quality", "event_context", "market_context"}:
        return SpecialistProposalV1
    if stage == "challenge":
        return ChallengesProposalV3 if (identity or {}).get("challenge_check_policy") else ChallengesProposalV2
    if stage.startswith("response_") and stage.removeprefix("response_") in {
        "operating_quality", "event_context", "market_context",
    }:
        return ResponsesProposalV1
    if stage == "synthesis":
        return SynthesisProposalV3
    if stage == "focus_response":
        return FocusProposalV1
    raise CatalystCheckpointConflict("native numeric stage mismatch")


def remember_numeric(journal, stage, proposal, proof, context):
    from tradingagents.research.numeric_narrative import (
        numeric_validation_context,
        validate_numeric_stage,
    )
    validate_numeric_stage(stage, proposal, proof, context, stage_schema(stage, context))
    journal.ledger.record_result("native.numeric.accepted." + stage, {
        "stage": stage, "proposal": proposal, "proof": proof,
        "context": numeric_validation_context(context, sectioned=proof.get("kind") == "synthesis-sections-v1"),
    })


def validate_cached_numeric(journal, stage, proposal, context, schema, *, allow_candidate=False):
    if not numeric_enabled(journal.state["identity"]):
        return
    from tradingagents.research.numeric_narrative import validate_numeric_stage
    try:
        saved = journal.ledger.cached_result("native.numeric.accepted." + stage)
        if saved is None and allow_candidate:
            candidate = journal.ledger.cached_result("native.numeric.candidate." + stage)
            if candidate is not None:
                saved = {"proposal": proposal, "proof": candidate}
            if stage == "synthesis":
                from tradingagents.research.synthesis_sections import saved_section_candidate
                candidate = saved_section_candidate(journal, context)
                if candidate is not None:
                    saved = {"proposal": candidate[0], "proof": candidate[1]}
        if saved is None or saved["proposal"] != proposal:
            raise ValueError
        validate_numeric_stage(stage, proposal, saved["proof"], context, schema)
        return saved
    except Exception:
        raise CatalystCheckpointConflict("native numeric cached proof invalid") from None


def filter_numeric_proof(stage, proof, accepted_indices, rejections, context, schema):
    from tradingagents.research.numeric_narrative import _compile, _remap_path
    envelope = deepcopy(proof["envelope"])
    positions = [i for i, original in enumerate(proof["indices"]) if original in accepted_indices]
    collection = "challenges" if stage == "challenge" else "hypotheses"
    envelope["proposal"][collection] = [envelope["proposal"][collection][i] for i in positions]
    for key in ("plans", "structured_bindings", *(("premises",) if "premises" in envelope else ())):
        envelope[key] = [dict(item, field_path=path) for item in envelope[key]
            if (path := _remap_path(item["field_path"], positions, reverse=True)) is not None]
    rejected = sorted((r.model_dump(mode="json") for r in rejections), key=lambda r: r["index"])
    _, result = _compile(stage, envelope, context, schema, indices=accepted_indices, rejections=rejected)
    return result


def accept_numeric_result(journal, stage, value, context, schema):
    if not numeric_enabled(journal.state["identity"]):
        return value
    from tradingagents.research.numeric_narrative import compile_numeric_stage
    raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else json.loads(value) if isinstance(value, str) else value
    if isinstance(raw, dict) and "proposal" in raw:
        proposal, proof = compile_numeric_stage(stage, raw, context, schema)
        remember_numeric(journal, stage, proposal, proof, context)
        return proposal
    # SDK adapters return their already-compiled proposal. A custom caller
    # cannot use that route without a matching accepted durable receipt.
    if journal.ledger.cached_result("native.numeric.accepted." + stage) is None and not journal.state.get("native.model." + stage + ".dispatched"):
        from tradingagents.research.numeric_narrative import NumericNarrativeError
        raise NumericNarrativeError("numeric_manifest_binding")
    validate_cached_numeric(journal, stage, raw, context, schema)
    return raw


def _hash_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _texts(record):
    """Public narrative fields, excluding source data and machine identifiers."""
    raw = record.model_dump(mode="json")
    for name in ("claims", "hypotheses", "challenges"):
        for i, item in enumerate(raw[name]):
            fields = (("statement",) if name == "claims" else
                      ("assumptions", "invalidation_conditions", "limitations") if name == "hypotheses"
                      else ("statement", "proposed_test"))
            for field in fields:
                value = item.get(field)
                if isinstance(value, str):
                    yield [name, i, field], value
                elif isinstance(value, list):
                    for j, text in enumerate(value):
                        yield [name, i, field, j], text
    dialogue = raw.get("dialogue")
    if dialogue:
        for i, reply in enumerate(dialogue["responses"]):
            yield ["dialogue", "responses", i, "rationale"], reply["rationale"]
            for j, text in enumerate(reply["remaining_unknowns"]):
                yield ["dialogue", "responses", i, "remaining_unknowns", j], text
    for i, review in enumerate(raw.get('search_reviews', [])):
        yield ['search_reviews', i, 'rationale'], review['rationale']
        for j, text in enumerate(review['new_risks']):
            yield ['search_reviews', i, 'new_risks', j], text
    assessment = raw.get("assessment")
    if assessment:
        for field in ("judgement", "next_check"):
            yield ["assessment", field], assessment[field]
        for i, dimension in enumerate(assessment["dimensions"]):
            yield ["assessment", "dimensions", i, "judgement"], dimension["judgement"]
            for j, text in enumerate(dimension["limitations"]):
                yield ["assessment", "dimensions", i, "limitations", j], text
        for field in ("supporting_arguments", "opposing_arguments", "adjudications", "challenge_assessments"):
            for i, item in enumerate(assessment.get(field, [])):
                yield ["assessment", field, i, "rationale"], item["rationale"]
        for i, condition in enumerate(assessment.get("change_conditions", [])):
            yield ["assessment", "change_conditions", i, "text"], condition["text"]
    for i, text in enumerate(raw["limitations"]):
        if text.startswith("specialist_unknown:"):
            yield ["limitations", i], text


def _value(raw, path):
    for component in path:
        raw = raw[component]
    return raw


def _field_sources(stages):
    for saved in stages:
        for field in saved["proof"]["fields"]:
            text = "".join(segment["text"] for segment in field["segments"])
            yield text, {"stage": saved["stage"], "path": field["path"]}


def _final_fields(record, stages):
    sources = list(_field_sources(stages))
    result = []
    delivery = getattr(record.assessment, "synthesis_sections", None)
    from tradingagents.research.synthesis_sections import unfinished_sections
    missing = unfinished_sections(delivery) if delivery else set()
    host_paths = set()
    if "overall" in missing:
        host_paths.update({("assessment", "judgement"), ("assessment", "next_check")})
    if delivery:
        host_paths.update(("assessment", "challenge_assessments", i, "rationale")
                          for i, _ in enumerate(record.assessment.challenge_assessments))
        for i, d in enumerate(record.assessment.dimensions):
            if "dimension:" + d.dimension in missing:
                host_paths.add(("assessment", "dimensions", i, "judgement"))
                host_paths.update(("assessment", "dimensions", i, "limitations", j) for j, _ in enumerate(d.limitations))
        for i, a in enumerate(record.assessment.adjudications):
            if "adjudication:" + a.challenge_id in missing:
                host_paths.add(("assessment", "adjudications", i, "rationale"))
    for path, text in _texts(record):
        if tuple(path) in host_paths:
            result.append({"path": path, "text_sha256": _hash_text(text), "kind": "host", "sources": []})
            continue
        direct = next((source for original, source in sources if original == text), None)
        selected = [direct] if direct else [source for original, source in sources
            if original and original in text and len(original) >= 2]
        result.append({"path": path, "text_sha256": _hash_text(text),
            "kind": "stage" if direct else "composite" if selected else "host",
            "sources": selected[:8]})
    return result


def attach_numeric_attribution(record, journal):
    if not numeric_enabled(journal.state["identity"]):
        return record
    from tradingagents.research.numeric_catalog import build_numeric_catalog
    catalog = build_numeric_catalog(record)
    if catalog["availability"] == "unavailable" and CATALOG_LIMIT_NOTICE not in record.limitations:
        record = record.model_copy(update={"limitations": (*record.limitations, CATALOG_LIMIT_NOTICE)})
    stages = []
    for stage in ("operating_quality", "event_context", "market_context", "challenge",
                  "response_operating_quality", "response_event_context", "response_market_context", "synthesis"):
        accepted = journal.ledger.cached_result("native.numeric.accepted." + stage)
        kernel = journal.ledger.cached_result("native." + stage)
        if accepted is not None and kernel is not None:
            if accepted["proposal"] != kernel["proposal"]:
                raise CatalystCheckpointConflict("native numeric kernel proposal mismatch")
            if stage.startswith("response_") and not any(
                r.role == stage.removeprefix("response_") and r.status == "available"
                for r in record.dialogue.responses
            ):
                continue
            stages.append(accepted)
    input_identity = dict(journal.state.get("native_input", {}))
    from tradingagents.research.factual_premises import premise_enabled
    if premise_enabled(journal.state["identity"]):
        input_identity.update(factual_premise_policy=journal.state["identity"]["factual_premise_policy"],
                              numeric_narrative_policy=NUMERIC_NARRATIVE_POLICY)
    if record.schema_version == 'research-record-v2':
        for review in record.search_reviews:
            snapshot = next(s for s in record.snapshots if s.snapshot_id == review.input_snapshot_id)
            stage = f'search_review.{review.round_id}.{review.role}.'+snapshot.content_sha256
            accepted = journal.ledger.cached_result('native.numeric.accepted.'+stage)
            kernel = journal.ledger.cached_result('native.'+stage)
            if accepted is None or kernel is None or accepted['proposal'] != kernel['proposal']:
                raise CatalystCheckpointConflict('review numeric receipt missing')
            stages.append(accepted)
    attribution_model = NumericAttributionV1
    if record.schema_version == 'research-record-v2':
        from tradingagents.agents.schemas._numeric_attribution import NumericAttributionV2
        attribution_model = NumericAttributionV2
    attribution = attribution_model.model_validate({
        "policy": NUMERIC_NARRATIVE_POLICY, "input_identity": input_identity,
        "catalog": catalog,
        "stages": stages, "final_fields": _final_fields(record, stages),
    })
    result = record.model_copy(update={"numeric_attribution": attribution})
    validate_record_numeric(result, journal.state["identity"])
    return result


def _validate_public_context(record, stage, context):
    """Public receipts cannot invent a larger fact view than the saved record."""
    from tradingagents.research.numeric_catalog import build_numeric_catalog
    from tradingagents.research.numeric_narrative import _stage_fact_ids
    raw = record.model_dump(mode="json")
    claims = {c["claim_id"]: c for c in raw["claims"]}
    if context.get("numeric_analysis_date") != record.analysis_date.isoformat():
        raise ValueError("numeric context analysis date changed")
    for field in ("facts", "assertions"):
        if any(item != claims.get(item.get("claim_id")) for item in context.get(field, [])):
            raise ValueError("numeric context facts changed")
    contextual = context.get("record", {})
    if record.challenge_check_policy is not None:
        for key in ("challenge_check_policy", "challenge_outcomes", "verifications"):
            if key in contextual and contextual[key] != raw.get(key):
                raise ValueError("numeric challenge result context changed")
        if stage.startswith("response_"):
            targets = set(context.get("assigned", {}))
            if context.get("verifications") != [v.model_dump(mode="json") for v in record.verifications if v.challenge_id in targets]:
                raise ValueError("numeric reply verification context changed")
            if context.get("challenge_outcomes") != [o.model_dump(mode="json") for o in record.challenge_outcomes or () if o.challenge_id in targets]:
                raise ValueError("numeric reply check outcome context changed")
    for key, identifier in (("claims", "claim_id"), ("hypotheses", "hypothesis_id"), ("challenges", "challenge_id")):
        actual = {item[identifier]: item for item in raw[key]}
        if any(item != actual.get(item.get(identifier)) for item in contextual.get(key, [])):
            raise ValueError("numeric context public binding changed")
        if any(item != actual.get(item.get(identifier)) for item in context.get(key, []) if key != "claims"):
            raise ValueError("numeric context target changed")
    snapshot_id = context.get('numeric_input_snapshot_id')
    if record.schema_version == 'research-record-v2' and snapshot_id is None:
        raise ValueError('numeric input snapshot missing')
    actual_catalog = build_numeric_catalog(record, snapshot_id=snapshot_id)
    anchors = {a["anchor_id"]: a for a in actual_catalog["anchors"]}
    metadata = {m["meta_id"]: m for m in actual_catalog["metadata"]}
    catalog = context["numeric_catalog"]
    if any(a != anchors.get(a["anchor_id"]) for a in catalog["anchors"]):
        raise ValueError("numeric context anchor changed")
    if any(m != metadata.get(m["meta_id"]) for m in catalog["metadata"]):
        raise ValueError("numeric context metadata changed")
    if context.get("numeric_aliases") != {f"n_{i:04d}": a["anchor_id"] for i, a in enumerate(catalog["anchors"])}:
        raise ValueError("numeric context aliases changed")
    if context.get("numeric_meta") != {f"m_{i:04d}": m for i, m in enumerate(catalog["metadata"])}:
        raise ValueError("numeric context metadata aliases changed")
    if stage == "synthesis":
        from tradingagents.research.native_policy import dimension_claim_ids
        if context.get("dimension_claim_ids") != {key: list(value) for key, value in dimension_claim_ids(record).items()}:
            raise ValueError("numeric dimension context changed")
        if context.get("synthesis_sections_policy") == "synthesis-sections-v1":
            for key in ("evidence", "metrics", "snapshots", "valuation", "company_basics", "mode",
                        "run_id", "ticker", "evidence_checks", "challenge_bindings"):
                if contextual.get(key) != raw.get(key):
                    raise ValueError("numeric synthesis section context changed")
            if record.assessment is not None and context.get("question") != record.assessment.research_question:
                raise ValueError("numeric synthesis section question changed")
    if stage in {"synthesis", "focus_response"} and contextual.get("dialogue") != raw.get("dialogue"):
        raise ValueError("numeric dialogue context changed")
    if stage in {"operating_quality", "event_context", "market_context"} or stage.startswith("search_review."):
        from tradingagents.research.native_policy import fact_views
        role = stage.split(".")[2] if stage.startswith("search_review.") else stage
        allowed = {f.claim_id for f in fact_views(record, valuation=True)[role]
                   if set(f.evidence_ids) <= set(next(s for s in record.snapshots if s.snapshot_id == snapshot_id).evidence_ids if snapshot_id else record.snapshots[0].evidence_ids)}
        if not _stage_fact_ids(stage, context) <= allowed:
            raise ValueError("numeric specialist context outside scope")
    elif stage.startswith("response_"):
        from tradingagents.agents.schemas._research_dialogue import response_fact_ids
        role = stage.removeprefix("response_")
        actual = {r.challenge_id: r.hypothesis_id for r in record.dialogue.responses if r.role == role}
        if context.get("assigned") != actual:
            raise ValueError("numeric reply assignment changed")
        expected = {cid: sorted(response_fact_ids(record, role, cid)) for cid in actual}
        if context.get("allowed_facts_by_challenge") != expected:
            raise ValueError("numeric reply context outside scope")


def validate_record_numeric(record, identity):
    try:
        _validate_record_numeric(record, identity)
    except (KeyError, IndexError, TypeError, AttributeError, StopIteration):
        raise ValueError("numeric public binding invalid") from None


def _validate_record_numeric(record, identity):
    from tradingagents.agents.schemas._challenge_verification import CHALLENGE_CHECK_POLICY
    challenge_policy = identity.get("challenge_check_policy")
    if challenge_policy is not None and challenge_policy != CHALLENGE_CHECK_POLICY:
        raise ValueError("challenge check identity invalid")
    if (record.challenge_check_policy is not None or record.assessment is not None) and (
            record.challenge_check_policy != challenge_policy):
        raise ValueError("challenge check record identity mismatch")
    from tradingagents.research.factual_premises import premise_enabled, validate_context
    premise_enabled(identity)
    enabled = numeric_enabled(identity)
    attribution = record.numeric_attribution
    if not enabled:
        if attribution is not None:
            raise ValueError("numeric attribution without frozen policy")
        return
    if attribution is None:
        raise ValueError("numeric attribution missing")
    if record.assessment is not None and attribution.input_identity.get("numeric_narrative_policy") != NUMERIC_NARRATIVE_POLICY:
        raise ValueError("numeric input policy missing")
    from tradingagents.research.numeric_catalog import validate_numeric_catalog
    from tradingagents.research.numeric_narrative import validate_numeric_stage
    validate_numeric_catalog(record, attribution.catalog.model_dump(mode="json"))
    if (attribution.catalog.availability == "unavailable") != (CATALOG_LIMIT_NOTICE in record.limitations):
        raise ValueError("numeric catalog availability notice changed")
    stages = [s.model_dump(mode="json") for s in attribution.stages]
    if len({s["stage"] for s in stages}) != len(stages):
        raise ValueError("numeric duplicate stage")
    if "factual_premise_policy" in identity and identity.get("factual_premise_policy") != attribution.input_identity.get("factual_premise_policy"):
        raise ValueError("factual premise record identity mismatch")
    if record.assessment is not None and challenge_policy != attribution.input_identity.get("challenge_check_policy"):
        raise ValueError("challenge check receipt identity mismatch")
    premise_enabled(attribution.input_identity)
    for saved in stages:
        validate_context(record, saved["stage"], saved["context"], attribution.input_identity)
        _validate_public_context(record, saved["stage"], saved["context"])
        validate_numeric_stage(saved["stage"], saved["proposal"], saved["proof"],
                               saved["context"], stage_schema(saved["stage"], attribution.input_identity))
    _validate_entities(record, stages, attribution.input_identity)
    saved_fields = [f.model_dump(mode="json") for f in attribution.final_fields]
    expected_fields = _final_fields(record, stages)
    saved_by_path = {tuple(f["path"]): f for f in saved_fields}
    expected_by_path = {tuple(f["path"]): f for f in expected_fields}
    # Historical producers iterated sets, whose order differs across processes.
    # Paths identify fields; order grants no evidence. Reject duplicates before
    # comparing every binding so dictionary indexing cannot hide extra entries.
    if (len(saved_by_path) != len(saved_fields) or len(expected_by_path) != len(expected_fields)
            or saved_by_path != expected_by_path):
        raise ValueError("numeric final field binding changed")
    # Every model-created public assertion needs an accepted stage receipt.
    covered = {s["stage"] for s in stages}
    if record.hypotheses and record.dialogue and any(o.role not in covered for o in record.dialogue.origins):
        raise ValueError("numeric specialist receipt missing")
    if record.challenges and "challenge" not in covered:
        raise ValueError("numeric challenge receipt missing")
    if record.dialogue and any(r.status == "available" and "response_" + r.role not in covered
                              for r in record.dialogue.responses):
        raise ValueError("numeric response receipt missing")
    if record.assessment and getattr(record.assessment, "report_status", None) in {"synthesized", "analysis_unrated"} and "synthesis" not in covered:
        raise ValueError("numeric synthesis receipt missing")


def _validate_entities(record, stages, identity):
    """A valid receipt cannot certify unrelated, subsequently edited prose."""
    from tradingagents.research.native_policy import gate_dimensions
    from tradingagents.research.report_delivery import retained_summary
    from tradingagents.research.unified_synthesis import investment_fields

    claims = {c.claim_id: c for c in record.claims}
    hypotheses = {h.hypothesis_id: h for h in record.hypotheses}
    expected_hypotheses, expected_challenges, expected_replies = set(), set(), set()
    expected_unknowns = set()
    expected_reviews = set()
    synthesis = None
    for saved in stages:
        stage, proposal = saved["stage"], saved["proposal"]
        if stage in {"operating_quality", "event_context", "market_context"}:
            expected_unknowns.update("specialist_unknown:" + stage + ":" + text for text in proposal["unknowns"])
            indices = saved["proof"]["indices"]
            for index, item in zip(indices, proposal["hypotheses"], strict=True):
                hid = "h." + canonical_sha256({"input": identity, "role": stage,
                                               "index": index, "proposal": item})
                hypothesis, claim = hypotheses[hid], claims["i." + hid[2:]]
                if (claim.statement != item["statement"]
                        or list(claim.supporting_fact_ids) != item["supporting_fact_ids"]
                        or list(hypothesis.assumptions) != [c["text"] for c in item["conditions"] if c["condition_role"] == "necessary"]
                        or list(hypothesis.invalidation_conditions) != [c["text"] for c in item["conditions"] if c["condition_role"] == "invalidation"]
                        or hypothesis.limitations != ("alternative_explanation:" + item["alternative_explanation"],)):
                    raise ValueError("numeric hypothesis text changed")
                expected_hypotheses.add(hid)
        elif stage == "challenge":
            actual = {c.challenge_id: c for c in record.challenges}
            directed = identity.get("challenge_check_policy") is not None
            indices = saved["proof"]["indices"] if directed else range(len(proposal["challenges"]))
            for index, item in zip(indices, proposal["challenges"], strict=True):
                cid = "c." + canonical_sha256({"input": identity, "index": index, "challenge": item})
                challenge = actual[cid]
                target = hypotheses[item["hypothesis_id"]].claim_id
                if (challenge.statement, challenge.proposed_test, challenge.severity,
                    challenge.risk_type, challenge.target_claim_ids) != (
                    item["statement"], item["proposed_test"], item["severity"], item["risk_type"], (target,)):
                    raise ValueError("numeric challenge text changed")
                if directed:
                    from tradingagents.agents.schemas._native_stage import ChallengeProposalV3
                    from tradingagents.research.challenge_checks import challenge_test
                    if challenge.test != challenge_test(ChallengeProposalV3.model_validate(item)):
                        raise ValueError("numeric challenge proposition changed")
                binding = next(b for b in record.challenge_bindings if b.challenge_id == cid)
                if (binding.check_id, binding.observed_risk,
                    binding.observation_date.isoformat() if binding.observation_date else None) != (
                    item["check_id"], item["observed_risk"], item["observation_date"]):
                    raise ValueError("numeric challenge structured binding changed")
                expected_challenges.add(cid)
        elif stage.startswith("response_"):
            replies = {r.response_id: r for r in record.dialogue.responses}
            role = stage.removeprefix("response_")
            for item in proposal["responses"]:
                rid = "response." + canonical_sha256({"snapshot": record.dialogue.input_snapshot_id,
                                                       "role": role, "reply": item})
                reply = replies[rid]
                raw = reply.model_dump(mode="json")
                if {k: v for k, v in raw.items() if k not in {"response_id", "role", "status", "reason_code"}} != item or reply.status != "available":
                    raise ValueError("numeric reply text changed")
                expected_replies.add(rid)
        elif stage.startswith('search_review.'):
            review = next((r for r in record.search_reviews if
                stage == f'search_review.{r.round_id}.{r.role}.'+
                next(s.content_sha256 for s in record.snapshots if s.snapshot_id == r.input_snapshot_id)), None)
            if review is None or review.model_dump(mode='json', include=set(stage_schema(stage).model_fields)) != proposal:
                raise ValueError('numeric review text changed')
            expected_reviews.add(review.review_id)
        elif stage == "synthesis":
            synthesis = stage_schema(stage).model_validate(proposal)
    if record.schema_version == 'research-record-v2' and expected_reviews != {r.review_id for r in record.search_reviews}:
        raise ValueError('numeric review coverage changed')
    if expected_hypotheses != set(hypotheses):
        raise ValueError("numeric hypothesis coverage changed")
    if expected_challenges != {c.challenge_id for c in record.challenges}:
        raise ValueError("numeric challenge coverage changed")
    if record.dialogue and expected_replies != {r.response_id for r in record.dialogue.responses if r.status == "available"}:
        raise ValueError("numeric reply coverage changed")
    if expected_unknowns != {text for text in record.limitations if text.startswith("specialist_unknown:")}:
        raise ValueError("numeric unknown text changed")
    if record.dialogue and any(r.status == "unavailable" and (
        r.rationale != "本专项回应未取得有效保存结果。" or r.remaining_unknowns
    ) for r in record.dialogue.responses):
        raise ValueError("numeric unavailable reply text changed")
    if record.assessment is None:
        return
    base = record.model_copy(update={"assessment": None, "numeric_attribution": None})
    if synthesis is None:
        dimensions, _ = retained_summary(
            base,
            numeric_policy=identity.get("numeric_narrative_policy") == NUMERIC_NARRATIVE_POLICY,
        )
        if record.assessment.dimensions != dimensions:
            raise ValueError("numeric retained summary changed")
        if (record.assessment.judgement != "公司基础报告与已有专项结果已交付；综合阶段未完成，暂未形成总体评级。"
                or record.assessment.next_check != "补充各章节列明的具体资料，并在后续完成综合分析。"):
            raise ValueError("numeric fallback prose changed")
        return
    dimensions = gate_dimensions(base, synthesis.dimensions, scoped=True, valuation=True, sections=synthesis.synthesis_sections)
    fields = investment_fields(base, synthesis, dimensions)
    judgement = ("关键经营或估值依据不足，暂不能形成完整投资吸引力判断。"
                 if fields.pop("force_insufficient", False) else synthesis.judgement)
    actual = record.assessment
    if actual.dimensions != dimensions or actual.judgement != judgement or actual.next_check != synthesis.next_check:
        raise ValueError("numeric synthesis prose changed")
    for key, value in fields.items():
        if getattr(actual, key) != value:
            raise ValueError("numeric investment binding changed")


def validate_focus_numeric(record, response):
    saved = response.numeric_attribution
    if record.numeric_attribution is None:
        if saved is not None:
            raise ValueError("numeric focus without baseline policy")
        return
    if response.status == "unavailable":
        if saved is not None:
            raise ValueError("unavailable focus cannot carry numeric support")
        return
    if saved is None or saved.stage != "focus_response" or saved.proposal != response.proposal.model_dump(mode="json"):
        raise ValueError("numeric focus receipt missing or changed")
    from tradingagents.research.numeric_narrative import validate_numeric_stage
    _validate_public_context(record, "focus_response", saved.context)
    validate_numeric_stage("focus_response", saved.proposal, saved.proof, saved.context, stage_schema("focus_response"))
