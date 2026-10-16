"""Read-only public explanation projection; generation is a separate command."""

import hashlib
import json

from tradingagents.agents.schemas._report_explanation import (
    EXPLANATION_POLICY,
    ReportExplanationView,
)
from tradingagents.agents.schemas._research_focus import ResearchFocusResponseV1
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.research.report_explanation import (
    explanation_targets,
    indicator_presentations,
    validate_explanation_entry,
)
from tradingagents.runtime.report_explanation import read_explanation_job
from tradingagents.web.focus_projection import project_reader_focus
from tradingagents.web.research_record_projection import project_research_record


def load_explanation_record(store, run_id):
    projected = project_research_record(store, run_id)
    if projected["state"] != "ready":
        raise ValueError("base_unavailable")
    record = ResearchRecordV1.model_validate(projected["record"])
    focus = project_reader_focus(store, run_id)
    return record, ResearchFocusResponseV1.model_validate(focus["response"]) if focus["state"] == "ready" else None


def project_report_explanation(store, run_id, *, service=None):
    snapshot = store.read_snapshot(run_id)
    eligible = (snapshot.status == "completed"
                and snapshot.metadata.get("report_explanation_policy") == EXPLANATION_POLICY)
    view = {"run_id": run_id, "state": "not_generated", "eligible": eligible}
    try:
        record, focus = load_explanation_record(store, run_id)
    except ValueError:
        return ReportExplanationView(**{**view, "state": "unsupported", "eligible": False,
                                       "reason_code": "base_unavailable"}).model_dump(mode="json")
    digest = canonical_sha256(record)
    view.update(base_record_sha256=digest, indicators=indicator_presentations(record))
    if record.construction != "native":
        view.update(state="unsupported", eligible=False, reason_code="historical_workflow")
    try:
        job = read_explanation_job(store, run_id)
        if job is None:
            return ReportExplanationView(**view).model_dump(mode="json")
        if not eligible or record.construction != "native":
            raise ValueError("explanation_policy_mismatch")
        targets, excluded = explanation_targets(record, view["indicators"], focus)
        if (job.base_record_sha256 != digest or job.focus_sha256 != (canonical_sha256(focus) if focus else None)
                or job.targets_sha256 != canonical_sha256(targets)
                or job.target_hashes != {k: t["text_sha256"] for k, t in targets.items()}
                or job.config_sha256 != canonical_sha256(snapshot.metadata.get("effective_config"))
                or job.model != snapshot.quick_think_llm or job.language != snapshot.output_language):
            raise ValueError("explanation_binding_mismatch")
        for key, entry in job.entries.items():
            if key not in targets or entry.target != key:
                raise ValueError("explanation_target_invalid")
            validate_explanation_entry(entry, targets[key])
        if job.state in {"available", "partial"}:
            if not job.result_artifact_id or not job.result_sha256:
                raise ValueError("explanation_result_missing")
            raw = store.read_artifact(run_id, job.result_artifact_id)
            if hashlib.sha256(raw).hexdigest() != job.result_sha256:
                raise ValueError("explanation_result_corrupt")
            result = json.loads(raw)
            if result != {"job_id": job.job_id, "base_record_sha256": digest,
                          "entries": {k: v.model_dump(mode="json") for k, v in job.entries.items()}}:
                raise ValueError("explanation_result_mismatch")
        state = job.state
        if state == "generating" and (service is None or not service.active(run_id, job.job_id)):
            state = "interrupted"
        view.update(state=state, entries=job.entries if job.state in {"available", "partial"} else {}, reason_code=job.reason_code,
                    unavailable_targets={**excluded, **job.unavailable_targets},
                    model=job.model, generated_at=job.generated_at)
    except Exception:
        view.update(state="corrupt", reason_code="explanation_binding_invalid", entries={})
    return ReportExplanationView(**view).model_dump(mode="json")
