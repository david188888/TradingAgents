"""Reading coverage survives batching, sparse replies and bounded failures."""
import json
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from tests import test_report_explanation as fixtures
from tests.test_report_explanation import FakeProvider, wait_job
from tradingagents.execution.report_explanation import ExplanationService
from tradingagents.research.report_explanation import explanation_targets, indicator_presentations
from tradingagents.runtime.report_explanation import read_explanation_job, save_explanation_job
from tradingagents.web.report_explanation import project_report_explanation

published = fixtures.published


def many_record(record, count=50):
    # Distinct addresses for the same saved fact exercise scheduling without
    # inventing a new economic observation or changing its source binding.
    indicators = indicator_presentations(record)
    fact = next(c for c in record.claims if c.kind == "fact" and "claim:" + c.claim_id not in indicators)
    return record.model_copy(update={"claims": (*record.claims, *(
        fact.model_copy(update={"claim_id": f"f.batch.{i}", "limitations": ()}) for i in range(count)))})


def enable(store, run_id):
    snapshot = store.read_snapshot(run_id)
    store.write_snapshot_atomic(snapshot.evolve(metadata={**snapshot.metadata,
        "research_delivery_policy": "evidence-packets-v1"}))


def test_fresh_targets_are_not_silently_cut_off_at_32(published):
    _, record, _ = published
    large = many_record(record)
    targets, excluded = explanation_targets(large, indicator_presentations(large), batched=True)
    assert len(targets) > 32
    assert all(f"claim:f.batch.{i}" in targets for i in range(50))
    assert "capacity_limited" not in excluded.values()
    legacy, _ = explanation_targets(large, indicator_presentations(large))
    assert len(legacy) <= 32


def test_batches_cover_all_targets_and_preserve_professional_record(published):
    store, record, _ = published
    enable(store, record.run_id)
    large = many_record(record)
    provider = FakeProvider()
    service = ExplanationService(store, lambda _: (large, None), client_factory=provider.factory)
    before = deepcopy(record.model_dump(mode="json"))
    service.start(record.run_id)
    job = wait_job(service, store, record.run_id)
    assert job.state == "available"
    assert len(job.entries) == len(job.target_hashes) > 32
    assert len(provider.calls) > 1
    for prompt in provider.calls:
        targets = json.loads(prompt.split("\nDATA:\n", 1)[1])
        assert len(targets) <= 16
        assert len(json.dumps(targets, ensure_ascii=False)) <= 32000
    assert record.model_dump(mode="json") == before
    service.close()


def test_sparse_response_retries_only_the_missing_target_ids(published):
    store, record, _ = published
    enable(store, record.run_id)
    large = many_record(record, 20)

    class Sparse(FakeProvider):
        def invoke(self, prompt):
            targets = json.loads(prompt.split("\nDATA:\n", 1)[1])
            if not self.calls:
                self.first_ids = {t["target"] for t in targets}
                self.accepted_ids = {t["target"] for t in targets[:2]}
                targets = targets[:2]
                response = json.dumps({"entries": [{"target": t["target"], "explanation": "保留原有条件判断，仍需后续核查。",
                    "uncertainty": "尚不能确认原因。", "references": t["references"][:1]} for t in targets]})
                self.responses = iter([response])
            return super().invoke(prompt)

    provider = Sparse()
    service = ExplanationService(store, lambda _: (large, None), client_factory=provider.factory)
    service.start(record.run_id)
    job = wait_job(service, store, record.run_id)
    assert job.state == "available"
    second_ids = {t["target"] for t in json.loads(provider.calls[1].split("\nDATA:\n", 1)[1])}
    assert second_ids == provider.first_ids - provider.accepted_ids
    assert len(job.entries) == len(job.target_hashes)
    service.close()


def test_total_requests_are_bounded_even_when_the_model_omits_everything(published):
    store, record, _ = published
    enable(store, record.run_id)
    large = many_record(record, 400)
    provider = FakeProvider(['{"entries":[]}'] * 100)
    service = ExplanationService(store, lambda _: (large, None), client_factory=provider.factory)
    service.start(record.run_id)
    job = wait_job(service, store, record.run_id)
    assert len(provider.calls) == 24
    assert job.reason_code == "request_limit_reached"
    assert job.state == "failed"
    assert len(job.unavailable_targets) == len(job.target_hashes)
    before = len(provider.calls)
    service.start(record.run_id, retry=True)
    assert len(provider.calls) == before
    assert read_explanation_job(store, record.run_id).state == "failed"
    service.close()


