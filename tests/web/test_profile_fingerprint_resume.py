"""T12 — resume fingerprint / recovery compatibility across the profile boundary.

Three questions are answered here, and each is answered by a test that fails
without the corresponding change:

1. Does a *reader* upgrade (a new projection over an already-committed
   artifact) require recomputation?  **No.**  The resume fingerprint is built
   from the request, the effective config, the runtime semantics, and the agent
   state schema -- none of which change when a reader is upgraded.  A reader
   upgrade therefore produces a byte-identical fingerprint and the stored
   checkpoint is authorized without a single model or provider call.
2. Is a checkpoint opened under the *same* profile but a different evidence
   policy compatible?  **No.**  A different evidence window means a different
   graph over the same state, so resume must be refused.
3. Is a classic checkpoint resumed under a catalyst_v1 request compatible?
   **No**, and the original stored record must survive the refusal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.runner import PreparedInitialContext
from tradingagents.observability.canonical import (
    AGENT_STATE_SCHEMA_SHA256,
    canonical_sha256,
)
from tradingagents.research.catalyst_evidence_policy import (
    CATALYST_EVIDENCE_POLICY_VERSION,
    CatalystEvidencePolicyV1,
)
from tradingagents.runtime.fingerprint import FingerprintError
from tradingagents.web.fingerprint import (
    CheckpointIncompatible,
    FingerprintCheckpointGuard,
    _build_resume_fingerprint_for_test,
    compare_resume_fingerprints,
)
from tradingagents.web.run_models import RunSnapshot, generate_run_id
from tradingagents.web.store import RunStore

pytestmark = pytest.mark.unit


# Identical to the shape frozen by
# tests/web/test_fingerprint.py::test_resume_fingerprint_document_has_the_exact_
# approved_top_level_shape, so the classic digest below is directly comparable.
EFFECTIVE_CONFIG = {
    "llm_provider": "openai",
    "quick_think_llm": "gpt-4.1-mini",
    "max_tokens": 2048,
    "backend_url": "https://api.example.com/v1?trace=discarded",
}
RUNTIME_PYTHON = {
    "implementation": "cpython",
    "version": "3.12.5",
    "cache_tag": "cpython-312",
    "abi_flags": "",
    "platform": "macosx-14.0-arm64",
}
RUNTIME_DISTRIBUTIONS = [
    {
        "name": "langgraph",
        "version": "1.1.10",
        "record_sha256": "b" * 64,
        "direct_url_sha256": None,
    }
]
INITIAL_CONTEXT = {
    "past_context": "No prior decision memory.",
    "company_of_interest": "AAPL",
    "asset_type": "stock",
    "instrument_context": {"symbol": "AAPL", "exchange": "NASDAQ"},
}


def _request(**changes) -> AnalysisRequest:
    # Mirrors tests/web/test_fingerprint.py::_request exactly (ticker " aapl "
    # is normalized to AAPL in the fingerprint) so the frozen digest below is a
    # like-for-like comparison rather than a new golden value.
    base = {
        "ticker": " aapl ",
        "analysis_date": "2026-07-18",
        "selected_analysts": ("news", "market"),
        "max_debate_rounds": 2,
        "max_risk_discuss_rounds": 3,
        "horizon": "medium",
        "mode": "company_research",
        "effective_config": dict(EFFECTIVE_CONFIG),
    }
    return AnalysisRequest(**{**base, **changes})


def _build(request: AnalysisRequest, *, agent_state_schema_sha256: str | None = None):
    return _build_resume_fingerprint_for_test(
        request,
        effective_config=dict(request.effective_config),
        initial_context=dict(INITIAL_CONTEXT),
        runtime_semantics_hash="a" * 64,
        runtime_python=dict(RUNTIME_PYTHON),
        runtime_distributions=[dict(item) for item in RUNTIME_DISTRIBUTIONS],
        agent_state_schema_sha256=agent_state_schema_sha256,
    )


# ---------------------------------------------------------------------------
# 1. Reader upgrade does NOT require recomputation
# ---------------------------------------------------------------------------


def test_reader_upgrade_does_not_change_the_fingerprint_or_block_resume():
    """A reader/projection upgrade is not a writer-semantics change.

    The fingerprint deliberately excludes the reader contract: upgrading the
    reader must not invalidate a checkpoint, because the graph that produced
    the state is unchanged and re-running it would be a pure cost with no
    benefit.
    """
    stored = _build(_request())

    # Same runtime semantics (the only thing a writer change would move), a
    # different observation/projection constant standing in for the upgraded
    # reader, and a fresh build for the incoming resume.
    upgraded = _build(_request())

    assert stored.sha256 == upgraded.sha256
    assert stored.document == upgraded.document
    assert compare_resume_fingerprints(stored, upgraded).compatible is True
    # Nothing in the document tracks the reader contract.
    assert "reader" not in str(stored.document)
    assert "projection_version" not in stored.document


def test_classic_fingerprint_bytes_are_unchanged_by_the_profile_field():
    """The frozen classic digest must survive this release.

    ``profile_identity()`` returns ``{}`` for the classic default, so every
    checkpoint written before research_profile existed is still resumable and
    is not silently invalidated by a schema that only added a field.
    """
    fingerprint = _build(_request())
    request_block = fingerprint.document["request"]

    assert "research_profile" not in request_block
    assert "evidence_policy_version" not in request_block
    assert "catalyst_policy" not in request_block
    # The pre-existing frozen value for this exact request shape.
    assert fingerprint.sha256 == (
        "fc2fcd10aeccd802cf4a35102989065e711636abe1941950c2353bfda7e34c33"
    )


def test_a_classic_checkpoint_resumes_under_its_original_profile(tmp_path, monkeypatch):
    """Old checkpoint, matching fingerprint: resume proceeds, record untouched."""
    run_id = generate_run_id()
    store = RunStore(tmp_path)
    store.create_run(
        RunSnapshot.create(
            run_id=run_id,
            ticker="AAPL",
            analysis_date="2026-07-18",
            selected_analysts=("market", "news"),
            llm_provider="openai",
            quick_think_llm="gpt-4.1-mini",
            deep_think_llm="gpt-4.1",
        )
    )
    request = _request()
    fingerprint = _build(request)
    monkeypatch.setattr(
        "tradingagents.runtime.fingerprint.build_resume_fingerprint",
        lambda *_args, **_kwargs: fingerprint,
    )
    guard = FingerprintCheckpointGuard(
        store, run_id, request, request.effective_config
    )
    initial_context = PreparedInitialContext(dict(INITIAL_CONTEXT))

    fresh = guard(initial_context, type("Latest", (), {"latest": None})())
    resume = guard(initial_context, type("Latest", (), {"latest": object()})())

    assert fresh.mode == "fresh"
    assert resume.mode == "resume"
    # No LLM or provider work is implied by the authorization.
    assert resume.fingerprint_sha256 == fingerprint.sha256
    assert store.read_snapshot(run_id).resume_fingerprint["sha256"] == fingerprint.sha256


# ---------------------------------------------------------------------------
# 2. Profile and evidence policy participate in resume compatibility
# ---------------------------------------------------------------------------


def test_classic_and_catalyst_requests_never_share_a_fingerprint():
    classic = _build(_request())
    catalyst = _build(_request(research_profile="catalyst_v1"))

    assert classic.sha256 != catalyst.sha256
    comparison = compare_resume_fingerprints(classic, catalyst)
    assert comparison.compatible is False
    assert comparison.mismatch_categories == ("request",)

    request_block = catalyst.document["request"]
    assert request_block["research_profile"] == "catalyst_v1"
    assert request_block["evidence_policy_version"] == CATALYST_EVIDENCE_POLICY_VERSION
    assert request_block["catalyst_policy"]["forward_window_max_calendar_days"] == 84


def test_catalyst_evidence_policy_change_blocks_resume():
    """A different evidence window is a different graph over the same state."""
    original = _build(
        _request(
            research_profile="catalyst_v1",
            catalyst_policy=CatalystEvidencePolicyV1(),
        )
    )
    changed = _build(
        _request(
            research_profile="catalyst_v1",
            catalyst_policy=CatalystEvidencePolicyV1(max_model_calls=9),
        )
    )

    assert original.sha256 != changed.sha256
    assert compare_resume_fingerprints(original, changed).mismatch_categories == (
        "request",
    )


def test_omitted_profile_and_explicit_classic_are_the_same_fingerprint():
    """Backward compatibility: an old caller and a new caller agree byte-wise."""
    omitted = _build(_request())
    explicit = _build(_request(research_profile="classic"))

    assert omitted.sha256 == explicit.sha256
    assert compare_resume_fingerprints(omitted, explicit).compatible is True


def test_catalyst_resume_under_a_different_topology_is_refused_and_record_survives(
    tmp_path, monkeypatch
):
    """Fingerprint mismatch refuses resume and preserves the original record."""
    run_id = generate_run_id()
    store = RunStore(tmp_path)
    store.create_run(
        RunSnapshot.create(
            run_id=run_id,
            ticker="AAPL",
            analysis_date="2026-07-18",
            selected_analysts=("market", "news"),
            llm_provider="openai",
            quick_think_llm="gpt-4.1-mini",
            deep_think_llm="gpt-4.1",
        )
    )
    # The checkpoint was written under classic.
    classic_request = _request()
    monkeypatch.setattr(
        "tradingagents.runtime.fingerprint.build_resume_fingerprint",
        lambda *_args, **_kwargs: _build(classic_request),
    )
    guard = FingerprintCheckpointGuard(
        store, run_id, classic_request, classic_request.effective_config
    )
    initial_context = PreparedInitialContext(dict(INITIAL_CONTEXT))
    guard(initial_context, type("Latest", (), {"latest": None})())

    before = store.read_snapshot(run_id)

    # The same run is now resumed with a catalyst_v1 request: different topology.
    catalyst_request = _request(research_profile="catalyst_v1")
    monkeypatch.setattr(
        "tradingagents.runtime.fingerprint.build_resume_fingerprint",
        lambda *_args, **_kwargs: _build(catalyst_request),
    )
    reopened = FingerprintCheckpointGuard(
        store, run_id, catalyst_request, catalyst_request.effective_config
    )

    with pytest.raises(CheckpointIncompatible) as refused:
        reopened(initial_context, type("Latest", (), {"latest": object()})())

    assert refused.value.mismatch_categories == ("request",)
    # The original record is preserved so a new run can be created instead.
    after = store.read_snapshot(run_id)
    assert after.run_id == before.run_id
    assert after.resume_fingerprint == before.resume_fingerprint
    assert after.status == before.status


def test_agent_state_schema_change_still_blocks_resume_for_catalyst():
    """The state-schema axis and the profile axis are independent and additive."""
    baseline = _build(
        _request(research_profile="catalyst_v1"),
        agent_state_schema_sha256=AGENT_STATE_SCHEMA_SHA256,
    )
    mutated = _build(
        _request(research_profile="catalyst_v1"),
        agent_state_schema_sha256="c" * 64,
    )

    assert compare_resume_fingerprints(baseline, mutated).mismatch_categories == (
        "observation_schema",
    )


def test_fingerprint_requires_the_request_and_config_to_agree():
    """The profile travels with the config; a mismatch is not fingerprintable."""
    request = _request(research_profile="catalyst_v1")
    with pytest.raises(FingerprintError):
        _build_resume_fingerprint_for_test(
            request,
            effective_config={**EFFECTIVE_CONFIG, "llm_provider": "anthropic"},
            initial_context=dict(INITIAL_CONTEXT),
            runtime_semantics_hash="a" * 64,
        )


def test_catalyst_profile_identity_never_carries_a_horizon_policy_v3_reference():
    """A reader upgrade must not smuggle in the v3 test gate.

    ``horizon-policy-v3`` is an already-active test gate; the catalyst policy is
    a separate contract.  The two must not meet in a fingerprint.
    """
    fingerprint = _build(_request(research_profile="catalyst_v1"))
    serialized = canonical_sha256(fingerprint.document)

    assert "horizon-policy-v3" not in str(fingerprint.document)
    assert fingerprint.document["request"]["evidence_policy_version"] == (
        "catalyst-evidence-policy-v1"
    )
    assert isinstance(serialized, str) and len(serialized) == 64


def test_catalyst_fingerprint_is_deterministic_across_repeated_builds(tmp_path: Path):
    first = _build(_request(research_profile="catalyst_v1"))
    second = _build(_request(research_profile="catalyst_v1"))

    assert first.sha256 == second.sha256
    assert first.document == second.document
    assert first.sha256 == canonical_sha256(first.document)
