"""Pure SEC filing index and document evidence contracts."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from tradingagents.dataflows.capability_result import (
    semantic_model_payload,
    validate_content_addressed_id,
)
from tradingagents.observability.canonical import canonical_sha256

SecForm = Literal["10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A"]
_DOCUMENT_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A"})


class SecSourceArtifactRefV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    role: Literal[
        "submissions_current",
        "submissions_history",
        "primary_document_raw",
        "primary_document_text",
    ]
    artifact_id: str = Field(min_length=1, max_length=512)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_url: str | None = Field(default=None, max_length=2048)
    logical_name: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_ref(self) -> SecSourceArtifactRefV1:
        validate_content_addressed_id(self.artifact_id, self.content_sha256)
        if self.role == "submissions_history":
            if self.logical_name is None:
                raise ValueError("history artifacts require a logical name")
        elif self.logical_name is not None:
            raise ValueError("only history artifacts may carry a logical name")
        if self.source_url is not None:
            parsed = urlsplit(self.source_url)
            if parsed.scheme != "https" or parsed.hostname not in {
                "www.sec.gov",
                "data.sec.gov",
            }:
                raise ValueError("SEC source URLs must use an official HTTPS host")
        return self


class SecFilingDocumentV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    accession: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    form: Literal["10-K", "10-K/A", "10-Q", "10-Q/A"]
    accepted_at: datetime
    raw_artifact_ref: SecSourceArtifactRefV1 | None = None
    normalized_text_artifact_ref: SecSourceArtifactRefV1 | None = None
    parser_status: Literal[
        "complete",
        "normalized_text_unavailable",
        "parser_timeout",
        "invalid_content_type",
        "oversize",
    ]

    @field_validator("accepted_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("SEC accepted_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    def semantic_payload(self) -> dict[str, Any]:
        return semantic_model_payload(self)

    @computed_field
    @property
    def content_hash(self) -> str:
        return canonical_sha256(self.semantic_payload())

    @model_validator(mode="after")
    def validate_document(self) -> SecFilingDocumentV1:
        if self.parser_status in {
            "complete",
            "normalized_text_unavailable",
            "parser_timeout",
        } and self.raw_artifact_ref is None:
            raise ValueError("downloaded filing documents require a raw ref")
        if self.parser_status == "complete":
            if self.normalized_text_artifact_ref is None:
                raise ValueError("complete filing documents require raw and normalized refs")
        elif self.normalized_text_artifact_ref is not None:
            raise ValueError("incomplete parsing cannot claim normalized text")
        if self.raw_artifact_ref is not None and self.raw_artifact_ref.role != "primary_document_raw":
            raise ValueError("raw document ref has the wrong role")
        if (
            self.normalized_text_artifact_ref is not None
            and self.normalized_text_artifact_ref.role != "primary_document_text"
        ):
            raise ValueError("normalized document ref has the wrong role")
        return self


class SecFilingRecordV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    form: SecForm
    accession: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    filing_date: str
    accepted_at: datetime
    report_date: str | None = None
    primary_document: str = Field(min_length=1, max_length=512)
    sec_urls: tuple[str, ...] = Field(min_length=1)
    source_artifact_ref: SecSourceArtifactRefV1
    document: SecFilingDocumentV1 | None = None

    @field_validator("filing_date", "report_date")
    @classmethod
    def validate_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("SEC dates must use YYYY-MM-DD")
        return value

    @field_validator("accepted_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("SEC accepted_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("sec_urls")
    @classmethod
    def validate_urls(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("SEC URLs must be unique")
        for value in values:
            parsed = urlsplit(value)
            if parsed.scheme != "https" or parsed.hostname not in {
                "www.sec.gov",
                "data.sec.gov",
            }:
                raise ValueError("filing URLs must use an official SEC HTTPS host")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_record(self) -> SecFilingRecordV1:
        if self.source_artifact_ref.role not in {
            "submissions_current",
            "submissions_history",
        }:
            raise ValueError("filing source must be a submissions artifact")
        if self.document is not None and (
            self.document.accession != self.accession
            or self.document.form != self.form
            or self.document.accepted_at != self.accepted_at
        ):
            raise ValueError("filing document identity does not match its index record")
        if self.form in {"8-K", "8-K/A"} and self.document is not None:
            raise ValueError("8-K filings are metadata-only in this contract version")
        return self


class SecFilingIndexCoverageV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    index_search_complete: bool
    observed_index_count: int = Field(ge=0)
    target_filing_count: int = Field(ge=0)
    rejected_target_count: int = Field(ge=0)
    required_document_count: int = Field(ge=0)
    completed_document_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> SecFilingIndexCoverageV1:
        if self.rejected_target_count > self.target_filing_count:
            raise ValueError("rejected targets cannot exceed target filings")
        if self.target_filing_count > self.observed_index_count:
            raise ValueError("target filings cannot exceed observed index rows")
        if self.completed_document_count > self.required_document_count:
            raise ValueError("completed documents cannot exceed required documents")
        return self


class SecFilingIndexV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    contract_kind: Literal["sec-filing-index-v1"] = "sec-filing-index-v1"
    ticker: str = Field(min_length=1, max_length=80)
    cik: str = Field(pattern=r"^[0-9]{10}$")
    company_name: str = Field(min_length=1, max_length=500)
    analysis_cutoff_at: datetime
    requested_start: str
    requested_end: str
    fetched_history_files: tuple[str, ...]
    pagination_exhausted: bool
    source_artifacts: tuple[SecSourceArtifactRefV1, ...] = Field(min_length=1)
    coverage: SecFilingIndexCoverageV1
    filings: tuple[SecFilingRecordV1, ...]

    @field_validator("analysis_cutoff_at")
    @classmethod
    def normalize_cutoff(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("SEC cutoff must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("requested_start", "requested_end")
    @classmethod
    def validate_date(cls, value: str) -> str:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("requested dates must use YYYY-MM-DD")
        return value

    @field_validator("fetched_history_files")
    @classmethod
    def canonical_history_files(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("history file names must be unique")
        return tuple(sorted(values))

    @field_validator("source_artifacts")
    @classmethod
    def canonical_source_artifacts(
        cls, values: tuple[SecSourceArtifactRefV1, ...]
    ) -> tuple[SecSourceArtifactRefV1, ...]:
        artifact_ids = [ref.artifact_id for ref in values]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("source artifacts must be unique")
        return tuple(sorted(values, key=lambda ref: ref.artifact_id))

    @field_validator("filings")
    @classmethod
    def canonical_filings(
        cls, values: tuple[SecFilingRecordV1, ...]
    ) -> tuple[SecFilingRecordV1, ...]:
        accessions = [filing.accession for filing in values]
        if len(set(accessions)) != len(accessions):
            raise ValueError("SEC filing accessions must be unique")
        return tuple(sorted(values, key=lambda filing: filing.accession))

    def semantic_payload(self) -> dict[str, Any]:
        return semantic_model_payload(self)

    @computed_field
    @property
    def content_hash(self) -> str:
        return canonical_sha256(self.semantic_payload())

    @model_validator(mode="after")
    def validate_index(self) -> SecFilingIndexV1:
        if self.requested_start > self.requested_end:
            raise ValueError("requested_start cannot be after requested_end")
        if self.pagination_exhausted != self.coverage.index_search_complete:
            raise ValueError("pagination status must match index coverage")
        declared_by_id = {ref.artifact_id: ref for ref in self.source_artifacts}
        if not any(ref.role == "submissions_current" for ref in self.source_artifacts):
            raise ValueError("SEC index requires the current submissions artifact")
        history_names = tuple(
            sorted(
                ref.logical_name
                for ref in self.source_artifacts
                if ref.role == "submissions_history" and ref.logical_name is not None
            )
        )
        if history_names != self.fetched_history_files:
            raise ValueError("fetched history files must match history artifacts")

        for filing in self.filings:
            if filing.accepted_at > self.analysis_cutoff_at:
                raise ValueError("filing accepted_at cannot exceed cutoff")
            refs = [filing.source_artifact_ref]
            if filing.document is not None:
                refs.extend(
                    ref
                    for ref in (
                        filing.document.raw_artifact_ref,
                        filing.document.normalized_text_artifact_ref,
                    )
                    if ref is not None
                )
            if any(declared_by_id.get(ref.artifact_id) != ref for ref in refs):
                raise ValueError("filing references must exactly match the index closure")

        expected_required = sum(filing.form in _DOCUMENT_FORMS for filing in self.filings)
        expected_completed = sum(
            filing.form in _DOCUMENT_FORMS
            and filing.document is not None
            and filing.document.parser_status == "complete"
            for filing in self.filings
        )
        if self.coverage.required_document_count != expected_required:
            raise ValueError("required document count does not match retained filings")
        if self.coverage.completed_document_count != expected_completed:
            raise ValueError("completed document count does not match retained filings")
        if (
            self.coverage.target_filing_count
            != len(self.filings) + self.coverage.rejected_target_count
        ):
            raise ValueError("target filing count does not match retained and rejected filings")
        return self