def test_accepted_batch_is_visible_while_later_batch_is_pending(published, monkeypatch):
    store, record, _ = published
    enable(store, record.run_id)
    large = many_record(record)
    entered, release = threading.Event(), threading.Event()
    provider = FakeProvider()
    original = provider.invoke

    def block_second(prompt):
        if provider.calls:
            entered.set()
            assert release.wait(4)
        return original(prompt)

    provider.invoke = block_second
    monkeypatch.setattr("tradingagents.web.report_explanation.load_explanation_record", lambda *a: (large, None))
    service = ExplanationService(store, lambda _: (large, None), client_factory=provider.factory)
    try:
        service.start(record.run_id)
        assert entered.wait(4)
        job = read_explanation_job(store, record.run_id)
        assert job.state == "generating" and len(job.entries) == 16
        view = project_report_explanation(store, record.run_id, service=service)
        assert view["state"] == "generating" and len(view["entries"]) == 16
        assert view["coverage"] == {"total": len(job.target_hashes), "explained": 16,
                                    "pending": len(job.target_hashes) - 16, "unavailable": 0}
    finally:
        release.set()
        wait_job(service, store, record.run_id)
        service.close()


def test_interrupted_dispatch_is_not_resent_and_retry_keeps_deadline(published, monkeypatch):
    store, record, _ = published
    enable(store, record.run_id)
    large = many_record(record, 20)
    provider = FakeProvider()
    service = ExplanationService(store, lambda _: (large, None), client_factory=provider.factory)
    monkeypatch.setattr("tradingagents.web.report_explanation.load_explanation_record", lambda *a: (large, None))
    service.start(record.run_id)
    completed = wait_job(service, store, record.run_id)
    lost = completed.attempts[0].model_copy(update={"outcome": "unknown"})
    interrupted = completed.model_copy(update={"state": "generating", "entries": {}, "attempts": (lost,),
                                              "unavailable_targets": {}, "result_artifact_id": None, "result_sha256": None})
    save_explanation_job(store, interrupted)
    before = len(provider.calls)
    assert project_report_explanation(store, record.run_id)["state"] == "interrupted"
    assert len(provider.calls) == before
    service.start(record.run_id, retry=True)
    recovered = wait_job(service, store, record.run_id)
    assert recovered.job_id == completed.job_id and recovered.deadline_at == completed.deadline_at
    assert recovered.state == "partial"
    assert all(recovered.unavailable_targets[k] == "response_unknown" for k in lost.target_ids)
    for prompt in provider.calls[before:]:
        assert not set(lost.target_ids).intersection(t["target"] for t in json.loads(prompt.split("\nDATA:\n")[1]))
    expired = recovered.model_copy(update={"deadline_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    save_explanation_job(store, expired)
    before = len(provider.calls)
    assert service.start(record.run_id, retry=True).deadline_at == expired.deadline_at
    assert len(provider.calls) == before
    service.close()


def test_batched_job_requires_aware_deadline_and_bounded_attempts(published):
    from tradingagents.agents.schemas._report_explanation import ExplanationJob

    store, record, _ = published
    enable(store, record.run_id)
    service = ExplanationService(store, lambda _: (record, None), client_factory=FakeProvider().factory)
    service.start(record.run_id)
    job = wait_job(service, store, record.run_id)
    for updates in ({"deadline_at": None}, {"deadline_at": "2026-10-27T12:00:00"},
                    {"attempts": [job.attempts[0].model_dump(mode="json")] * 25}):
        with pytest.raises(ValueError):
            ExplanationJob.model_validate({**job.model_dump(mode="json"), **updates})
    service.close()


def test_one_invalid_explanation_does_not_discard_valid_siblings():
    from tradingagents.execution.explanation_batches import parse_reply

    target = {"target": "x", "references": ["f.one"], "text": "原文"}
    valid = {"target": "x", "explanation": "仍需核查原因。", "references": ["f.one"]}
    reply = json.dumps({"entries": [valid, {"target": "y", "explanation": 123}]})
    assert set(parse_reply(reply, {"x": target})) == {"x"}


def test_received_response_lost_before_acceptance_is_not_resent(published, monkeypatch):
    from tradingagents.execution import explanation_batches

    store, record, _ = published
    enable(store, record.run_id)
    large = many_record(record, 20)
    provider = FakeProvider()
    service = ExplanationService(store, lambda _: (large, None), client_factory=provider.factory)
    original = explanation_batches.parse_reply

    def interrupted(response, targets):
        raise RuntimeError("interrupt after response before accepted entries persist")

    monkeypatch.setattr(explanation_batches, "parse_reply", interrupted)
    service.start(record.run_id)
    first = wait_job(service, store, record.run_id)
    assert first.reason_code == "model_failed" and len(provider.calls) == 1
    first_targets = set(first.attempts[0].target_ids)
    monkeypatch.setattr(explanation_batches, "parse_reply", original)
    service.start(record.run_id, retry=True)
    recovered = wait_job(service, store, record.run_id)
    assert all(recovered.unavailable_targets[k] == "response_unknown" for k in first_targets)
    for prompt in provider.calls[1:]:
        assert not first_targets.intersection(t["target"] for t in json.loads(prompt.split("\nDATA:\n")[1]))
    service.close()
