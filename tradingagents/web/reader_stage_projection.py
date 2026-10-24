"""Read-only V7 stage qualification, independent of final publication.

Only closed public schemas leave this module. Rebuilding a record executes no
research, verification, model call or persistence operation.
"""

import json
from functools import cached_property
from types import SimpleNamespace

from tradingagents.agents.schemas._native_stage import (
    ChallengesProposalV2,
    ChallengesProposalV3,
    SpecialistProposalV1,
    SynthesisProposalV3,
    saved_specialist_acceptance,
    validate_hypothesis_references,
)
from tradingagents.agents.schemas._research_dialogue import (
    ResearchDialogueV1,
    ResearchResponseV1,
    ResponsesProposalV1,
    response_fact_ids,
)
from tradingagents.agents.schemas._verification_plan import (
    VerificationPlanV1,
    canonical_sha256,
    parse_verification_plan,
)
from tradingagents.research.native_versions import (
    COMPANY_RESEARCH_POLICY,
    NUMERIC_NARRATIVE_POLICY,
    REPORT_DELIVERY_POLICY,
    RESPONSE_ROLES,
    SEARCH_WORKFLOW_VERSION,
    SPECIALIST_REFERENCE_POLICY,
    UNIFIED_KERNEL_VERSION,
    UNIFIED_QUESTION,
    UNIFIED_WORKFLOW_VERSION,
)
from tradingagents.research.numeric_integration import (
    numeric_enabled,
    validate_cached_numeric,
    validate_record_numeric,
)
from tradingagents.research.record_codec import parse_research_record
from tradingagents.research.unified_dialogue import validate_response_proposal
from tradingagents.web.native_reader_versions import saved_fact_views

SPECIALISTS = ("operating_quality", "event_context", "market_context")


def updated(record, **fields):
    return parse_research_record({**record.model_dump(mode="json"), "numeric_attribution": None, **fields})


def stage_seed(ctx):
    cp, snapshot = ctx.checkpoint, ctx.snapshot
    identity = cp["identity"]
    if identity.get("workflow_version") not in {UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION}:
        raise ValueError("stage_workflow_unsupported")
    seed = parse_research_record(cp["native_seed"])
    if (seed.run_id, seed.ticker, seed.mode, seed.analysis_date.isoformat(), seed.construction) != (
        snapshot.run_id, snapshot.ticker, snapshot.mode, snapshot.analysis_date, "native"
    ) or (identity.get("ticker"), identity.get("mode"), identity.get("cutoff")) != (
        seed.ticker, seed.mode, seed.analysis_date.isoformat()
    ):
        raise ValueError("stage_seed_identity")
    if (seed.assessment or seed.dialogue is not None or seed.hypotheses or seed.challenges
            or seed.verifications or len(seed.snapshots) != 1 or any(c.kind != "fact" for c in seed.claims)):
        raise ValueError("stage_seed_shape")
    sources = {s.evidence_id: s for s in seed.evidence}
    if any(sources[e].availability != "available" or sources[e].content is None or sources[e].usable_as_of is None
           for fact in seed.claims for e in fact.evidence_ids):
        raise ValueError("stage_source_qualification")
    validate_record_numeric(seed, identity)
    expected = {"workflow_version": "native-research-kernel-v7" if seed.schema_version == "research-record-v2" else UNIFIED_KERNEL_VERSION, "seed_sha256": canonical_sha256(seed),
                "research_question": UNIFIED_QUESTION}
    from tradingagents.agents.schemas._challenge_verification import CHALLENGE_CHECK_POLICY
    from tradingagents.agents.schemas._factual_premise import FACTUAL_PREMISE_POLICY
    for key, policy in (("factual_premise_policy", FACTUAL_PREMISE_POLICY),
                        ("company_research_policy", COMPANY_RESEARCH_POLICY),
                        ("report_delivery_policy", REPORT_DELIVERY_POLICY),
                        ("specialist_reference_policy", SPECIALIST_REFERENCE_POLICY),
                        ("numeric_narrative_policy", NUMERIC_NARRATIVE_POLICY)):
        if identity.get(key) is not None:
            if identity[key] != policy:
                raise ValueError("stage_policy")
            expected[key] = policy
    if identity.get("challenge_check_policy") is not None:
        if identity["challenge_check_policy"] != CHALLENGE_CHECK_POLICY:
            raise ValueError("stage_policy")
        expected["challenge_check_policy"] = CHALLENGE_CHECK_POLICY
    if "native_input" in cp and cp["native_input"] != expected:
        raise ValueError("stage_input_identity")
    return seed


