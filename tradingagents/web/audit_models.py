"""Closed DTOs for the terminal-run Audit Center APIs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AuditKind = Literal[
    "run",
    "role",
    "capability",
    "tool",
    "artifact",
    "prompt",
    "config",
    "report",
]
AuditSummaryAvailability = Literal["ready", "partial", "legacy", "unavailable"]
AuditSectionAvailability = Literal["ready", "partial", "unavailable", "not_recorded"]
AuditSummaryReason = Literal[
    "projection_failed",
    "terminal_data_incomplete",
    "legacy_event_gap",
    "not_recorded",
]
AuditDetailReason = Literal[
    "not_recorded",
    "unsupported_artifact",
    "content_too_large",
    "content_sensitive",
    "detail_not_available",
]
RedactionStatus = Literal["clean", "redacted", "metadata_only"]


class _AuditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuditSelection(_AuditModel):
    kind: AuditKind
    id: str = Field(min_length=1, max_length=512)


class AuditSectionSummary(_AuditModel):
    section_id: Literal[
        "overview",
        "roles",
        "capabilities",
        "tools",
        "artifacts",
        "prompt_config",
    ]
    availability: AuditSectionAvailability
    reason_code: AuditSummaryReason | None = None
    item_count: int = Field(ge=0)


class AuditCounts(_AuditModel):
    stages: int = Field(ge=0)
    roles: int = Field(ge=0)
    turns: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    artifacts: int = Field(ge=0)
    prompts: int = Field(ge=0)
    configs: int = Field(ge=0)
    reports: int = Field(ge=0)


class AuditRunSummary(_AuditModel):
    item_id: Literal["run"] = "run"
    status: Literal["completed", "failed", "cancelled", "interrupted"]
    ticker: str
    mode: Literal["company_research", "holding_review"] | None = None
    horizon: Literal["short", "medium", "long"] | None = None
    created_at: str
    completed_at: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    llm_provider: str
    quick_think_llm: str
    deep_think_llm: str
    data_quality: Literal["healthy", "limited", "conflicted", "unknown"]


class AuditRoleSummary(_AuditModel):
    item_id: str
    actor_id: str
    label: str
    status: str
    turn_count: int = Field(ge=0)
    model_call_count: int = Field(ge=0)
    duration_ms: int | None = Field(default=None, ge=0)


class AuditCapabilitySummary(_AuditModel):
    item_id: str
    label: str
    status: str
    reason_codes: tuple[str, ...] = ()
    affected_sections: tuple[str, ...] = ()
    capability_result_id: str | None = None
    availability: str | None = None
    freshness: str | None = None
    effective_period: str | None = None
    providers: tuple[str, ...] = ()
    fallback_from: tuple[str, ...] = ()


class AuditToolSummary(_AuditModel):
    item_id: str
    tool_name: str
    status: str
    execution_count: int = Field(ge=0)
    cache_status: str
    failure_code: str | None = None


class AuditArtifactSummary(_AuditModel):
    item_id: str
    label: str
    artifact_kind: str
    media_type: str
    byte_size: int = Field(ge=0)
    producer_stage: str | None = None
    content_exposure: Literal["safe_inline", "download_only", "prohibited"]
    is_report: bool


class AuditPromptConfigSummary(_AuditModel):
    item_id: str
    label: str
    actor_id: str | None = None
    model_call_id: str | None = None
    redaction_status: RedactionStatus
    byte_size: int = Field(ge=0)


class AuditStageSummary(_AuditModel):
    stage_id: str
    label: str
    status: Literal[
        "not_started",
        "running",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
        "unknown",
    ]
    availability: Literal["ready", "not_recorded"]
    reason_code: Literal["legacy_event_gap", "not_recorded"] | None = None
    related_selections: tuple[AuditSelection, ...] = ()


class AuditSummaryDTO(_AuditModel):
    schema_version: Literal[1] = 1
    run_id: str
    source_sequence: int = Field(ge=0)
    availability: AuditSummaryAvailability
    reason_code: AuditSummaryReason | None = None
    run: AuditRunSummary
    counts: AuditCounts
    sections: tuple[AuditSectionSummary, ...]
    stage_navigation: tuple[AuditStageSummary, ...] = ()
    roles: tuple[AuditRoleSummary, ...] = ()
    capabilities: tuple[AuditCapabilitySummary, ...] = ()
    tools: tuple[AuditToolSummary, ...] = ()
    artifacts: tuple[AuditArtifactSummary, ...] = ()
    prompts: tuple[AuditPromptConfigSummary, ...] = ()
    configs: tuple[AuditPromptConfigSummary, ...] = ()

    @model_validator(mode="after")
    def validate_sections(self) -> AuditSummaryDTO:
        expected = (
            "overview",
            "roles",
            "capabilities",
            "tools",
            "artifacts",
            "prompt_config",
        )
        actual = tuple(section.section_id for section in self.sections)
        if actual != expected:
            raise ValueError("audit sections must use the fixed v1 order")
        return self


class AuditFact(_AuditModel):
    label: str
    value: str | int | float | bool | None


class AuditContent(_AuditModel):
    mode: Literal["none", "inline", "download"]
    media_type: str | None = None
    byte_size: int | None = Field(default=None, ge=0)
    redaction_status: RedactionStatus
    text: str | None = None
    download_url: str | None = None

    @model_validator(mode="after")
    def validate_mode_fields(self) -> AuditContent:
        if self.mode == "inline" and (self.text is None or self.download_url is not None):
            raise ValueError("inline audit content requires text only")
        if self.mode == "download" and (self.download_url is None or self.text is not None):
            raise ValueError("download audit content requires download_url only")
        if self.mode == "none" and (self.text is not None or self.download_url is not None):
            raise ValueError("none audit content cannot include content or URL")
        return self


class AuditDetailDTO(_AuditModel):
    schema_version: Literal[1] = 1
    run_id: str
    source_sequence: int = Field(ge=0)
    selection: AuditSelection
    availability: Literal["ready", "unavailable"]
    reason_code: AuditDetailReason | None = None
    title: str
    facts: tuple[AuditFact, ...] = ()
    related_selections: tuple[AuditSelection, ...] = ()
    content: AuditContent

    @model_validator(mode="after")
    def validate_outcome(self) -> AuditDetailDTO:
        outcome = (self.availability, self.reason_code, self.content.mode)
        allowed = {
            ("ready", None, "none"),
            ("ready", None, "inline"),
            ("ready", "content_too_large", "download"),
            ("ready", "unsupported_artifact", "download"),
            ("unavailable", "not_recorded", "none"),
            ("unavailable", "content_sensitive", "none"),
            ("unavailable", "detail_not_available", "none"),
        }
        if outcome not in allowed:
            raise ValueError("invalid audit detail outcome")
        return self
