"""Local-only wire-contract pin between frontend TypeScript and backend Python.

The frontend owns ``frontend/src/api/contracts.ts`` and
``frontend/src/domain/{roles,errorCategory}.ts`` as its single source of truth
for the wire contract. These tests re-read those files and pin them to the
backend truth, so a backend role / error-category / terminal-event change
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


def test_event_schema_version_matches_backend():
    from tradingagents.observability.events import EVENT_SCHEMA_VERSION

    ts = _read("api/contracts.ts")
    match = re.search(r"EVENT_SCHEMA_VERSION = (\d+) as const", ts)
    assert match is not None
    assert int(match.group(1)) == EVENT_SCHEMA_VERSION


def test_stage_ids_and_actor_ids_match_role_registry():
    from tradingagents.observability.roles import ROLE_REGISTRY

    ts = _read("domain/roles.ts")
    stage_ids = set(re.findall(r'id: "(analysts|evidence|research|trading|risk|portfolio)"', ts))
    actor_blocks = re.findall(r"actor_ids: \[(.*?)\]", ts, re.S)
    actor_ids = set(re.findall(r'"([^"]+)"', "".join(actor_blocks)))
    backend_team_ids = {role.team_id for role in ROLE_REGISTRY}
    backend_actor_ids = {role.actor_id for role in ROLE_REGISTRY}
    assert stage_ids == backend_team_ids
    assert actor_ids == backend_actor_ids


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
# EventPayloadByType pin: every event type the backend can emit must appear
# in the frontend discriminated union. An unlisted type is silently dropped
# by the reducer (spec §9.5), so a new backend emit without a matching TS
# entry would vanish from the UI instead of failing loudly here.
# ---------------------------------------------------------------------------

_EVENT_NAMESPACES = frozenset(
    {
        "run", "graph", "role", "agent", "state", "report", "stats",
        "turn", "model", "input", "tool", "data", "artifact",
    }
)

# Dotted strings that match the event-type shape but are not events:
_NOT_EVENT_TYPES = {
    "data.sec.gov",  # SEC source label in research/sec_filings.py
    "run.json",  # store file locator, not an emitted type
    "tool.execution_",  # startswith() prefix literal in events.py
    # development-assertion reason strings (manager.py)
    "tool.execution_started.missing_tool_call_id",
    "tool.execution_started.unregistered_request",
}

# Union entries kept as reserved contract slots without a current producer.
# RoleInputPanel.tsx documents that input.data_snapshot has no emitter yet;
# dropping the type would break the defensive reducer branch for no gain.
_FRONTEND_RESERVED_TYPES = {
    "input.data_snapshot",
}


def _backend_emit_types() -> set[str]:
    pattern = re.compile(r'"([a-z]+)\.([a-z_.]+)"')
    found: set[str] = set()
    for path in (REPO / "tradingagents").rglob("*.py"):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            namespace, rest = match.groups()
            if namespace not in _EVENT_NAMESPACES:
                continue
            event_type = f"{namespace}.{rest}"
            if event_type not in _NOT_EVENT_TYPES:
                found.add(event_type)
    return found


def test_event_payload_union_covers_every_backend_emit_type():
    ts = _read("api/contracts.ts")
    # Members use inner semicolons (`{ type: "x"; payload: Y }`), so bound
    # the block by the next export instead of the terminating `;`.
    union_block = ts.split("export type EventPayloadByType", 1)[1].split(
        "AnyEventPayload",
        1,
    )[0]
    frontend_types = set(re.findall(r'type: "([a-z]+\.[a-z_.]+)"', union_block))

    backend = _backend_emit_types()
    missing_in_frontend = sorted(backend - frontend_types)
    stale_in_frontend = sorted(
        frontend_types - backend - _FRONTEND_RESERVED_TYPES
    )
    assert not missing_in_frontend, (
        f"backend emits event types missing from EventPayloadByType: "
        f"{missing_in_frontend}"
    )
    assert not stale_in_frontend, (
        f"EventPayloadByType lists types the backend never emits: "
        f"{stale_in_frontend}"
    )


def _interface_fields(ts: str) -> dict[str, set[str]]:
    """Map each exported interface to its field names, resolving extends."""
    fields: dict[str, set[str]] = {}
    extends: dict[str, str] = {}
    for match in re.finditer(r"export interface (\w+)(?: extends (\w+))? \{(.*?)\}", ts, re.S):
        name, parent, body = match.groups()
        fields[name] = set(re.findall(r"^\s{2}([a-z_][a-z0-9_]*)\??\s*:", body, re.M))
        if parent:
            extends[name] = parent
    for child, parent in extends.items():
        fields[child] |= fields.get(parent, set())
    return fields


def test_interrupted_and_queued_payloads_cover_backend_requirements():
    """Spot-check: the newly wired terminal/queued payloads carry every field
    the backend validator requires for those event types."""
    from tradingagents.observability.events import required_payload_fields

    ts = _read("api/contracts.ts")
    interfaces = _interface_fields(ts)
    spot_checks = {
        "run.queued": "RunQueuedPayload",
        "model.interrupted": "ModelEndedPayload",
        "tool.execution_interrupted": "ToolExecutionFailedPayload",
    }
    for event_type, iface in spot_checks.items():
        missing = required_payload_fields(event_type) - interfaces[iface]
        assert not missing, f"{event_type}: {iface} lacks {sorted(missing)}"


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


def test_api_error_codes_match_backend_vocabulary():
    """The ApiErrorCode union must carry every detail.code api.py can emit
    (via _error_response / ApiBoundaryError) plus the client-only
    http_error fallback for non-JSON failure bodies."""
    import ast

    source = (REPO / "tradingagents" / "web" / "api.py").read_text(encoding="utf-8")
    codes: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", "")
        if name not in {"_error_response", "ApiBoundaryError"}:
            continue
        arg = node.args[1] if len(node.args) >= 2 else None
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            codes.add(arg.value)
        for keyword in node.keywords:
            if keyword.arg == "code" and isinstance(keyword.value, ast.Constant):
                codes.add(keyword.value.value)

    ts = _read("api/contracts.ts")
    block = ts.split("export type ApiErrorCode", 1)[1].split(";", 1)[0]
    frontend = set(re.findall(r'"([a-z_]+)"', block))
    assert frontend == codes | {"http_error"}


def test_research_mode_horizon_and_asset_type_literals_match_models():
    """contracts.ts mirrors the AnalysisRequest Literal fields verbatim;
    widening or narrowing one side without the other fails here."""
    import typing

    from tradingagents.execution.models import AnalysisRequest

    hints = typing.get_type_hints(AnalysisRequest)
    expected = {
        "AssetTypeLiteral": set(typing.get_args(hints["asset_type"])),
        "ResearchHorizon": set(typing.get_args(hints["horizon"])),
        "ResearchMode": set(typing.get_args(hints["mode"])),
    }
    ts = _read("api/contracts.ts")
    for type_name, literals in expected.items():
        match = re.search(rf"export type {type_name} = (.*?);", ts)
        assert match is not None, type_name
        frontend = set(re.findall(r'"([a-z_]+)"', match.group(1)))
        assert frontend == literals, type_name
