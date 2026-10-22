"""Evidence → hypotheses → one challenge → bounded checks → synthesis.

This shared kernel has no profile, HTTP retrieval, model SDK or Web dependency.
Callers supply a facts-only V0 and the run's existing durable ledger.
"""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel

from tradingagents.agents.schemas._native_stage import (
    ChallengesProposalV1,
    ChallengesProposalV2,
    ChallengesProposalV3,
    NativeEvidenceBindingError,
    SpecialistProposalV1,
    SynthesisProposalV1,
    SynthesisProposalV2,
    SynthesisProposalV3,
    saved_challenge_acceptance,
    saved_specialist_acceptance,
    validate_hypothesis_references,
)
from tradingagents.agents.schemas._research_assessment import (
    ChallengeAssessmentV1,
    DimensionAssessmentV1,
    ResearchAssessmentV1,
    ResearchAssessmentV2,
    ResearchAssessmentV3,
)
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.agents.schemas._verification_plan import VerificationPlanV1, canonical_sha256
from tradingagents.execution.budget import AttemptPhase, BudgetBucket, BudgetLimitHit
from tradingagents.execution.models import AnalysisCancelled
from tradingagents.execution.verification_executor import execute_verification
from tradingagents.research.native_policy import (
    QUESTIONS,
    ROLE_ORDER,
    dimension_claim_ids,
    dimension_policy,
    fact_views,
    gate_dimensions,
    global_coverage,
)
from tradingagents.research.native_versions import (
    BASE_QUESTIONS,
    FOCUS_KERNEL_VERSION,
    NUMERIC_NARRATIVE_POLICY,
    REPORT_DELIVERY_POLICY,
    SPECIALIST_REFERENCE_POLICY,
    UNIFIED_KERNEL_VERSION,
    UNIFIED_QUESTION,
)
from tradingagents.runtime.catalyst_checkpoint import (
    CatalystCheckpointConflict,
    DurableBudgetLedger,
)

WORKFLOW_VERSION = "native-research-kernel-v1"


def _bound_put(journal, key, value):
    with journal.lock:
        if key in journal.state and journal.state[key] != value:
            raise CatalystCheckpointConflict("native research frontier changed")
        if key not in journal.state:
            journal.put(key, value)


def _call(stage, context, schema, *, caller, ledger, cancelled, reservation=None):
    logical = "native." + stage
    _bound_put(ledger.journal, logical + ".input", {"sha256": canonical_sha256(context)})
    cached = ledger.cached_result(logical)
    if cached is not None:
        from tradingagents.research.numeric_integration import validate_cached_numeric
        validate_cached_numeric(ledger.journal, stage, cached["proposal"], context, schema)
        return schema.model_validate_json(json.dumps(cached["proposal"]))
    recover = getattr(caller, "recover_cached", None)
    if callable(recover):
        saved = recover(stage, context)
        if saved is not None:
            from tradingagents.research.numeric_integration import validate_cached_numeric
            receipt = validate_cached_numeric(ledger.journal, stage, saved, context, schema, allow_candidate=True)
            if receipt is not None:
                from tradingagents.research.numeric_integration import remember_numeric
                remember_numeric(ledger.journal, stage, saved, receipt["proof"], context)
            proposal = schema.model_validate_json(json.dumps(saved, allow_nan=False))
            ledger.record_result(logical, {"proposal": proposal.model_dump(mode="json")})
            return proposal
    attempts = [item for item in ledger.records() if item.logical_call_id == logical]
    if any(item.phase != AttemptPhase.RESERVED and item.dispatched_at is not None for item in attempts):
        # A lost response remains billed and unknown. Resuming cannot invent a
        # second model decision for the same immutable stage.
        return None
    token = reservation or ledger.reserve(BudgetBucket.MAIN_ANALYSIS, stage=logical, logical_call_id=logical)
    if isinstance(token, BudgetLimitHit):
        return None
    if cancelled():
        ledger.release(token, reason="native_cancelled_before_dispatch")
        return None
    ledger.mark_dispatched(token)
    try:
        value = caller(stage, context)
        from tradingagents.research.numeric_integration import accept_numeric_result
        value = accept_numeric_result(ledger.journal, stage, value, context, schema)
        if isinstance(value, BaseModel):
            value = value.model_dump_json()
        elif not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if stage == "synthesis" and ledger.journal.state["identity"].get("report_delivery_policy") == REPORT_DELIVERY_POLICY:
            from tradingagents.research.report_delivery import normalize_synthesis_bindings
            value = json.dumps(normalize_synthesis_bindings(json.loads(value), ResearchRecordV1.model_validate(context["record"])), ensure_ascii=False)
        proposal = schema.model_validate_json(value)
        if isinstance(proposal, ChallengesProposalV3):
            from tradingagents.research.challenge_checks import validate_challenge
            record = ResearchRecordV1.model_validate(context["record"])
            for item in proposal.challenges:
                validate_challenge(record, item, context["conditions"])
    except (CatalystCheckpointConflict, AnalysisCancelled, TimeoutError):
        raise
    except Exception:
        if ledger.journal.failed:
            raise
        ledger.settle(token, ok=False, detail="native_stage_invalid_or_unavailable")
        return None
    ledger.record_result(logical, {"proposal": proposal.model_dump(mode="json")})
    usage = ledger.journal.state.get("native.model_usage", {}).get(stage, {})
    measured = all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("input_tokens", "output_tokens"))
    ledger.settle(token, ok=True, detail="native_stage_validated", usage_available=measured,
                  input_tokens=usage.get("input_tokens") if measured else None,
                  output_tokens=usage.get("output_tokens") if measured else None)
    return proposal


