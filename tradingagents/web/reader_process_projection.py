"""Bounded, read-only native process and validated role output projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tradingagents.agents.schemas._native_stage import (
    ChallengesProposalV1,
    ChallengesProposalV2,
    SpecialistProposalV1,
    SynthesisProposalV1,
    SynthesisProposalV2,
)
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.runtime.catalyst_checkpoint import load_checkpoint
from tradingagents.runtime.native_observation import SDK_OBSERVATION_KEY, NativeSDKObservationV1
from tradingagents.web.native_reader_versions import saved_dimensions_match, saved_fact_views
from tradingagents.web.reader_process_models import (
    AgentKey,
    ClaimOrigin,
    NativeCounts,
    ObservedCount,
    OutputRelation,
    ReaderAgentDTO,
    ReaderProcessDTO,
    ReaderRole,
)
from tradingagents.web.research_record_projection import project_research_record

VERSIONS = {
    "evidence-production-v1": "native-research-kernel-v1",
    "evidence-production-v2": "native-research-kernel-v1",
    "evidence-production-v3": "native-research-kernel-v2",
    "evidence-production-v4": "native-research-kernel-v3",
    "evidence-production-v5": "native-research-kernel-v4",
}
ROLE_INFO = {
    "evidence": (
        "证据冻结",
        "保存符合时间与来源要求的事实，计算固定证据子问题。",
        "公开资料、来源时间和保存内容；由代码整理，不调用研究模型。",
    ),
    "operating_quality": (
        "经营研究",
        "从经营与财务证据提出假设、成立条件和替代解释。",
        "冻结证据中的经营、财务及合格估值事实；只读取本专项允许的资料。",
    ),
    "event_context": (
        "事件研究",
        "判断公告与事件可能带来什么变化，以及兑现条件。",
        "冻结证据中的公告与事件事实；未在本专项看到不代表全局缺失。",
    ),
    "market_context": (
        "市场研究",
        "解释历史行情和量化背景，提出待核查假设。",
        "合格行情事实及代码计算的历史指标；价格联动不能证明业务联系。",
    ),
    "challenge": (
        "独立挑战",
        "检查假设的证据缺口、替代解释及可检验条件。",
        "保存的假设、支撑事实及条件；不提供专项作者身份。",
    ),
    "synthesis": (
        "研究综合",
        "回答研究问题，选择重点依据、主要疑点和下一步。",
        "事实、假设、挑战和已执行核查结果；最终发布受代码规则约束。",
    ),
    "code_checks": (
        "代码核查与发布",
        "核对固定证据子问题和可执行条件，约束最终发布范围。",
        "已保存事实、固定检查与条件验证；不额外创建一个 Agent。",
    ),
}
SAFE_FAILURES = {
    "document_parser_not_installed",
    "source_transport_unavailable",
    "document_fetch_failed",
    "document_parse_failed",
}
MODEL_ROLES = tuple(key for key in ROLE_INFO if key not in {"evidence", "code_checks"})


def count(value=None, *, complete="not_recorded", basis="not_recorded"):
    return ObservedCount(value=value, completeness=complete, basis=basis)


def native_counts(checkpoint, *, role=None):
    """Budget dispatch and SDK authorization are different measurements."""
    if checkpoint is None:
        missing = count()
        return NativeCounts(
            main_budget=missing,
            repair_budget=missing,
            sdk_main=missing,
            sdk_repair=missing,
            sdk_total=missing,
            data_capability=missing,
            data_http=missing,
        )
    records = [r for r in checkpoint["records"] if r.get("dispatched_at") is not None]
    scoped = [r for r in records if role is None or r.get("stage") == "native." + role]

    def budget(bucket, rows=scoped):
        return count(
            sum(r["bucket"] == bucket for r in rows),
            complete="complete",
            basis="budget_dispatch_authorization",
        )

    coverage = False
    try:
        marker = NativeSDKObservationV1.model_validate(checkpoint.get(SDK_OBSERVATION_KEY))
        coverage = marker.complete and checkpoint["identity"].get("workflow_version") in VERSIONS
    except (ValueError, TypeError):
        pass
    known_workflow = checkpoint["identity"].get("workflow_version") in VERSIONS
    flags = (
        sum(
            checkpoint.get("native.model." + key + ".dispatched") is True
            for key in ((role,) if role else MODEL_ROLES)
        )
        if known_workflow
        else 0
    )
    repair = sum(r["bucket"] == "structured_repair" for r in scoped) if known_workflow else 0

    def sdk(value):
        return count(
            value if coverage or value else None,
            complete="complete" if coverage else "known_lower_bound" if value else "not_recorded",
            basis="sdk_dispatch_authorization",
        )

    main, repairs = sdk(flags), sdk(repair)
    if role in {"evidence", "code_checks"}:
        main = repairs = count(0, complete="complete", basis="code_no_model")
    total_complete = main.completeness == repairs.completeness == "complete"
    known = [item.value for item in (main, repairs) if item.value is not None]
    total = count(
        sum(known) if known else None,
        complete="complete" if total_complete else "known_lower_bound" if known else "not_recorded",
        basis="sdk_dispatch_authorization",
    )
    return NativeCounts(
        main_budget=budget("main_analysis"),
        repair_budget=budget("structured_repair"),
        sdk_main=main,
        sdk_repair=repairs,
        sdk_total=total,
        data_capability=budget("data_capability_calls", records),
        data_http=budget("data_http_attempts", records),
    )


@dataclass
class Context:
    snapshot: Any
    sequence: int
    events: list
    checkpoint: dict | None
    record: ResearchRecordV1 | None
    seed: ResearchRecordV1 | None
    reason: str | None


def _context(store, run_id, through=None):
    snapshot = store.read_snapshot(run_id)
    sequence = snapshot.latest_sequence if through is None else through
    if sequence < 0 or sequence > snapshot.latest_sequence:
        raise ValueError("reader_sequence_unavailable")
    events = store.read_events(run_id, through=sequence)
    reason, cp, seed, record = None, None, None, None
    if (snapshot.metadata or {}).get("research_profile") != "evidence_v1":
        return Context(snapshot, sequence, events, None, None, None, "profile_not_applicable")
    try:
        cp = load_checkpoint(store, run_id, through=sequence)
    except Exception:
        reason = "checkpoint_unavailable"
    if cp is None:
        return Context(
            snapshot, sequence, events, None, None, None, reason or "checkpoint_not_recorded"
        )
    version = cp["identity"].get("workflow_version")
    if version not in VERSIONS:
        return Context(snapshot, sequence, events, cp, None, None, "workflow_unsupported")
    try:
        identity = cp["identity"]
        if (identity.get("ticker"), identity.get("mode"), identity.get("cutoff")) != (
            snapshot.ticker,
            snapshot.mode,
            snapshot.analysis_date,
        ):
            raise ValueError("identity")
        published = project_research_record(store, run_id, through=sequence)
        if published["state"] != "ready":
            return Context(snapshot, sequence, events, cp, None, None, "publication_pending")
        record = ResearchRecordV1.model_validate(published["record"])
        seed = ResearchRecordV1.model_validate(cp["native_seed"])
        native_input = cp["native_input"]
        if native_input != {
            "workflow_version": VERSIONS[version],
            "seed_sha256": canonical_sha256(seed),
            "research_question": record.assessment.research_question,
        }:
            raise ValueError("input")
        output = cp["results"]["native.output"]
        if output["identity"] != native_input or canonical_sha256(
            ResearchRecordV1.model_validate(output["record"])
        ) != canonical_sha256(record):
            raise ValueError("output")
        if (seed.run_id, seed.ticker, seed.mode, seed.analysis_date, seed.construction) != (
            record.run_id,
            record.ticker,
            record.mode,
            record.analysis_date,
            "native",
        ):
            raise ValueError("seed")
        if (
            seed.assessment
            or seed.hypotheses
            or seed.challenges
            or seed.verifications
            or len(seed.snapshots) != 1
            or any(c.kind != "fact" for c in seed.claims)
        ):
            raise ValueError("seed_shape")
        claims = {c.claim_id: c for c in record.claims}
        sources = {s.evidence_id: s for s in record.evidence}
        if (
            any(claims.get(c.claim_id) != c for c in seed.claims)
            or any(sources.get(s.evidence_id) != s for s in seed.evidence)
            or seed.snapshots[0] not in record.snapshots
        ):
            raise ValueError("seed_content")
    except Exception:
        return Context(snapshot, sequence, events, cp, record, None, "output_identity_unavailable")
    return Context(snapshot, sequence, events, cp, record, seed, None)


def _proposal(ctx, role):
    cp, record, seed = ctx.checkpoint, ctx.record, ctx.seed
    version = cp["identity"]["workflow_version"]
    saved = cp["results"].get("native." + role)
    if saved is None:
        return None, (), ()
    schema = (
        SpecialistProposalV1
        if role in {"operating_quality", "event_context", "market_context"}
        else (ChallengesProposalV2 if version == "evidence-production-v5" else ChallengesProposalV1)
        if role == "challenge"
        else (SynthesisProposalV2 if version == "evidence-production-v5" else SynthesisProposalV1)
    )
    proposal = schema.model_validate(saved["proposal"])
    claims = {c.claim_id: c for c in record.claims}
    hypotheses = {h.hypothesis_id: h for h in record.hypotheses}
    cids, chids = [], []
    if isinstance(proposal, SpecialistProposalV1):
        allowed = {f.claim_id for f in saved_fact_views(seed, version)[role]}
        for index, item in enumerate(proposal.hypotheses):
            hid = "h." + canonical_sha256(
                {
                    "input": cp["native_input"],
                    "role": role,
                    "index": index,
                    "proposal": item.model_dump(mode="json"),
                }
            )
            cid = "i." + hid[2:]
            claim, hypothesis = claims[cid], hypotheses[hid]
            if (
                not set(item.supporting_fact_ids) <= allowed
                or claim.kind != "inference"
                or claim.statement != item.statement
                or claim.supporting_fact_ids != item.supporting_fact_ids
                or claim.evidence_ids
                != tuple(
                    dict.fromkeys(
                        e for fid in item.supporting_fact_ids for e in claims[fid].evidence_ids
                    )
                )
            ):
                raise ValueError("specialist_binding")
            if (
                hypothesis.claim_id != cid
                or hypothesis.input_snapshot_id != seed.snapshots[0].snapshot_id
                or hypothesis.assumptions
                != tuple(c.text for c in item.conditions if c.condition_role == "necessary")
                or hypothesis.invalidation_conditions
                != tuple(c.text for c in item.conditions if c.condition_role == "invalidation")
                or hypothesis.limitations
                != ("alternative_explanation:" + item.alternative_explanation,)
            ):
                raise ValueError("hypothesis_binding")
            for condition in item.conditions:
                check = condition.check
                if check is not None:
                    if check.kind == "financial":
                        operands = (
                            (check.current,) if check.base is None else (check.current, check.base)
                        )
                        if any(o.evidence_id not in claim.evidence_ids for o in operands):
                            raise ValueError("condition_evidence_scope")
                    else:
                        metric = next(
                            (m for m in seed.metrics if m.metric_id == check.metric_id), None
                        )
                        if metric is None or not set(metric.input_evidence_ids) <= set(
                            claim.evidence_ids
                        ):
                            raise ValueError("condition_metric_scope")
                bound = {
                    "hypothesis_id": hid,
                    "input_snapshot_id": seed.snapshots[0].snapshot_id,
                    **condition.model_dump(mode="json"),
                }
                if (
                    cp.get("native_conditions", {}).get("condition." + canonical_sha256(bound))
                    != bound
                ):
                    raise ValueError("condition_binding")
            cids.append(cid)
    elif isinstance(proposal, (ChallengesProposalV1, ChallengesProposalV2)):
        challenges = {c.challenge_id: c for c in record.challenges}
        for index, item in enumerate(proposal.challenges):
            cid = "c." + canonical_sha256(
                {
                    "input": cp["native_input"],
                    "index": index,
                    "challenge": item.model_dump(mode="json"),
                }
            )
            target, challenge = hypotheses[item.hypothesis_id], challenges[cid]
            if (
                challenge.statement,
                challenge.severity,
                challenge.risk_type,
                challenge.proposed_test,
                challenge.target_claim_ids,
            ) != (
                item.statement,
                item.severity,
                item.risk_type,
                item.proposed_test,
                (target.claim_id,),
            ):
                raise ValueError("challenge_binding")
            if (
                item.condition_id
                and cp.get("native_conditions", {}).get(item.condition_id, {}).get("hypothesis_id")
                != item.hypothesis_id
            ):
                raise ValueError("challenge_condition")
            if version == "evidence-production-v5":
                binding = next(b for b in record.challenge_bindings if b.challenge_id == cid)
                if (binding.check_id, binding.observed_risk, binding.observation_date) != (
                    item.check_id,
                    item.observed_risk,
                    item.observation_date,
                ):
                    raise ValueError("check_binding")
            chids.append(cid)
        if tuple(chids) != tuple(c.challenge_id for c in record.challenges):
            raise ValueError("challenge_coverage_binding")
    else:
        assessment = record.assessment
        if (proposal.judgement, proposal.next_check, proposal.key_claim_ids) != (
            assessment.judgement,
            assessment.next_check,
            assessment.key_claim_ids,
        ):
            raise ValueError("synthesis_binding")
        if not saved_dimensions_match(record, proposal.dimensions, version):
            raise ValueError("dimension_binding")
        primary = proposal.primary_challenge_id
        critical = [c.challenge_id for c in record.challenges if c.severity == "critical"]
        if critical and primary not in critical:
            primary = critical[0]
        if primary != assessment.primary_challenge_id:
            raise ValueError("primary_binding")
        if (
            version != "evidence-production-v5"
            and proposal.challenge_assessments != assessment.challenge_assessments
        ):
            raise ValueError("assessment_binding")
        if len({a.challenge_id for a in proposal.challenge_assessments}) != len(
            proposal.challenge_assessments
        ) or any(
            a.challenge_id not in {c.challenge_id for c in record.challenges}
            for a in proposal.challenge_assessments
        ):
            raise ValueError("synthesis_challenge_reference")
        cids.extend(proposal.key_claim_ids)
        chids.extend(a.challenge_id for a in proposal.challenge_assessments)
    return proposal, tuple(cids), tuple(chids)


def _agent(ctx, role):
    origin = "code" if role in {"evidence", "code_checks"} else "model"
    base = {
        "run_id": ctx.snapshot.run_id,
        "source_sequence": ctx.sequence,
        "role_key": role,
        "origin": origin,
        "input_description": ROLE_INFO[role][2],
    }
    if ctx.reason:
        pending = ctx.reason == "publication_pending"
        saved = ctx.checkpoint and ctx.checkpoint["results"].get("native." + role)
        availability = (
            "pending_publication"
            if pending and saved
            else "not_recorded"
            if pending
            else "not_applicable"
            if ctx.reason == "profile_not_applicable"
            else "unsupported"
            if ctx.reason == "workflow_unsupported"
            else "unavailable"
        )
        return ReaderAgentDTO(**base, availability=availability, reason_code=ctx.reason)
    if origin == "code":
        return ReaderAgentDTO(
            **base,
            availability="available",
            code_sections=("facts", "sources", "checks")
            if role == "evidence"
            else ("checks", "verifications", "publication"),
            claim_ids=tuple(c.claim_id for c in ctx.seed.claims),
        )
    try:
        proposal, cids, chids = _proposal(ctx, role)
        if proposal is None:
            if (
                role in {"operating_quality", "event_context", "market_context"}
                and not saved_fact_views(ctx.seed, ctx.checkpoint["identity"]["workflow_version"])[
                    role
                ]
            ):
                return ReaderAgentDTO(
                    **base,
                    availability="not_applicable",
                    reason_code="no_qualified_facts_not_called",
                )
            return ReaderAgentDTO(
                **base,
                availability="not_recorded",
                reason_code="no_hypotheses_not_called"
                if role == "challenge" and not ctx.record.hypotheses
                else "proposal_not_recorded",
            )
        record = ctx.record
        relations = [
            OutputRelation(
                entity_id=cid,
                kind="claim",
                in_record=True,
                is_key=cid in record.assessment.key_claim_ids,
                dimensions=tuple(
                    d.dimension for d in record.assessment.dimensions if cid in d.claim_ids
                ),
                challenge_ids=tuple(
                    c.challenge_id for c in record.challenges if cid in c.target_claim_ids
                ),
            )
            for cid in cids
        ]
        relations += [
            OutputRelation(
                entity_id=cid,
                kind="challenge",
                in_record=True,
                is_key=cid == record.assessment.primary_challenge_id,
            )
            for cid in chids
        ]
        facts = tuple(
            dict.fromkeys(
                f
                for cid in cids
                for f in next(c for c in record.claims if c.claim_id == cid).supporting_fact_ids
            )
        )
        return ReaderAgentDTO(
            **base,
            availability="available",
            proposal=proposal,
            relations=tuple(relations),
            claim_ids=cids,
            challenge_ids=chids,
            input_fact_ids=facts,
        )
    except Exception:
        return ReaderAgentDTO(
            **base, availability="unavailable", reason_code="proposal_binding_unavailable"
        )


def _process(ctx):
    snapshot, cp = ctx.snapshot, ctx.checkpoint
    metadata = snapshot.metadata or {}
    profile = metadata.get("research_profile", "classic")
    statuses = {}
    for event in ctx.events:
        if event.type == "role.status_changed" and event.payload.get("new_status") in {
            "pending",
            "running",
            "completed",
            "failed",
            "cancelled",
            "interrupted",
            "skipped",
            "not_reached",
        }:
            statuses[event.actor_id] = event.payload["new_status"]
    roles, origins, agents = [], [], {}
    if profile == "evidence_v1":
        for key in ROLE_INFO:
            agent = _agent(ctx, key)
            agents[key] = agent
            n = native_counts(cp, role=key)
            roles.append(
                ReaderRole(
                    role_key=key,
                    actor_id="native." + key,
                    label=ROLE_INFO[key][0],
                    origin=agent.origin,
                    purpose=ROLE_INFO[key][1],
                    status=statuses.get("native." + key, "not_recorded")
                    if key != "code_checks"
                    else "not_applicable",
                    output_availability=agent.availability,
                    reason_code=agent.reason_code,
                    output_count=None
                    if agent.availability != "available"
                    else len(agent.claim_ids)
                    if key in {"evidence", "operating_quality", "event_context", "market_context"}
                    else len(agent.challenge_ids)
                    if key == "challenge"
                    else 1
                    if agent.proposal is not None
                    else None,
                    output_sequence=max(
                        (
                            e.sequence
                            for e in ctx.events
                            if e.type == "artifact.written"
                            and e.status == "committed"
                            and isinstance(e.payload.get("committed_sequence"), int)
                            and e.payload["committed_sequence"] <= ctx.sequence
                            and e.payload.get("public_contract") == "research-record-v1"
                        ),
                        default=None,
                    )
                    if agent.availability == "available"
                    else None,
                    main_budget=n.main_budget,
                    sdk_main=n.sdk_main,
                    sdk_repair=n.sdk_repair,
                )
            )
            if key in {"operating_quality", "event_context", "market_context"}:
                origins.extend(ClaimOrigin(claim_id=cid, role_key=key) for cid in agent.claim_ids)
    primary = "not_recorded"
    if agents.get("synthesis") and agents["synthesis"].proposal:
        primary = (
            "synthesis"
            if agents["synthesis"].proposal.primary_challenge_id
            == ctx.record.assessment.primary_challenge_id
            else "code"
        )
    failures = set()
    if cp:
        for value in cp["results"].values():
            code = value.get("source_error_code")
            if code in SAFE_FAILURES:
                failures.add(code)
    return ReaderProcessDTO(
        run_id=snapshot.run_id,
        source_sequence=ctx.sequence,
        profile=profile,
        workflow_version=cp["identity"].get("workflow_version") if cp else None,
        availability="not_applicable"
        if profile != "evidence_v1"
        else "ready"
        if ctx.reason is None
        and all(
            a.availability in {"available", "not_recorded", "not_applicable"}
            for a in agents.values()
        )
        else "partial"
        if cp
        else "unavailable",
        reason_code=ctx.reason,
        question_origin=("user" if metadata["research_question"] is not None else "default")
        if "research_question" in metadata
        else "not_recorded",
        primary_selection=primary,
        counts=native_counts(cp),
        roles=tuple(roles),
        claim_origins=tuple(origins),
        source_failures=tuple(sorted(failures)),
    )


def project_reader_process(store, run_id):
    return _process(_context(store, run_id)).model_dump(mode="json")


def project_reader_agent(store, run_id, role: AgentKey, *, through=None):
    return _agent(_context(store, run_id, through), role).model_dump(mode="json")
