"""Atomic, independent supplement state; never touches research checkpoints."""

from tradingagents.agents.schemas._report_explanation import ExplanationJob

EXPLANATION_LOCATOR = "supplements/report-explanation-v1.json"


def read_explanation_job(store, run_id):
    from tradingagents.runtime.store import RunNotFound
    try:
        value = store.read_fixed_json(run_id, EXPLANATION_LOCATOR)
    except RunNotFound:
        return None
    job = ExplanationJob.model_validate(value)
    if job.run_id != run_id:
        raise ValueError("explanation run mismatch")
    return job


def save_explanation_job(store, job):
    store.write_fixed_json(job.run_id, EXPLANATION_LOCATOR, job.model_dump(mode="json"))