def _validated(record, **updates):
    if record.numeric_attribution is not None:
        updates.setdefault("numeric_attribution", None)
    return ResearchRecordV1.model_validate({**record.model_dump(mode="json"), **updates})


def load_native_seed(ledger: DurableBudgetLedger) -> ResearchRecordV1 | None:
    """Recover the exact V0 instead of rehashing normalized provider numbers.

    RunStore uses RFC 8785 (2.0 becomes 2). Source families use the provider's
    original JSON representation. The saved source-content strings in V0 keep
    their exact bytes; rebuilding that record from normalized raw context can
    therefore change provenance. Reading this seed never retrieves anything.
    """
    if not isinstance(ledger, DurableBudgetLedger) or ledger.journal.ledger is not ledger:
        raise ValueError("native seed recovery requires the run's durable ledger")
    with ledger.journal.lock:
        if ledger.journal.failed:
            raise CatalystCheckpointConflict("native seed persistence failed")
        saved = ledger.journal.state.get("native_seed")
        if saved is None:
            return None
        try:
            record = ResearchRecordV1.model_validate(saved)
            from tradingagents.research.numeric_integration import validate_record_numeric
            validate_record_numeric(record, ledger.journal.state["identity"])
        except Exception:
            raise CatalystCheckpointConflict("native seed invalid") from None
        identity = ledger.journal.state.get("native_input")
        if record.run_id != ledger.run_id or (identity is not None
                and identity.get("seed_sha256") != canonical_sha256(record)):
            raise CatalystCheckpointConflict("native seed identity mismatch")
        if (record.construction != "native" or len(record.snapshots) != 1 or record.hypotheses
                or record.challenges or record.verifications or record.assessment or record.dialogue is not None
                or any(claim.kind != "fact" for claim in record.claims)):
            raise CatalystCheckpointConflict("native seed is not a facts-only V0")
        return record


