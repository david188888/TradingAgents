"""Non-secret durable run and artifact metadata."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timezone
from typing import Any, Literal

from tradingagents.observability.events import EVENT_SCHEMA_VERSION

RUN_ID_PATTERN = re.compile(r"^run_\d{8}T\d{12}Z_[0-9a-f]{8}$")
RUN_STATUSES = frozenset(
    {
        "created",
        "queued",
        "running",
        "cancel_requested",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    }
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def generate_run_id(captured_at: datetime | None = None) -> str:
    captured = (captured_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"run_{captured.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}"


def validate_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("invalid run_id")


class UnsupportedResearchVersion(ValueError):
    """A persisted run belongs to a retired execution or storage contract."""


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    status: str
    ticker: str
    asset_type: Literal["stock"]
    analysis_date: str
    output_language: str
    llm_provider: str
    quick_think_llm: str
    deep_think_llm: str
    configured_keys: dict[str, bool]
    created_at: str
    updated_at: str
    mode: Literal["company_research"] = "company_research"
    latest_sequence: int = 0
    final_signal: str | None = None
    # Explicit canonical report locator for new completed runs.  V9 runs without this field
    # use the frontend's unique report-artifact lookup.
    final_report_artifact_id: str | None = None
    # Timestamp of the terminal run.completed event, not the report file mtime.
    completed_at: str | None = None
    # Kept structurally present for new snapshots.  P2 fills normalized source
    # degradation entries; P0 intentionally emits the empty tuple.
    degraded_data_sources: tuple[dict[str, Any], ...] = ()
    summary: str | None = None
    error_category: str | None = None
    error_message: str | None = None
    error_traceback: str | None = None
    retry_of: str | None = None
    resumed_from_sequence: int | None = None
    artifacts: tuple[str, ...] = ()
    redaction_manifest: tuple[str, ...] = ()
    event_schema_version: int = EVENT_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_run_id(self.run_id)
        if self.status not in RUN_STATUSES:
            raise ValueError(f"invalid run status: {self.status}")
        if not self.ticker.strip():
            raise ValueError("ticker is required")
        if self.latest_sequence < 0:
            raise ValueError("latest_sequence must be non-negative")
        if self.mode != "company_research" or self.asset_type != "stock":
            raise ValueError("only A-share company research is supported")
        if self.event_schema_version != EVENT_SCHEMA_VERSION:
            raise ValueError("unsupported event schema version")

    @classmethod
    def create(
        cls,
        *,
        ticker: str,
        analysis_date: str,
        asset_type: Literal["stock"] = "stock",
        output_language: str = "English",
        llm_provider: str = "",
        quick_think_llm: str = "",
        deep_think_llm: str = "",
        configured_keys: dict[str, bool] | None = None,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> RunSnapshot:
        captured = utc_timestamp()
        kwargs["metadata"] = {"research_profile": "evidence_v1", "native_workflow_version": "evidence-production-v9", **kwargs.get("metadata", {})}
        return cls(
            run_id=run_id or generate_run_id(),
            status="created",
            ticker=ticker,
            asset_type=asset_type,
            analysis_date=analysis_date,
            output_language=output_language,
            llm_provider=llm_provider,
            quick_think_llm=quick_think_llm,
            deep_think_llm=deep_think_llm,
            configured_keys=configured_keys or {},
            created_at=captured,
            updated_at=captured,
            **kwargs,
        )

    def evolve(self, **changes: Any) -> RunSnapshot:
        return replace(self, **changes)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RunSnapshot:
        metadata = value.get("metadata", {})
        if metadata.get("research_profile") != "evidence_v1" or metadata.get("native_workflow_version") != "evidence-production-v9":
            raise UnsupportedResearchVersion("unsupported research version")
        copied = {key: item for key, item in value.items() if key in {f.name for f in fields(cls)}}
        for field_name in (
            "artifacts",
            "redaction_manifest",
            "degraded_data_sources",
        ):
            copied[field_name] = tuple(copied.get(field_name, ()))
        return cls(**copied)


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    ticker: str
    analysis_date: str
    asset_type: str
    created_at: str
    updated_at: str
    latest_sequence: int
    final_signal: str | None = None
    summary: str | None = None
    error_category: str | None = None

    @classmethod
    def from_snapshot(cls, snapshot: RunSnapshot) -> RunSummary:
        return cls(
            run_id=snapshot.run_id,
            status=snapshot.status,
            ticker=snapshot.ticker,
            analysis_date=snapshot.analysis_date,
            asset_type=snapshot.asset_type,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
            latest_sequence=snapshot.latest_sequence,
            final_signal=snapshot.final_signal,
            summary=snapshot.summary,
            error_category=snapshot.error_category,
        )
