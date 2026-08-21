"""Durable metadata for Web batch analysis scheduling."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

BATCH_ID_PATTERN = re.compile(r"^batch_\d{8}T\d{12}Z_[0-9a-f]{8}$")
BATCH_STATUSES = frozenset({"queued", "running", "completed", "partial", "failed", "cancelled"})
BATCH_ITEM_STATUSES = frozenset({"queued", "running", "completed", "failed", "cancelled", "interrupted"})


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def generate_batch_id(captured_at: datetime | None = None) -> str:
    captured = (captured_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"batch_{captured.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}"


def validate_batch_id(batch_id: str) -> None:
    if not BATCH_ID_PATTERN.fullmatch(batch_id):
        raise ValueError("invalid batch_id")


@dataclass(frozen=True)
class BatchItem:
    input_value: str
    company_name: str
    ticker: str
    market: str
    run_id: str
    ordinal: int
    status: str = "queued"
    error_message: str | None = None
    config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.input_value.strip() or not self.company_name.strip() or not self.ticker.strip():
            raise ValueError("batch item identity is required")
        if self.status not in BATCH_ITEM_STATUSES:
            raise ValueError(f"invalid batch item status: {self.status}")
        if self.ordinal < 0:
            raise ValueError("batch item ordinal must be non-negative")


@dataclass(frozen=True)
class BatchSnapshot:
    batch_id: str
    status: str
    created_at: str
    updated_at: str
    concurrency: int
    items: tuple[BatchItem, ...]
    completed_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    running_count: int = 0
    queued_count: int = 0
    interrupted_count: int = 0
    summary: str | None = None

    def __post_init__(self) -> None:
        validate_batch_id(self.batch_id)
        if self.status not in BATCH_STATUSES:
            raise ValueError(f"invalid batch status: {self.status}")
        if self.concurrency not in (1, 2, 3):
            raise ValueError("batch concurrency must be between 1 and 3")
        if not 1 <= len(self.items) <= 8:
            raise ValueError("batch must contain between 1 and 8 items")

    @classmethod
    def create(cls, *, items: tuple[BatchItem, ...], concurrency: int = 3) -> BatchSnapshot:
        captured = utc_timestamp()
        return cls(
            batch_id=generate_batch_id(),
            status="queued",
            created_at=captured,
            updated_at=captured,
            concurrency=concurrency,
            items=items,
            queued_count=len(items),
        )

    def evolve(self, **changes: Any) -> BatchSnapshot:
        return replace(self, **changes, updated_at=utc_timestamp())

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BatchSnapshot:
        copied = dict(value)
        copied["items"] = tuple(
            item if isinstance(item, BatchItem) else BatchItem(**item)
            for item in copied.get("items", ())
        )
        return cls(**copied)

    def with_item_status(
        self,
        run_id: str,
        status: str,
        *,
        error_message: str | None = None,
    ) -> BatchSnapshot:
        items = tuple(
            replace(item, status=status, error_message=error_message)
            if item.run_id == run_id
            else item
            for item in self.items
        )
        counts = {key: 0 for key in ("completed", "failed", "cancelled", "running", "queued", "interrupted")}
        for item in items:
            counts[item.status] += 1
        if counts["completed"] == len(items):
            batch_status = "completed"
        elif counts["completed"] + counts["failed"] + counts["cancelled"] + counts["interrupted"] < len(items):
            batch_status = "running" if counts["running"] else "queued"
        elif counts["completed"] and counts["failed"] == 0 and counts["cancelled"] == 0 and counts["interrupted"] == 0:
            batch_status = "completed"
        elif counts["completed"]:
            batch_status = "partial"
        elif counts["failed"]:
            batch_status = "failed"
        else:
            batch_status = "cancelled"
        return self.evolve(
            status=batch_status,
            items=items,
            completed_count=counts["completed"],
            failed_count=counts["failed"],
            cancelled_count=counts["cancelled"],
            running_count=counts["running"],
            queued_count=counts["queued"],
            interrupted_count=counts["interrupted"],
            summary=(
                f"{counts['completed']}/{len(items)} companies completed, "
                f"{counts['failed']} failed, {counts['cancelled']} cancelled."
            )
            if batch_status in {"completed", "partial", "failed", "cancelled"}
            else None,
        )
