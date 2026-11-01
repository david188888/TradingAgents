"""Local-only wire-contract pin between frontend TypeScript and backend Python.

The frontend owns ``frontend/src/api/contracts.ts`` and
``frontend/src/domain/errorCategory.ts`` as its single source of truth
for the wire contract. These tests re-read those files and pin them to the
backend truth, so a backend error-category / terminal-event change
cannot drift silently on the next iteration.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FRONTEND = REPO / "frontend" / "src"


def _read(relative: str) -> str:
    return (FRONTEND / relative).read_text(encoding="utf-8")


def _extract_strings(text: str, start: str, end: str) -> set[str]:
    block = text.split(start, 1)[1].split(end, 1)[0]
    return set(re.findall(r'"([^"]+)"', block))


def test_terminal_stream_events_match_backend():
    from tradingagents.web.api import TERMINAL_STREAM_EVENTS

    ts = _read("api/contracts.ts")
    frontend = _extract_strings(
        ts,
        "TERMINAL_STREAM_EVENTS = [",
        "] as const;",
    )
    assert frontend == set(TERMINAL_STREAM_EVENTS)


def test_error_category_labels_match_manager_vocabulary():
    from tradingagents.web.manager import _error_category

    ts = _read("domain/errorCategory.ts")
    labels_block = ts.split("const ERROR_LABELS", 1)[1]
    frontend = set(re.findall(r"^\s{2}([a-z_]+):", labels_block, re.M))
    expected = {
        "provider_authentication",
        "provider_timeout",
        "vendor_rate_limit",
        "evidence_rejection",
        "checkpoint_incompatibility",
        "missing_configuration",
        "report_publication",
        "unexpected_internal_failure",
    }
    assert frontend == expected
    # The backend vocabulary must stay inside the same set: any future
    # category returned by _error_category that is not in the frontend map
    # falls back to a neutral label, so this pin keeps the two aligned.
    assert _error_category(None) in expected


# ---------------------------------------------------------------------------
# Terminal run statuses: useRunStream closes the stream once no further
# events can arrive. Backend TERMINAL_RUN_STATUSES are final forever; an
# interrupted run stays quiet until an explicit resume restarts the stream,
# so the frontend set is exactly the backend set plus "interrupted".
# ---------------------------------------------------------------------------


def test_frontend_terminal_run_statuses_cover_backend_terminal_statuses():
    from tradingagents.web.manager import TERMINAL_RUN_STATUSES

    ts = _read("hooks/useRunStream.ts")
    match = re.search(r"TERMINAL_RUN_STATUSES = new Set\(\[(.*?)\]\)", ts, re.S)
    assert match is not None
    frontend = set(re.findall(r'"([a-z]+)"', match.group(1)))
    assert frontend == set(TERMINAL_RUN_STATUSES) | {"interrupted"}
