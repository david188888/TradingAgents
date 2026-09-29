"""One JSON file, two loaders: pytest and Vitest read the same fixtures.

The catalyst fixtures under ``shared_fixtures/catalyst/`` are the single source
of truth for both sides of the wire.  Python loads them through
:func:`load_catalyst_fixture`; Vitest imports the same paths (see
``frontend/src/api/contracts.catalyst.test.ts``).  A field renamed on one side
and not the other therefore fails in both suites rather than only in the browser.

The files are plain JSON with no comments and no trailing commas so that
``JSON.parse`` and ``json.loads`` see byte-identical input.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALYST_FIXTURE_DIR = REPO_ROOT / "shared_fixtures" / "catalyst"

# The classes the task plan requires.  The names double as file stems.
# ``unavailable`` is split out from ``unsupported`` so the transient and the
# permanent state cannot be confused; both are asserted non-interchangeable.
FIXTURE_NAMES = (
    "catalyst_minimal_complete",
    "catalyst_partial",
    "catalyst_blocked",
    "catalyst_unavailable",
    "catalyst_unsupported",
    "catalyst_legacy_record",
)


def catalyst_fixture_path(name: str) -> Path:
    return CATALYST_FIXTURE_DIR / f"{name}.json"


def load_catalyst_fixture(name: str) -> dict[str, Any]:
    """Load one fixture. Raises KeyError for an unknown name."""
    if name not in FIXTURE_NAMES:
        raise KeyError(f"unknown catalyst fixture: {name}")
    return json.loads(catalyst_fixture_path(name).read_text(encoding="utf-8"))


def load_all_catalyst_fixtures() -> dict[str, dict[str, Any]]:
    return {name: load_catalyst_fixture(name) for name in FIXTURE_NAMES}
