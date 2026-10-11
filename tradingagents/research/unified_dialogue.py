"""One targeted reply per challenged specialist, with durable frozen inputs."""

from concurrent.futures import ThreadPoolExecutor

from tradingagents.agents.schemas._research_dialogue import (
    HypothesisOriginV1,
    ResearchDialogueV1,
    ResearchResponseV1,
    ResponsesProposalV1,
    response_fact_ids,
)
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.execution.budget import BudgetBucket
from tradingagents.research.native_policy import ROLE_ORDER


def validate_response_proposal(record, role, proposal, assignments):
    supplied = {r.challenge_id: r for r in proposal.responses}
    if len(supplied) != len(proposal.responses) or supplied.keys() != assignments.keys():
        raise ValueError("specialist must answer each assigned challenge exactly once")
    bindings = {b.challenge_id: b.check_id for b in record.challenge_bindings or ()}
    for cid, reply in supplied.items():
        if reply.hypothesis_id != assignments[cid]:
            raise ValueError("reply changed the target hypothesis")
        if (len(set(reply.supporting_fact_ids)) != len(reply.supporting_fact_ids)
                or not set(reply.supporting_fact_ids) <= response_fact_ids(record, role, cid)):
            raise ValueError("reply cites facts outside its frozen scope")
        if len(set(reply.check_ids)) != len(reply.check_ids) or not set(reply.check_ids) <= ({bindings[cid]} - {None}):
            raise ValueError("reply cites an unbound check")
        if reply.disposition in {"maintained", "revised"} and not reply.supporting_fact_ids:
            raise ValueError("maintaining or revising a claim requires facts")


def run_responses(record, origins, question, *, call, caller, ledger, cancelled, concurrency):
    hypotheses = {h.claim_id: h for h in record.hypotheses}
    assignments = {role: {} for role in ROLE_ORDER}
    for challenge in record.challenges:
        hypothesis = hypotheses[challenge.target_claim_ids[0]]
        assignments[origins[hypothesis.hypothesis_id]][challenge.challenge_id] = hypothesis.hypothesis_id
    contexts, reservations = {}, {}
    for role, targets in assignments.items():
        if not targets:
            continue
        stage = "response_" + role
        allowed = {f for cid in targets for f in response_fact_ids(record, role, cid)}
        context = {"role": role, "question": question,
                   "assigned": targets, "allowed_fact_ids": sorted(allowed),
                   "instruction": "只回应分配的挑战，每条一次。维持、修正、撤回或承认无法回答均可。只引用本专项合格事实或绑定核查，不创造事实、条件或新取数；回应不证明经济风险消失。"}
        # Do not expose unrelated specialist assertions to the reply model.
        context["hypotheses"] = [h.model_dump(mode="json") for h in record.hypotheses if h.hypothesis_id in targets.values()]
        context["challenges"] = [c.model_dump(mode="json") for c in record.challenges if c.challenge_id in targets]
        context["verifications"] = [v.model_dump(mode="json") for v in record.verifications if v.challenge_id in targets]
        target_claims = {h.claim_id for h in record.hypotheses if h.hypothesis_id in targets.values()}
        context["assertions"] = [c.model_dump(mode="json") for c in record.claims if c.claim_id in target_claims]
        evidence_ids = {eid for f in record.claims if f.claim_id in allowed for eid in f.evidence_ids}
        context["sources"] = [s.model_dump(mode="json") for s in record.evidence if s.evidence_id in evidence_ids]
        # A reply gets only its own partition and targeted checks, never the other drafts.
        context["facts"] = [f.model_dump(mode="json") for f in record.claims if f.claim_id in allowed]
        context["allowed_facts_by_challenge"] = {cid: sorted(response_fact_ids(record, role, cid)) for cid in targets}
        from tradingagents.research.minimum_evidence import challenge_assessments
        context["check_results"] = [a.model_dump(mode="json") for a in challenge_assessments(record) if a.challenge_id in targets]
        context["local_checks"] = [b.model_dump(mode="json") for b in record.challenge_bindings or () if b.challenge_id in targets]
        contexts[role] = context
        logical = "native." + stage
        if ledger.cached_result(logical) is None and not any(r.logical_call_id == logical and r.dispatched_at for r in ledger.records()):
            reservations[role] = ledger.reserve(BudgetBucket.MAIN_ANALYSIS, stage=logical, logical_call_id=logical)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending = {role: pool.submit(call, "response_" + role, context, ResponsesProposalV1,
                   caller=caller, ledger=ledger, cancelled=cancelled, reservation=reservations.get(role))
                   for role, context in contexts.items()}
        proposals = {role: pending[role].result() for role in ROLE_ORDER if role in pending}
    replies = []
    for role in ROLE_ORDER:
        targets = assignments[role]
        if not targets:
            continue
        proposal = proposals[role]
        if proposal is not None:
            try:
                validate_response_proposal(record, role, proposal, targets)
            except ValueError:
                proposal = None
        supplied = {r.challenge_id: r.model_dump(mode="json") for r in proposal.responses} if proposal else {}
        for cid, hid in targets.items():
            value = supplied.get(cid, {"challenge_id": cid, "hypothesis_id": hid,
                    "disposition": "unanswerable", "rationale": "本专项回应未取得有效保存结果。"})
            rid = "response." + canonical_sha256({"snapshot": record.snapshots[-1].snapshot_id,
                                                  "role": role, "reply": value})
            replies.append(ResearchResponseV1(**value, response_id=rid, role=role,
                status="available" if proposal else "unavailable",
                reason_code=None if proposal else "native_response_unavailable"))
    return ResearchDialogueV1(input_snapshot_id=record.snapshots[-1].snapshot_id,
        origins=tuple(HypothesisOriginV1(hypothesis_id=h, role=r) for h, r in origins.items()), responses=tuple(replies))