class StageReader:
    def __init__(self, ctx):
        self.ctx, self.cp = ctx, ctx.checkpoint
        self.seed = stage_seed(ctx)
        self.views = saved_fact_views(self.seed, self.cp["identity"]["workflow_version"])
        # V7 company-foundation facts are background, never specialist inputs.
        self.views = {role: tuple(f for f in facts if "native_dimension:company_introduction" not in f.limitations)
                      for role, facts in self.views.items()}
        self._specialists = {}

    def proposal(self, role, schema, record, context):
        saved = self.cp["results"].get("native." + role)
        if saved is None:
            return None
        if "native_input" not in self.cp:
            raise ValueError("stage_input_missing")
        proposal = schema.model_validate_json(json.dumps(saved["proposal"], allow_nan=False))
        if numeric_enabled(self.cp["identity"]):
            from tradingagents.research.numeric_narrative import (
                numeric_validation_context,
                prepare_numeric_context,
            )
            # Rebuild from qualified material, never trust the receipt's context
            # to validate itself. This also binds catalogs, aliases and dates.
            sectioned = role == "synthesis" and self.cp.get("native.reference_schema.synthesis") == 3
            if sectioned:
                context = {**context, "question": UNIFIED_QUESTION}
            expected = numeric_validation_context(prepare_numeric_context(role, context, record, identity=self.cp["identity"]), sectioned=sectioned)
            receipt = self.cp["results"].get("native.numeric.accepted." + role, {})
            if receipt.get("context") != expected:
                raise ValueError("stage_numeric_context")
            journal = SimpleNamespace(state=self.cp, ledger=SimpleNamespace(
                cached_result=lambda key: self.cp["results"].get(key)))
            validate_cached_numeric(journal, role, proposal.model_dump(mode="json"), expected, schema)
        return proposal

    def specialist(self, role):
        if role not in self._specialists:
            self._specialists[role] = self._specialist(role)
        return self._specialists[role]

    def _specialist(self, role):
        facts = self.views[role]
        context = {"facts": [f.model_dump(mode="json") for f in facts]}
        if role == "operating_quality":
            context["local_checks"] = self.seed.evidence_checks.model_dump(mode="json")
        proposal = self.proposal(role, SpecialistProposalV1, self.seed, context)
        if proposal is None:
            return None
        accepted = saved_specialist_acceptance(self.cp, role, proposal)
        indices = accepted.indices if accepted else tuple(range(len(proposal.hypotheses)))
        claims, hypotheses, conditions = [], [], {}
        allowed = {f.claim_id: f.evidence_ids for f in facts}
        metric_evidence = {m.metric_id: m.input_evidence_ids for m in self.seed.metrics}
        for index, item in zip(indices, proposal.hypotheses, strict=True):
            validate_hypothesis_references(item, allowed, metric_evidence)
            hid = "h." + canonical_sha256({"input": self.cp["native_input"], "role": role,
                                         "index": index, "proposal": item.model_dump(mode="json")})
            cid = "i." + hid[2:]
            evidence = tuple(dict.fromkeys(e for fid in item.supporting_fact_ids for e in allowed[fid]))
            claims.append({"claim_id": cid, "kind": "inference", "statement": item.statement,
                           "evidence_ids": evidence, "supporting_fact_ids": item.supporting_fact_ids})
            hypotheses.append({"hypothesis_id": hid, "claim_id": cid,
                "input_snapshot_id": self.seed.snapshots[0].snapshot_id, "origin": "hypothesis_stage",
                "assumptions": [c.text for c in item.conditions if c.condition_role == "necessary"],
                "invalidation_conditions": [c.text for c in item.conditions if c.condition_role == "invalidation"],
                "limitations": ["alternative_explanation:" + item.alternative_explanation]})
            for condition in item.conditions:
                bound = {"hypothesis_id": hid, "input_snapshot_id": self.seed.snapshots[0].snapshot_id,
                         **condition.model_dump(mode="json")}
                key = "condition." + canonical_sha256(bound)
                if "native_conditions" in self.cp and self.cp["native_conditions"].get(key) != bound:
                    raise ValueError("stage_condition_binding")
                conditions[key] = bound
        return proposal, claims, hypotheses, conditions, accepted

    def prerequisites(self):
        return self._prerequisites

    @cached_property
    def _prerequisites(self):
        claims, hypotheses, conditions, origins = [], [], {}, {}
        limits = list(self.seed.limitations)
        for key in ("company_research_policy", "report_delivery_policy", "numeric_narrative_policy"):
            if self.cp["identity"].get(key) is not None:
                limits.append(self.cp["identity"][key])
        for role in SPECIALISTS:
            item = self.specialist(role)
            if item is None:
                if self.views[role]:
                    limits.append("native_stage_unavailable:" + role)
                continue
            proposal, cs, hs, bound, accepted = item
            claims.extend(cs)
            hypotheses.extend(hs)
            conditions.update(bound)
            origins.update({h["hypothesis_id"]: role for h in hs})
            if accepted:
                limits.extend(f"native_hypothesis_rejected:{role}:{r.code}:{r.index}" for r in accepted.rejections)
                if accepted.rejections and not proposal.hypotheses:
                    limits.append("native_stage_unavailable:" + role)
            limits.extend("specialist_unknown:" + role + ":" + u for u in proposal.unknowns)
        record = updated(self.seed, claims=[*self.seed.claims, *claims], hypotheses=hypotheses, limitations=limits)
        payload = record.model_dump(mode="json")
        payload["claims"].sort(key=lambda c: c["claim_id"])
        payload["hypotheses"].sort(key=lambda h: h["hypothesis_id"])
        context = {"record": payload, "local_checks": self.seed.evidence_checks.model_dump(mode="json")}
        directed = self.cp["identity"].get("challenge_check_policy")
        if directed:
            context["challenge_check_policy"] = directed
        schema = ChallengesProposalV3 if directed else ChallengesProposalV2
        proposal = self.proposal("challenge", schema, record, context)
        challenges, bindings = [], []
        hs = {h.hypothesis_id: h for h in record.hypotheses}
        if proposal:
            from tradingagents.agents.schemas._native_stage import saved_challenge_acceptance
            accepted = saved_challenge_acceptance(self.cp, proposal) if directed else None
            if accepted:
                limits.extend(f"native_challenge_rejected:{r.code}:{r.index}" for r in accepted.rejections)
                if accepted.rejections and not proposal.challenges:
                    limits.append("native_stage_unavailable:challenge")
            indices = accepted.indices if accepted else range(len(proposal.challenges))
            for index, item in zip(indices, proposal.challenges, strict=True):
                if directed:
                    from tradingagents.research.challenge_checks import validate_challenge
                    validate_challenge(record, item, conditions)
                target = hs[item.hypothesis_id]
                if item.condition_id and conditions.get(item.condition_id, {}).get("hypothesis_id") != item.hypothesis_id:
                    raise ValueError("stage_challenge_condition")
                cid = "c." + canonical_sha256({"input": self.cp["native_input"], "index": index,
                                               "challenge": item.model_dump(mode="json")})
                challenges.append({"challenge_id": cid, "target_claim_ids": [target.claim_id],
                    "statement": item.statement, "severity": item.severity,
                    "risk_type": item.risk_type, "proposed_test": item.proposed_test})
                if directed:
                    from tradingagents.research.challenge_checks import challenge_test
                    challenges[-1]["test"] = challenge_test(item).model_dump(mode="json")
                bindings.append({"challenge_id": cid, "check_id": item.check_id,
                                 "observed_risk": item.observed_risk, "observation_date": item.observation_date})
        else:
            limits.append("native_stage_unavailable:challenge")
        record = updated(record, challenges=challenges, challenge_bindings=bindings,
                         limitations=list(dict.fromkeys(limits)),
                         **({"challenge_check_policy": directed} if directed else {}))
        if "native_origins" in self.cp and self.cp["native_origins"] != origins:
            raise ValueError("stage_origin_binding")
        return record, proposal, origins

    def verified(self, record):
        saved = self.cp["results"].get("verification.output")
        if saved is None:
            return record
        from tradingagents.execution.verification_executor import (
            VerificationExecutionV1,
            _build_record,
            _validate_bindings,
        )
        frontier = self.cp["verification_input"]
        original = parse_research_record(frontier["record"])
        if original != record:
            raise ValueError("stage_verification_input")
        plan = parse_verification_plan(frontier["plan"])
        _validate_bindings(original, plan)
        critique = self.cp["results"].get("native.challenge")
        schema = ChallengesProposalV3 if original.challenge_check_policy else ChallengesProposalV2
        proposed = schema.model_validate(critique["proposal"]) if critique else schema()
        tasks = []
        for challenge, item in zip(original.challenges, proposed.challenges, strict=True):
            bound = self.cp.get("native_conditions", {}).get(item.condition_id) if item.condition_id else None
            if not original.challenge_check_policy and bound and bound["check"] is not None:
                tasks.append({"task_id": "t." + challenge.challenge_id[2:], "challenge_id": challenge.challenge_id,
                    "hypothesis_id": item.hypothesis_id, "condition_role": bound["condition_role"],
                    "condition_text": bound["text"], "check": bound["check"]})
        expected_plan = VerificationPlanV1.model_validate_json(json.dumps({
            "run_id": original.run_id, "ticker": original.ticker, "mode": original.mode,
            "analysis_date": original.analysis_date.isoformat(), "input_snapshot_id": original.snapshots[0].snapshot_id,
            "tasks": tasks}, allow_nan=False))
        if original.challenge_check_policy:
            from tradingagents.research.challenge_checks import make_challenge_plan
            expected_plan = make_challenge_plan(original)
        if plan != expected_plan:
            raise ValueError("stage_verification_plan")
        if (frontier["plan_sha256"] != canonical_sha256(plan)
                or frontier["input_record_sha256"] != canonical_sha256(original)
                or saved["identity_sha256"] != canonical_sha256({**frontier,
                    "plan": plan.model_dump(mode="json"), "record": original.model_dump(mode="json")})):
            raise ValueError("stage_verification_identity")
        output = VerificationExecutionV1.model_validate(saved["output"])
        outcome_ids = [o.task_id for o in output.outcomes]
        if len(set(outcome_ids)) != len(outcome_ids) or set(outcome_ids) != {t.task_id for t in plan.tasks}:
            raise ValueError("stage_verification_coverage")
        if (output.plan_sha256 != canonical_sha256(plan)
                or output.input_record_sha256 != canonical_sha256(original)
                or _build_record(original, plan, output.outcomes, output.plan_sha256) != output.record):
            raise ValueError("stage_verification_output")
        return output.record

    def reply(self, record, origins, stage):
        role = stage.removeprefix("response_")
        hs = {h.claim_id: h for h in record.hypotheses}
        assignments = {c.challenge_id: hs[c.target_claim_ids[0]].hypothesis_id for c in record.challenges
                       if origins[hs[c.target_claim_ids[0]].hypothesis_id] == role}
        allowed = {fid for cid in assignments for fid in response_fact_ids(record, role, cid)}
        context = {"facts": [f.model_dump(mode="json") for f in record.claims if f.claim_id in allowed],
            "assertions": [c.model_dump(mode="json") for c in record.claims if c.claim_id in {
                h.claim_id for h in record.hypotheses if h.hypothesis_id in assignments.values()}],
            "hypotheses": [h.model_dump(mode="json") for h in record.hypotheses if h.hypothesis_id in assignments.values()],
            "challenges": [c.model_dump(mode="json") for c in record.challenges if c.challenge_id in assignments],
            "assigned": assignments, "allowed_facts_by_challenge": {
                cid: sorted(response_fact_ids(record, role, cid)) for cid in assignments},
            "local_checks": [b.model_dump(mode="json") for b in record.challenge_bindings if b.challenge_id in assignments]}
        if record.challenge_check_policy is not None:
            context["challenge_check_policy"] = record.challenge_check_policy
            context["verifications"] = [v.model_dump(mode="json") for v in record.verifications if v.challenge_id in assignments]
            context["challenge_outcomes"] = [o.model_dump(mode="json") for o in record.challenge_outcomes or ()
                                               if o.challenge_id in assignments]
        proposal = self.proposal(stage, ResponsesProposalV1, record, context)
        if proposal is not None:
            validate_response_proposal(record, role, proposal, assignments)
        return proposal, tuple(f.claim_id for f in record.claims if f.claim_id in allowed), assignments

    def read(self, role):
        """Return public material, proposal, output IDs and actual input facts."""
        seed = self.seed
        if role == "evidence":
            return seed, None, tuple(c.claim_id for c in seed.claims), (), ()
        if role in SPECIALISTS:
            item = self.specialist(role)
            if item is None:
                return None
            proposal, claims, hypotheses, _, _ = item
            if item[4] and item[4].rejections and not proposal.hypotheses:
                raise ValueError("stage_all_hypotheses_rejected")
            record = updated(seed, claims=[*seed.claims, *claims], hypotheses=hypotheses)
            return record, proposal, tuple(c["claim_id"] for c in claims), (), tuple(f.claim_id for f in self.views[role])
        record, challenge, origins = self.prerequisites()
        inputs = tuple(c.claim_id for c in record.claims if c.kind == "fact")
        if role == "challenge":
            if "native_stage_unavailable:challenge" in record.limitations:
                raise ValueError("stage_all_challenges_rejected")
            return (record, challenge, (), tuple(c.challenge_id for c in record.challenges), inputs) if challenge else None
        if self.cp["results"].get("verification.output") is None:
            if self.cp["results"].get("native." + role) is not None:
                raise ValueError("stage_verification_missing")
            return None
        record = self.verified(record)
        if role == "code_checks":
            return (record, None, (), (), inputs) if self.cp["results"].get("verification.output") else None
        if role in RESPONSE_ROLES:
            proposal, facts, _ = self.reply(record, origins, role)
            return (record, proposal, tuple(dict.fromkeys(f for r in proposal.responses for f in r.supporting_fact_ids)),
                    tuple(r.challenge_id for r in proposal.responses), facts) if proposal else None
        if role != "synthesis":
            return None
        replies = []
        for stage in RESPONSE_ROLES:
            proposal, _, assignments = self.reply(record, origins, stage)
            supplied = {r.challenge_id: r.model_dump(mode="json") for r in proposal.responses} if proposal else {}
            for cid, hid in assignments.items():
                value = supplied.get(cid, {"challenge_id": cid, "hypothesis_id": hid,
                    "disposition": "unanswerable", "rationale": "本专项回应未取得有效保存结果。"})
                rid = "response." + canonical_sha256({"snapshot": record.snapshots[-1].snapshot_id,
                    "role": stage.removeprefix("response_"), "reply": value})
                replies.append(ResearchResponseV1(**value, response_id=rid, role=stage.removeprefix("response_"),
                    status="available" if proposal else "unavailable", reason_code=None if proposal else "native_response_unavailable"))
        dialogue = ResearchDialogueV1(input_snapshot_id=record.snapshots[-1].snapshot_id,
            origins=tuple({"hypothesis_id": h, "role": r} for h, r in origins.items()), responses=tuple(replies))
        record = updated(record, dialogue=dialogue.model_dump(mode="json"))
        if record.schema_version == 'research-record-v2':
            saved_search = self.cp['results'].get('search.reviews.output')
            if saved_search is not None:
                from tradingagents.agents.schemas._search import SearchGapsV1
                stages = (*SPECIALISTS, 'challenge', *RESPONSE_ROLES)
                gaps = tuple(dict.fromkeys(g for stage in stages if self.cp['results'].get('native.'+stage) is not None
                    for g in SearchGapsV1.model_validate(self.cp['results'].get('native.search_gaps.'+stage) or {'gaps': []}).gaps))
                if saved_search['input'] != canonical_sha256({'record': record, 'gaps': gaps}):
                    raise ValueError('stage_search_frontier')
                revised = parse_research_record(saved_search['record'])
                if (revised.dialogue != record.dialogue or revised.hypotheses != record.hypotheses
                        or revised.challenges != record.challenges or revised.verifications != record.verifications
                        or revised.snapshots[:len(record.snapshots)] != record.snapshots):
                    raise ValueError('stage_search_history')
                record = revised
        from tradingagents.research.native_policy import dimension_claim_ids, gate_dimensions
        proposal = self.proposal(role, SynthesisProposalV3, record, {
            "record": record.model_dump(mode="json"), "dimension_claim_ids": dimension_claim_ids(record)})
        if proposal is None:
            return None
        for dim in proposal.dimensions:
            if not set(dim.claim_ids) <= set(dimension_claim_ids(record).get(dim.dimension, ())):
                raise ValueError("stage_synthesis_dimension")
        from tradingagents.research.minimum_evidence import challenge_assessments
        from tradingagents.research.unified_synthesis import investment_fields
        dimensions = gate_dimensions(record, proposal.dimensions, scoped=True, valuation=True,
                                    sections=getattr(proposal, "synthesis_sections", None))
        fields = investment_fields(record, proposal, dimensions)
        fields.pop("force_insufficient", None)
        # Validate the complete reference graph without publishing or returning
        # a manufactured assessment in the stage record.
        updated(record, assessment={**proposal.model_dump(mode="json"), **fields,
            "schema_version": "research-assessment-v3", "input_snapshot_id": record.snapshots[-1].snapshot_id,
            "research_question": UNIFIED_QUESTION, "dimensions": [d.model_dump(mode="json") for d in dimensions],
            "challenge_assessments": [a.model_dump(mode="json") for a in challenge_assessments(record)],
            "completeness": "partial", "quality": "LOW_CONFIDENCE"})
        return record, proposal, proposal.key_claim_ids, tuple(a.challenge_id for a in proposal.challenge_assessments), inputs
