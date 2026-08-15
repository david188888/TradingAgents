"""Versioned public conversation contracts for evidence-bound research Q&A.

These models deliberately describe only the portable, public surface. They do
not model prompts, tool calls, provider payloads, credentials, or private
reasoning. The durable append-only implementation lives in
:mod:`conversation_store`.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

THREAD_ID_PATTERN = re.compile(r"^thread_[A-Za-z0-9_-]{8,96}$")
ANCHOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

AnchorKind = Literal[
    "metric",
    "observation",
    "evaluation",
    "peer_set",
    "comparison",
    "edge",
    "claim",
    "evidence",
]
MessageAvailability = Literal["ready", "unknown", "unavailable", "refused"]


class ConversationAnchorV1(BaseModel):
    """A stable public reference into the persisted research package."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    kind: AnchorKind
    anchor_id: str = Field(min_length=1, max_length=128, pattern=ANCHOR_ID_PATTERN.pattern)


class ConversationMessageV1(BaseModel):
    """One public question/answer pair, retained in append-only order."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    sequence: int = Field(ge=1)
    created_at: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=16000)
    # Client-supplied public request identity makes HTTP retries idempotent.
    request_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=ANCHOR_ID_PATTERN.pattern)
    availability: MessageAvailability = "ready"
    refusal_reason: str | None = Field(default=None, max_length=500)
    anchors: tuple[ConversationAnchorV1, ...] = ()
    evidence_ref_ids: tuple[str, ...] = Field(default=(), max_length=64)
    next_validation: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def validate_public_status(self) -> ConversationMessageV1:
        if self.availability == "ready" and self.refusal_reason is not None:
            raise ValueError("ready messages must not carry a refusal_reason")
        if self.availability in {"unknown", "unavailable", "refused"} and not self.refusal_reason:
            raise ValueError("non-ready messages require a refusal_reason")
        if any(
            not isinstance(ref_id, str)
            or not ANCHOR_ID_PATTERN.fullmatch(ref_id)
            for ref_id in self.evidence_ref_ids
        ):
            raise ValueError("evidence_ref_ids must contain stable public ids")
        return self


class ConversationThreadV1(BaseModel):
    """A complete public conversation projection for one run and package hash."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["conversation-thread-v1"] = "conversation-thread-v1"
    thread_id: str = Field(min_length=1, max_length=104, pattern=THREAD_ID_PATTERN.pattern)
    run_id: str = Field(min_length=1, max_length=128)
    package_schema_version: str = Field(min_length=1, max_length=64)
    package_sha256: str = Field(pattern=SHA256_PATTERN.pattern)
    # Optional for legacy threads created before the HTTP API bound entity metadata.
    ticker: str | None = Field(default=None, min_length=1, max_length=32)
    target_entity_id: str | None = Field(default=None, min_length=1, max_length=120)
    created_at: str = Field(min_length=1, max_length=64)
    updated_at: str = Field(min_length=1, max_length=64)
    messages: tuple[ConversationMessageV1, ...] = ()

    @model_validator(mode="after")
    def validate_sequences(self) -> ConversationThreadV1:
        expected = tuple(range(1, len(self.messages) + 1))
        actual = tuple(message.sequence for message in self.messages)
        if actual != expected:
            raise ValueError("conversation message sequences must be contiguous")
        return self


__all__ = [
    "ANCHOR_ID_PATTERN",
    "ConversationAnchorV1",
    "ConversationMessageV1",
    "ConversationThreadV1",
    "MessageAvailability",
    "THREAD_ID_PATTERN",
]
