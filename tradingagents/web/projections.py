"""Pagination over current run summaries."""
import base64
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from tradingagents.runtime.run_models import RunSummary, validate_run_id

SCHEMA_VERSION = 1
RECENT_ELIGIBLE_STATUSES = {"created", "queued", "running", "cancel_requested", "completed", "failed", "cancelled", "interrupted"}
class InvalidCursor(ValueError):
    pass

def recent_runs_page(
    summaries: Iterable[RunSummary],
    *,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise ValueError("invalid_limit")
    eligible = [summary for summary in summaries if summary.status in RECENT_ELIGIBLE_STATUSES]
    eligible.sort(key=lambda item: (item.created_at, item.run_id), reverse=True)
    if cursor:
        marker = _decode_cursor(cursor)
        eligible = [
            item
            for item in eligible
            if (item.created_at, item.run_id) < (marker["created_at"], marker["run_id"])
        ]
    selected = eligible[:limit]
    next_cursor = None
    if len(eligible) > len(selected) and selected:
        tail = selected[-1]
        next_cursor = _encode_cursor(tail.created_at, tail.run_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "items": [
            {
                "run_id": item.run_id,
                "ticker": item.ticker,
                "status": item.status,
                "created_at": item.created_at,
                "completed_at": None,
                "latest_sequence": item.latest_sequence,
                "final_signal": item.final_signal,
                "error_category": item.error_category,
                "duration_ms": None,
                "data_quality_level": "unknown",
            }
            for item in selected
        ],
        "next_cursor": next_cursor,
    }


def _encode_cursor(created_at: str, run_id: str) -> str:
    payload = f"v1|recent|{created_at}|{run_id}".encode()
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> dict[str, str]:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")
        version, view, created_at, run_id = decoded.split("|", 3)
        if version != "v1" or view != "recent":
            raise ValueError
        validate_run_id(run_id)
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception as exc:
        raise InvalidCursor("invalid_cursor") from exc
    return {"created_at": created_at, "run_id": run_id}
