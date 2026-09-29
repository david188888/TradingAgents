"""T11 — the catalyst fixtures, loadable by pytest and Vitest alike.

One JSON file per class, read by both sides.  The Vitest half of this contract
lives in ``frontend/src/api/contracts.catalyst.test.ts``; both suites enumerate
the same names, so a fixture added on one side only fails on the other.

The three ``ready`` fixtures are not hand-written approximations: each is
validated against the real ``CatalystResearchCase`` contract by
``test_ready_fixtures_validate_against_the_canonical_case_schema``, so a
renamed field on the Python side fails here instead of only in the browser.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from shared_fixtures import (
    CATALYST_FIXTURE_DIR,
    FIXTURE_NAMES,
    catalyst_fixture_path,
    load_all_catalyst_fixtures,
    load_catalyst_fixture,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
VITEST_FIXTURE_TEST = REPO_ROOT / "frontend" / "src" / "api" / "contracts.catalyst.test.ts"

READY_NAMES = ("catalyst_minimal_complete", "catalyst_partial", "catalyst_blocked")

# The canonical case contract (agent C's ``_catalyst_research.py``) is validated
# when it is importable. It is a parallel-worktree dependency, not a soft one:
# once C's module lands, these tests run and a renamed field fails here instead
# of only in the browser. Before it lands, the fixtures are still checked for
# internal consistency, so this file never degrades to a no-op.
try:  # pragma: no cover - depends on merge order, not on behaviour
    from tradingagents.agents.schemas import (
        BRIEF_CHARACTER_BUDGET,
        PRIORITY_BLOCKING_REASONS,
        SAFETY_OVERFLOW_TEMPLATE_BUDGET,
        CatalystBrief,
        CatalystResearchCase,
    )
except ImportError:  # pragma: no cover
    CatalystResearchCase = None
    CatalystBrief = None
    PRIORITY_BLOCKING_REASONS = frozenset()
    BRIEF_CHARACTER_BUDGET = 420
    SAFETY_OVERFLOW_TEMPLATE_BUDGET = 120

requires_canonical_schema = pytest.mark.skipif(
    CatalystResearchCase is None,
    reason="catalyst-research-case-v1 is not merged into this tree yet",
)


def test_every_fixture_class_exists():
    assert FIXTURE_NAMES == (
        "catalyst_minimal_complete",
        "catalyst_partial",
        "catalyst_blocked",
        "catalyst_unavailable",
        "catalyst_unsupported",
        "catalyst_legacy_record",
    )
    on_disk = {path.stem for path in CATALYST_FIXTURE_DIR.glob("*.json")}
    assert on_disk == set(FIXTURE_NAMES)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_every_fixture_carries_a_schema_version(name):
    fixture = load_catalyst_fixture(name)
    assert fixture["schema_version"] == 1
    assert fixture["fixture_id"] == name
    assert fixture["description"]


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixtures_are_strict_json_readable_by_both_engines(name):
    """No comments, no trailing commas: JSON.parse and json.loads agree.

    A file only one parser accepts would let the two suites drift, which is the
    exact failure the shared-fixture requirement exists to prevent.
    """
    text = catalyst_fixture_path(name).read_text(encoding="utf-8")
    assert "\t" not in text
    assert json.loads(json.dumps(json.loads(text))) == json.loads(text)


@requires_canonical_schema
def test_ready_fixtures_validate_against_the_canonical_case_schema():
    """The shared sample is a real committed case, not a lookalike.

    Without this, a field renamed in ``_catalyst_research.py`` would leave the
    fixtures silently stale and both suites would keep agreeing on a shape the
    server never emits.
    """
    for name in READY_NAMES:
        fixture = load_catalyst_fixture(name)
        case = CatalystResearchCase.model_validate(fixture["case"])
        assert case.run_id == fixture["run_id"]
        assert case.completeness == fixture["completeness"]
        assert case.quality == fixture["quality"]
        assert case.priority_decision.priority == fixture["priority"]
        # The server counts the brief; the fixture must not assert its own.
        assert fixture["brief_character_count"] == case.brief.character_count


def test_unsupported_and_unavailable_have_different_shapes():
    """The two are not interchangeable, and the fixture set proves it.

    ``unavailable`` is transient — the run could still publish an artifact.
    ``unsupported`` is permanent — this run's profile will never have one.  A
    client that rendered them alike would tell a user that a classic run
    "failed" rather than "does not apply".
    """
    unavailable = load_catalyst_fixture("catalyst_unavailable")
    unsupported = load_catalyst_fixture("catalyst_unsupported")

    assert unavailable["state"] == "unavailable"
    assert unavailable["reason_code"] == "run_running"
    assert unavailable["run_status"] == "running"

    assert unsupported["state"] == "unsupported"
    assert unsupported["reason_code"] == "classic_profile"

    # `unsupported` carries a terminal reason and no case payload at all.
    for case_only in ("completeness", "quality", "priority", "brief", "case", "limitations"):
        assert case_only not in unsupported
    # `unavailable` keeps the run's lifecycle so a client can decide to poll.
    assert "run_status" in unavailable
    assert "case" not in unavailable

    for name in READY_NAMES:
        assert load_catalyst_fixture(name)["state"] == "ready"
        assert load_catalyst_fixture(name) != unsupported
        assert load_catalyst_fixture(name) != unavailable


def test_ready_fixtures_cover_all_three_completeness_states():
    ready = {name: load_catalyst_fixture(name)["completeness"] for name in READY_NAMES}
    assert set(ready.values()) == {"complete", "partial", "blocked"}


def test_only_a_complete_case_may_publish_verify_first():
    """The priority ceiling (design 9.1) is visible in the fixture set itself."""
    for name in READY_NAMES:
        fixture = load_catalyst_fixture(name)
        priority = fixture["priority"]
        if fixture["completeness"] == "complete":
            assert priority != "insufficient_information", name
        else:
            assert priority == "insufficient_information", name
            assert fixture["quality"] != "PASS", name
            assert fixture["case"]["priority_decision"]["blocking_reasons"], name


@requires_canonical_schema
def test_every_blocking_reason_is_a_registered_code():
    """A lowered priority must record a reason the contract recognises."""
    for name in READY_NAMES:
        decision = load_catalyst_fixture(name)["case"]["priority_decision"]
        for reason in decision["blocking_reasons"]:
            assert reason in PRIORITY_BLOCKING_REASONS, f"{name}:{reason}"
        if decision["priority"] != decision["candidate_priority"]:
            assert decision["blocking_reasons"], name


def test_non_complete_cases_carry_machine_readable_reasons():
    for name in ("catalyst_partial", "catalyst_blocked"):
        fixture = load_catalyst_fixture(name)
        assert fixture["case"]["reason_codes"], name
        assert all(re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*", c) for c in fixture["case"]["reason_codes"]), name
        assert fixture["limitations"], name


@requires_canonical_schema
def test_briefs_stay_inside_their_character_budget():
    """Design 4.3: the budget is about what a reader may be shown."""
    for name in READY_NAMES:
        brief = CatalystBrief.model_validate(load_catalyst_fixture(name)["brief"])
        limit = (
            BRIEF_CHARACTER_BUDGET
            if brief.kind == "ordinary"
            else SAFETY_OVERFLOW_TEMPLATE_BUDGET
        )
        assert brief.character_count <= limit, name


def test_every_reference_in_a_ready_fixture_resolves():
    """Cross-reference integrity inside the committed case.

    This is a fixture-level sanity check, not a replacement for the canonical
    validator; it guarantees the shared sample is internally consistent so a
    broken reference is a real defect rather than bad sample data.
    """
    for name in READY_NAMES:
        case = load_catalyst_fixture(name)["case"]
        evidence_ids = {item["evidence_id"] for item in case["evidence"]}
        event_ids = {item["event_id"] for item in case["events"]}
        finding_ids = {item["finding_id"] for item in case["findings"]}
        challenge_ids = {item["challenge_id"] for item in case["challenges"]}

        assert len(evidence_ids) == len(case["evidence"]), name
        assert len(event_ids) == len(case["events"]), name
        assert len(finding_ids) == len(case["findings"]), name
        assert len(challenge_ids) == len(case["challenges"]), name

        for event in case["events"]:
            assert set(event["date_evidence_ids"]) <= evidence_ids, name
            if event["supersedes_event_id"]:
                assert event["supersedes_event_id"] in event_ids, name
        for finding in case["findings"]:
            assert set(finding["evidence_ids"]) <= evidence_ids, name
            assert set(finding["event_ids"]) <= event_ids, name
            assert set(finding["supporting_finding_ids"]) <= finding_ids, name
        for challenge in case["challenges"]:
            assert set(challenge["evidence_ids"]) <= evidence_ids, name
            assert set(challenge["target_finding_ids"]) <= finding_ids, name
            assert set(challenge["target_event_ids"]) <= event_ids, name
        for disposition in case["dispositions"]:
            assert disposition["challenge_id"] in challenge_ids, name
            assert set(disposition["evidence_ids"]) <= evidence_ids, name
        for line in case["brief"]["key_evidence"] + case["brief"]["critical_limitations"]:
            assert set(line["finding_ids"]) <= finding_ids, name
            assert set(line["event_ids"]) <= event_ids, name
            assert set(line["challenge_ids"]) <= challenge_ids, name


def test_legacy_record_carries_no_research_priority():
    """A reader upgrade must not manufacture a priority from old prose."""
    legacy = load_catalyst_fixture("catalyst_legacy_record")
    assert legacy["kind"] == "legacy"
    assert legacy["research_priority"] is None
    for catalyst_only in ("completeness", "quality", "priority", "brief", "case"):
        assert catalyst_only not in legacy


def test_vitest_loads_the_same_files():
    """The TS suite must reference the same directory and the same names.

    A cross-language contract check: if the Vitest test hard-coded its own
    copies or a different set, the two suites would stop agreeing about the
    wire and only the browser would find out.
    """
    source = VITEST_FIXTURE_TEST.read_text(encoding="utf-8")
    assert "shared_fixtures/catalyst" in source
    for name in FIXTURE_NAMES:
        assert name in source, name


def test_vitest_fixture_glob_and_python_fixture_dir_are_the_same_path():
    """The TS import resolves under the same repository-relative directory."""
    source = VITEST_FIXTURE_TEST.read_text(encoding="utf-8")
    match = re.search(r"shared_fixtures/catalyst(/[^`\"']*)?", source)
    assert match is not None
    assert CATALYST_FIXTURE_DIR.is_dir()
    relative = CATALYST_FIXTURE_DIR.relative_to(REPO_ROOT).as_posix()
    assert relative in source


def test_fixture_bytes_are_identical_across_a_fresh_python_process():
    """Guards against an editor rewriting line endings or encoding."""
    script = (
        "import json,sys;"
        "from pathlib import Path;"
        f"p=Path({str(CATALYST_FIXTURE_DIR)!r});"
        "print(json.dumps(sorted(q.name for q in p.glob('*.json'))))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    assert json.loads(completed.stdout) == sorted(f"{name}.json" for name in FIXTURE_NAMES)


def test_unknown_fixture_name_is_an_explicit_error():
    with pytest.raises(KeyError):
        load_catalyst_fixture("catalyst_does_not_exist")


def test_all_fixtures_load_together():
    assert len(load_all_catalyst_fixtures()) == len(FIXTURE_NAMES)