def run_native_research(seed: ResearchRecordV1, *, caller: Callable,
                        ledger: DurableBudgetLedger, research_question: str | None = None,
                        cancelled: Callable[[], bool] = lambda: False,
                        concurrency: int = 2, scoped: bool = False, valuation: bool = False,
                        minimum: bool = False, independent: bool = False, unified: bool = False) -> ResearchRecordV1:
    seed = ResearchRecordV1.model_validate_json(seed.model_dump_json())
    if (seed.construction != "native" or len(seed.snapshots) != 1 or seed.hypotheses
            or seed.challenges or seed.verifications or seed.assessment or seed.dialogue is not None
            or any(claim.kind != "fact" for claim in seed.claims)):
        raise ValueError("native workflow requires a facts-only V0")
    if (not isinstance(ledger, DurableBudgetLedger) or ledger.run_id != seed.run_id
            or ledger.journal.ledger is not ledger):
        raise ValueError("native workflow requires the run's durable ledger")
    if concurrency not in (1, 2):
        raise ValueError("native specialist concurrency is bounded at two")
    if minimum and seed.evidence_checks is None:
        raise ValueError("v5 workflow requires frozen local checks")
    sources = {source.evidence_id: source for source in seed.evidence}
    if any(sources[key].availability != "available" or sources[key].content is None
           or sources[key].usable_as_of is None for fact in seed.claims for key in fact.evidence_ids):
        raise ValueError("native facts require qualified saved source content")
    if unified and not all((minimum, independent, valuation, scoped)):
        raise ValueError("unified workflow requires its frozen evidence policies")
    if unified and seed.mode != "company_research":
        raise ValueError("unified research supports company only")
    question = UNIFIED_QUESTION if unified else BASE_QUESTIONS[seed.mode] if independent else research_question if research_question is not None else QUESTIONS[seed.mode]
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 400:
        raise ValueError("research question must contain 1..400 characters")
    identity = {"workflow_version": UNIFIED_KERNEL_VERSION if unified else FOCUS_KERNEL_VERSION if independent else "native-research-kernel-v4" if minimum else "native-research-kernel-v3" if valuation else "native-research-kernel-v2" if scoped else WORKFLOW_VERSION, "seed_sha256": canonical_sha256(seed),
                "research_question": question}
    from tradingagents.agents.schemas._challenge_verification import CHALLENGE_CHECK_POLICY
    directed = ledger.journal.state["identity"].get("challenge_check_policy")
    if directed is not None:
        if directed != CHALLENGE_CHECK_POLICY or not unified:
            raise CatalystCheckpointConflict("native challenge check policy mismatch")
        identity["challenge_check_policy"] = directed
    from tradingagents.research.factual_premises import premise_enabled
    from tradingagents.research.numeric_integration import numeric_enabled, validate_record_numeric
    if premise_enabled(ledger.journal.state["identity"]):
        identity["factual_premise_policy"] = ledger.journal.state["identity"]["factual_premise_policy"]
    numeric = numeric_enabled(ledger.journal.state["identity"])
    if numeric:
        from tradingagents.research.numeric_narrative import prepare_numeric_context
        if not unified:
            raise CatalystCheckpointConflict("native numeric workflow mismatch")
        validate_record_numeric(seed, ledger.journal.state["identity"])
        identity["numeric_narrative_policy"] = NUMERIC_NARRATIVE_POLICY
    from tradingagents.research.native_versions import COMPANY_RESEARCH_POLICY
    company_policy = ledger.journal.state["identity"].get("company_research_policy")
    report_policy = ledger.journal.state["identity"].get("report_delivery_policy")
    if report_policy is not None:
        if report_policy != REPORT_DELIVERY_POLICY or not unified:
            raise CatalystCheckpointConflict("native report delivery policy mismatch")
        identity["report_delivery_policy"] = report_policy
    if company_policy is not None:
        if company_policy != COMPANY_RESEARCH_POLICY or not unified:
            raise CatalystCheckpointConflict("native company research policy mismatch")
        identity["company_research_policy"] = company_policy
    policy = ledger.journal.state["identity"].get("specialist_reference_policy")
    if policy is not None:
        if policy != SPECIALIST_REFERENCE_POLICY:
            raise CatalystCheckpointConflict("native specialist reference policy mismatch")
        identity["specialist_reference_policy"] = policy
    _bound_put(ledger.journal, "native_seed", seed.model_dump(mode="json"))
    _bound_put(ledger.journal, "native_input", identity)
    cached_final = ledger.cached_result("native.output")
    if cached_final is not None:
        if cached_final["identity"] != identity:
            raise CatalystCheckpointConflict("native output identity mismatch")
        restored = ResearchRecordV1.model_validate(cached_final["record"])
        validate_record_numeric(restored, ledger.journal.state["identity"])
        return restored
    views = fact_views(seed, valuation=valuation)
    contexts, reservations = {}, {}
    for role in ROLE_ORDER:
        facts = views[role]
        if not facts:
            continue
        source_ids = {key for fact in facts for key in fact.evidence_ids}
        contexts[role] = {"mode": seed.mode, "question": question,
            "input_snapshot_id": seed.snapshots[0].snapshot_id,
            "facts": [fact.model_dump(mode="json") for fact in facts],
            "sources": [item.model_dump(mode="json") for item in seed.evidence if item.evidence_id in source_ids],
            "metrics": [item.model_dump(mode="json") for item in seed.metrics
                        if set(item.input_evidence_ids) <= source_ids] if role == "market_context" else [],
            "instruction": "只提出证据绑定的假设、必要与失效条件、替代解释。不得创造事实。"}
        if valuation and role == "operating_quality" and seed.valuation is not None:
            contexts[role]["valuation"] = {"assessment": seed.valuation.assessment.model_dump(mode="json"), "input_evidence_ids": seed.valuation.input_evidence_ids, "input_sha256": seed.valuation.input_sha256}
            contexts[role]["valuation_instruction"] = "估值只引用估值事实。倍数和历史定位不能证明内在价值；参考区间依赖已保存盈利和历史倍数假设，无锚点时不得编造合理价格。经营判断仍需财务事实。"
        if scoped:
            contexts[role]["view_scope"] = {"role": role, "coverage_is": "isolated_specialist_input_only",
                "instruction": "未在本专项看到的资料不等于全局缺失；unknowns只描述本专项待查问题。"}
        if report_policy is not None:
            from tradingagents.research.company_basics import foundation_context
            contexts[role]["company_foundation"] = foundation_context(seed)
            contexts[role]["global_coverage"] = global_coverage(seed)
        if minimum and role == "operating_quality":
            contexts[role]["local_checks"] = seed.evidence_checks.model_dump(mode="json")
            contexts[role]["minimum_evidence_instruction"] = "局部检查仅回答其命名问题。可选数据缺失保留已有局部判断；会计桥不证明经济因果，同行样本和机构预测不证明合理价值。"
        if numeric:
            from tradingagents.research.numeric_narrative import prepare_numeric_context
            contexts[role] = prepare_numeric_context(role, contexts[role], seed, identity=ledger.journal.state["identity"])
        logical = "native." + role
        if ledger.cached_result(logical) is None and not any(
            item.logical_call_id == logical and item.dispatched_at is not None for item in ledger.records()
        ):
            # Stable reservation order before fan-out: the last budget unit
            # cannot be won by thread timing.
            reservations[role] = ledger.reserve(BudgetBucket.MAIN_ANALYSIS, stage=logical, logical_call_id=logical)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending = {role: pool.submit(_call, role, context, SpecialistProposalV1,
            caller=caller, ledger=ledger, cancelled=cancelled, reservation=reservations.get(role))
            for role, context in contexts.items()}
        proposals = {role: pending[role].result() for role in ROLE_ORDER if role in pending}
    claims = list(seed.model_dump(mode="json")["claims"])
    hypotheses, conditions, limits = [], {}, list(seed.limitations)
    if company_policy is not None:
        limits.append(company_policy)
    if report_policy is not None:
        limits.append(report_policy)
    if numeric:
        limits.append(NUMERIC_NARRATIVE_POLICY)
    origins = {}
    facts_by_id = {item.claim_id: item for item in seed.claims}
    metric_evidence = {metric.metric_id: metric.input_evidence_ids for metric in seed.metrics}
    for role in ROLE_ORDER:
        proposal = proposals.get(role)
        if proposal is None:
            if role in contexts:
                limits.append("native_stage_unavailable:" + role)
            continue
        try:
            accepted = saved_specialist_acceptance(ledger.journal.state, role, proposal)
        except (ValueError, KeyError, TypeError):
            raise CatalystCheckpointConflict("native specialist acceptance invalid") from None
        indices = accepted.indices if accepted else tuple(range(len(proposal.hypotheses)))
        if accepted:
            limits.extend(f"native_hypothesis_rejected:{role}:{r.code}:{r.index}" for r in accepted.rejections)
            if accepted.rejections and not proposal.hypotheses:
                limits.append("native_stage_unavailable:" + role)
        facts = {item.claim_id: item.evidence_ids for item in views[role]}
        initial_hypotheses = len(hypotheses)
        for index, item in zip(indices, proposal.hypotheses, strict=True):
            # A proposal that cites evidence outside its own scope is rejected,
            # but only that proposal: the kernel drops the offending hypothesis
            # and records why. Terminating the run would discard every other
            # specialist's valid work and make one bad reference unrecoverable.
            try:
                validate_hypothesis_references(item, facts, metric_evidence)
            except NativeEvidenceBindingError as exc:
                suffix = f":{index}" if policy else ""
                limits.append(f"native_hypothesis_rejected:{role}:{exc.code}" + suffix)
                continue
            hid = "h." + canonical_sha256({"input": identity, "role": role, "index": index,
                                           "proposal": item.model_dump(mode="json")})
            origins[hid] = role
            cid = "i." + hid[2:]
            evidence_ids = tuple(dict.fromkeys(key for fact_id in item.supporting_fact_ids
                                for key in facts_by_id[fact_id].evidence_ids))
            claims.append({"claim_id": cid, "kind": "inference", "statement": item.statement,
                           "evidence_ids": evidence_ids, "supporting_fact_ids": item.supporting_fact_ids})
            hypotheses.append({"hypothesis_id": hid, "claim_id": cid, "input_snapshot_id": seed.snapshots[0].snapshot_id,
                "origin": "hypothesis_stage", "assumptions": [c.text for c in item.conditions if c.condition_role == "necessary"],
                "invalidation_conditions": [c.text for c in item.conditions if c.condition_role == "invalidation"],
                "limitations": ["alternative_explanation:" + item.alternative_explanation]})
            for condition in item.conditions:
                bound = {"hypothesis_id": hid, "input_snapshot_id": seed.snapshots[0].snapshot_id,
                         **condition.model_dump(mode="json")}
                conditions["condition." + canonical_sha256(bound)] = bound
        if policy and proposal.hypotheses and len(hypotheses) == initial_hypotheses:
            limits.append("native_stage_unavailable:" + role)
        limits.extend("specialist_unknown:" + (role+":" if scoped else "") + item for item in proposal.unknowns)
    current = _validated(seed, claims=claims, hypotheses=hypotheses, limitations=limits)
    _bound_put(ledger.journal, "native_conditions", conditions)
    # Opaque IDs and no author role/order metadata: challenge the claim rather
    # than its named producer. Each condition remains immutable and bound.
    critic_context = {"mode": seed.mode, "question": question,
        "record": {**current.model_dump(mode="json"),
            "claims": sorted(current.model_dump(mode="json")["claims"], key=lambda item: item["claim_id"]),
            "hypotheses": sorted(hypotheses, key=lambda item: item["hypothesis_id"])}, "conditions": conditions,
        "instruction": "检验假设的证据与替代解释；明确材料可返回零挑战；只引用给定假设和条件，不强制看多或看空。"}
    if scoped:
        critic_context["global_coverage"] = global_coverage(current)
        critic_context["coverage_scope_instruction"] = "specialist_unknown为专项待查，不得据此断言全局来源缺失。"
    challenge_schema = ChallengesProposalV3 if directed else ChallengesProposalV2 if minimum else ChallengesProposalV1
    if directed:
        from tradingagents.agents.schemas._verification_plan import VERIFIABLE_FIELDS
        critic_context["challenge_check_policy"] = directed
        critic_context["verification_capabilities"] = {
            "financial_fields": {table: sorted(fields) for table, fields in VERIFIABLE_FIELDS.items()},
            "financial_operations": ["value", "difference", "growth"],
            "comparisons_require_same_evidence_id": True,
            "growth_requires_positive_base": True,
            "metric_ids": [m.metric_id for m in current.metrics],
        }
        critic_context["challenge_check_instruction"] = (
            "重要挑战须分类；独立核查命题使用proposed_test和自己的check，不改写或继承原假设条件。"
            "可引用冻结V0中的新增事实，列入supporting_fact_ids。只能检验指定命题，不能自动证明经济因果。"
            "缺来源、未知资料需求、工具能力缺口、未来观察与不可检验分别登记；不得把已有合格输入称为缺失。")
    if minimum:
        critic_context["local_checks"] = seed.evidence_checks.model_dump(mode="json")
        critic_context["check_binding_instruction"] = "可选择给定check_id；它只回答固定证据子问题，不能改名或解决经济母问题。observed_risk仅可选cash_conversion.cfo_yoy_decline，observation_date保留明确后续日期。缺数据不等于风险消失。"
    if numeric:
        critic_context = prepare_numeric_context("challenge", critic_context, current, identity=ledger.journal.state["identity"])
    critique = _call("challenge", critic_context, challenge_schema, caller=caller,
                     ledger=ledger, cancelled=cancelled) if hypotheses else challenge_schema()
    challenges, tasks, bindings = [], [], []
    hypothesis_map = {item.hypothesis_id: item for item in current.hypotheses}
    if critique is None:
        limits.append("native_stage_unavailable:challenge")
    else:
        accepted = saved_challenge_acceptance(ledger.journal.state, critique) if directed else None
        if accepted:
            limits.extend(f"native_challenge_rejected:{r.code}:{r.index}" for r in accepted.rejections)
            if accepted.rejections and not critique.challenges:
                limits.append("native_stage_unavailable:challenge")
        indices = accepted.indices if accepted else tuple(range(len(critique.challenges)))
        for index, item in zip(indices, critique.challenges, strict=True):
            if item.hypothesis_id not in hypothesis_map:
                raise ValueError("challenge references an unknown hypothesis")
            target = hypothesis_map[item.hypothesis_id]
            bound = conditions.get(item.condition_id) if item.condition_id else None
            if item.condition_id and (bound is None or bound["hypothesis_id"] != item.hypothesis_id):
                raise ValueError("challenge selected a condition from another hypothesis")
            challenge_id = "c." + canonical_sha256({"input": identity, "index": index, "challenge": item.model_dump(mode="json")})
            challenges.append({"challenge_id": challenge_id, "target_claim_ids": [target.claim_id],
                "statement": item.statement, "severity": item.severity, "risk_type": item.risk_type,
                "proposed_test": item.proposed_test})
            if directed:
                from tradingagents.research.challenge_checks import challenge_test
                challenges[-1]["test"] = challenge_test(item).model_dump(mode="json")
            if minimum:
                bindings.append({"challenge_id": challenge_id, "check_id": item.check_id,
                    "observed_risk": item.observed_risk, "observation_date": item.observation_date})
            if not directed and bound and bound["check"] is not None:
                tasks.append({"task_id": "t." + challenge_id[2:], "challenge_id": challenge_id,
                    "hypothesis_id": item.hypothesis_id, "condition_role": bound["condition_role"],
                    "condition_text": bound["text"], "check": bound["check"]})
    current = _validated(current, challenges=challenges, limitations=list(dict.fromkeys(limits)),
        **({"challenge_bindings": bindings} if minimum else {}),
        **({"challenge_check_policy": directed} if directed else {}))
    if directed:
        from tradingagents.research.challenge_checks import make_challenge_plan
        plan = make_challenge_plan(current)
    else:
        plan = VerificationPlanV1.model_validate_json(json.dumps({
            "run_id": seed.run_id, "ticker": seed.ticker, "mode": seed.mode,
            "analysis_date": seed.analysis_date.isoformat(), "input_snapshot_id": seed.snapshots[0].snapshot_id,
            "tasks": tasks}))
    execution = execute_verification(current, plan, ledger=ledger, cancelled=cancelled)
    current = execution.record
    if unified:
        from tradingagents.research.unified_dialogue import run_responses
        _bound_put(ledger.journal, "native_origins", origins)
        dialogue = run_responses(current, origins, question, call=_call, caller=caller,
            ledger=ledger, cancelled=cancelled, concurrency=concurrency)
        current = _validated(current, dialogue=dialogue.model_dump(mode="json"))
    synthesis_context = {"mode": seed.mode, "question": question,
        "record": current.model_dump(mode="json"), "verification": execution.model_dump(mode="json"),
        "dimension_policy": dimension_policy(current, scoped=scoped, valuation=valuation),
        "instruction": "核查仅证明条件；不能据此关闭经济假设挑战。按dimension_policy顺序输出维度，所有挑战保留unresolved。"}
    if valuation:
        synthesis_context["dimension_claim_ids"] = dimension_claim_ids(current)
        synthesis_context["dimension_binding_instruction"] = "每个维度只能引用dimension_claim_ids中该维度的ID。允许空引用并明确待核查；估值不得引用纯财务或市场统计推断。"
    if scoped:
        synthesis_context["global_coverage"] = global_coverage(current)
        synthesis_context["coverage_scope_instruction"] = "专项未知项只代表对应专项输入/分析范围。全局缺失只按global_coverage和已保存来源判断；不得把缺经营明细写成无财务、把缺基准写成无行情。"
    if minimum:
        from tradingagents.research.minimum_evidence import (
            challenge_assessments as local_assessments,
        )
        synthesis_context["local_check_assessments"] = [a.model_dump(mode="json") for a in local_assessments(current)]
        synthesis_context["local_check_instruction"] = "引用已保存的局部核查结果和回答范围；经济母问题仍未解决。schema中的challenge_assessments保留unresolved提议，最终局部outcome由代码生成，不得自行宣称风险已消除。"
    if unified:
        from tradingagents.research.unified_assessment import stance_ceiling
        synthesis_context["unified_instruction"] = "回答投资吸引力，逐条裁决所有挑战并绑定对应回应ID。修正/撤回的原推断禁止作为肯定性支撑；修正理由须引用回应及其事实。缺经营/估值用insufficient_evidence；critical未解决或无估值锚点不得favorable。改变判断条件引用hypothesis_id与原失效条件文本/索引。裁决不能改变代码局部outcome。"
        if company_policy is not None:
            synthesis_context["unified_instruction"] = synthesis_context["unified_instruction"].replace(
                "缺经营/估值用insufficient_evidence",
                "缺经营依据用insufficient_evidence；缺估值或合理价值区间只限制估值项并禁止favorable，可根据合格经营依据给出neutral/unfavorable及明确条件，不得把缺区间等同于无研究结果")
        synthesis_context["stance_ceiling"] = stance_ceiling(current, tuple(
            DimensionAssessmentV1(dimension=name, status=status, judgement=reason,
                claim_ids=tuple(dimension_claim_ids(current)[name]), limitations=(reason,))
            for name, (status, reason) in dimension_policy(current, scoped=scoped, valuation=valuation).items()))
        if report_policy is not None:
            synthesis_context["unified_instruction"] = "形成有依据的公司判断，资料缺口只限制对应章节。缺经营细项或估值区间禁止favorable，但可用合格引用理由给出谨慎neutral/unfavorable；没有整体判断时选insufficient_evidence，交付时显示未形成评级。修正/撤回原推断不得用于肯定支撑。失效条件只选hypothesis_id/index，原文由代码恢复；每项裁决只选challenge_id并给rationale，回应ID和处理状态由代码绑定。"
    if numeric:
        synthesis_context = prepare_numeric_context("synthesis", synthesis_context, current, identity=ledger.journal.state["identity"])
    synthesis = _call("synthesis", synthesis_context,
        SynthesisProposalV3 if unified else SynthesisProposalV2 if minimum else SynthesisProposalV1, caller=caller, ledger=ledger, cancelled=cancelled) if seed.claims else None
    if report_policy is not None and cancelled():
        raise AnalysisCancelled("native report cancelled before assembly")
    if synthesis is None:
        limits.append("native_synthesis_unavailable")
        dimensions = tuple(DimensionAssessmentV1(dimension=name, status="unresolved", judgement="证据或综合环节不足。",
                            limitations=(reason,)) for name, (_, reason) in dimension_policy(current, scoped=scoped, valuation=valuation).items())
        judgement, next_check, keys, primary = "资料或综合环节不足，暂不能形成完整研究判断。", "补齐缺失资料并重新核查。", (), None
        challenge_assessments = tuple(ChallengeAssessmentV1(challenge_id=item.challenge_id,
                                     rationale="未完成对整体假设的核查。") for item in current.challenges)
        if report_policy is not None:
            from tradingagents.research.report_delivery import retained_summary
            dimensions, keys = retained_summary(current, numeric_policy=numeric)
            judgement = "公司基础报告与已有专项结果已交付；综合阶段未完成，暂未形成总体评级。"
            next_check = "补充各章节列明的具体资料，并在后续完成综合分析。"
            primary = next((item.challenge_id for item in current.challenges if item.severity == "critical"), None)
    else:
        dimensions = gate_dimensions(current, synthesis.dimensions, scoped=scoped, valuation=valuation,
                                    sections=getattr(synthesis, "synthesis_sections", None))
        judgement, next_check, keys, primary = synthesis.judgement, synthesis.next_check, synthesis.key_claim_ids, synthesis.primary_challenge_id
        challenge_assessments = synthesis.challenge_assessments
        critical_ids = {item.challenge_id for item in current.challenges if item.severity == "critical"}
        if critical_ids and primary not in critical_ids:
            primary = next(item.challenge_id for item in current.challenges if item.severity == "critical")
    section_delivery = getattr(synthesis, "synthesis_sections", None)
    complete = (not (section_delivery and any(s.status == "unavailable" for s in section_delivery.sections))
                and not (unified and any(r.status == "unavailable" for r in current.dialogue.responses)) and synthesis is not None and not any(item.status == "unresolved" for item in dimensions)
                and not any(item.startswith(("native_stage_unavailable:", "native_hypothesis_rejected:")) for item in limits))
    if minimum:
        challenge_assessments = local_assessments(current)
    extra = {}
    if unified:
        from tradingagents.research.unified_synthesis import investment_fields
        extra = investment_fields(current, synthesis, dimensions)
        if extra.pop("force_insufficient", False):
            judgement = "关键经营或估值依据不足，暂不能形成完整投资吸引力判断。"
    assessment = (ResearchAssessmentV3 if unified else ResearchAssessmentV2 if minimum else ResearchAssessmentV1)(input_snapshot_id=current.snapshots[-1].snapshot_id,
        research_question=question, judgement=judgement, dimensions=dimensions, key_claim_ids=keys,
        primary_challenge_id=primary, next_check=next_check, challenge_assessments=challenge_assessments,
        completeness="complete" if complete else "partial",
        quality="PASS" if complete and not current.challenges else "LOW_CONFIDENCE",
        forward_window_calendar_days=84 if seed.mode == "catalyst_research" else None,
        limitations=tuple(dict.fromkeys(limits)), **extra)
    output = _validated(current, assessment=assessment.model_dump(mode="json"), limitations=list(dict.fromkeys(limits)))
    if numeric:
        from tradingagents.research.numeric_integration import attach_numeric_attribution
        output = attach_numeric_attribution(output, ledger.journal)
    ledger.record_result("native.output", {"identity": identity, "record": output.model_dump(mode="json")})
    return output
