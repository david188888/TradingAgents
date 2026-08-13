"""Internal point-in-time evidence selection contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from tradingagents.dataflows.capability_result import (
    semantic_model_payload,
    validate_content_addressed_id,
)
from tradingagents.observability.canonical import canonical_sha256


class ArtifactClosureRefV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    artifact_id: str = Field(min_length=1, max_length=512)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: str = Field(pattern=r"^[a-z][a-z0-9_]*$")

    @model_validator(mode="after")
    def validate_ref(self) -> ArtifactClosureRefV1:
        validate_content_addressed_id(
            self.artifact_id,
            self.content_sha256,
            label="closure artifact ID",
        )
        return self


class EvidenceSelectionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    capability: str = Field(min_length=1, max_length=120)
    capability_result_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_id: str = Field(min_length=1, max_length=512)
    evidence_ref_ids: tuple[str, ...]
    coverage_ref_ids: tuple[str, ...]

    @field_validator("evidence_ref_ids", "coverage_ref_ids")
    @classmethod
    def canonical_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("snapshot selection refs must be unique")
        return tuple(sorted(values))


class PointInTimeEvidenceSnapshotV1(BaseModel):
    """Frozen canonical selections; publication sequence E lives outside it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    contract_kind: Literal["point-in-time-evidence-snapshot-v1"] = (
        "point-in-time-evidence-snapshot-v1"
    )
    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=80)
    analysis_cutoff_at: datetime
    identity_artifact_id: str = Field(min_length=1, max_length=512)
    identity_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_committed_sequence: int = Field(ge=1)
    resolved_plan_id: str = Field(min_length=1, max_length=512)
    resolved_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selections: tuple[EvidenceSelectionV1, ...]
    artifact_closure: tuple[ArtifactClosureRefV1, ...]
    missing_capabilities: tuple[str, ...]
    degraded_capabilities: tuple[str, ...]

    @field_validator("analysis_cutoff_at")
    @classmethod
    def normalize_cutoff(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("snapshot cutoff must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("missing_capabilities", "degraded_capabilities")
    @classmethod
    def canonical_capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("snapshot capability lists must be unique")
        return tuple(sorted(values))

    @field_validator("selections")
    @classmethod
    def canonical_selections(
        cls, values: tuple[EvidenceSelectionV1, ...]
    ) -> tuple[EvidenceSelectionV1, ...]:
        capabilities = [value.capability for value in values]
        if len(set(capabilities)) != len(capabilities):
            raise ValueError("snapshot selections must have unique capabilities")
        return tuple(sorted(values, key=lambda value: value.capability))

    @field_validator("artifact_closure")
    @classmethod
    def canonical_closure(
        cls, values: tuple[ArtifactClosureRefV1, ...]
    ) -> tuple[ArtifactClosureRefV1, ...]:
        artifact_ids = [value.artifact_id for value in values]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("snapshot closure artifacts must be unique")
        return tuple(sorted(values, key=lambda value: (value.role, value.artifact_id)))

    def semantic_payload(self) -> dict[str, Any]:
        return semantic_model_payload(self)

    @computed_field
    @property
    def snapshot_hash(self) -> str:
        return canonical_sha256(self.semantic_payload())

    @model_validator(mode="after")
    def validate_snapshot(self) -> PointInTimeEvidenceSnapshotV1:
        closure = {item.artifact_id: item for item in self.artifact_closure}
        identity = closure.get(self.identity_artifact_id)
        if identity is None or identity.content_sha256 != self.identity_content_hash:
            raise ValueError("snapshot identity is absent from the artifact closure")
        for selection in self.selections:
            if selection.artifact_id not in closure:
                raise ValueError("snapshot selection is absent from the artifact closure")
            validate_content_addressed_id(
                selection.artifact_id,
                closure[selection.artifact_id].content_sha256,
                label="selection artifact ID",
            )
        if set(self.missing_capabilities) & set(self.degraded_capabilities):
            raise ValueError("missing and degraded capabilities must be disjoint")
        if set(self.missing_capabilities) & {
            selection.capability for selection in self.selections
        }:
            raise ValueError("selected capabilities cannot also be missing")
        validate_content_addressed_id(
            self.identity_artifact_id,
            self.identity_content_hash,
            label="identity artifact ID",
        )
        validate_content_addressed_id(
            self.resolved_plan_id,
            self.resolved_plan_hash,
            label="resolved plan ID",
        )
        return self
