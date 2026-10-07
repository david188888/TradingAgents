"""Closed read-only process and per-role research output contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.agents.schemas._native_stage import (
    ChallengesProposalV1,
    ChallengesProposalV2,
    SpecialistProposalV1,
    SynthesisProposalV1,
    SynthesisProposalV2,
)

AgentKey = Literal[
    "evidence",
    "operating_quality",
    "event_context",
    "market_context",
    "challenge",
    "synthesis",
    "code_checks",
]
OutputAvailability = Literal[
    "available",
    "pending_publication",
    "not_recorded",
    "unavailable",
    "unsupported",
    "not_applicable",
]


class _ReaderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ObservedCount(_ReaderModel):
    value: int | None = Field(default=None, ge=0)
    completeness: Literal["complete", "known_lower_bound", "not_recorded", "unavailable"]
    basis: str


class NativeCounts(_ReaderModel):
    main_budget: ObservedCount
    repair_budget: ObservedCount
    sdk_main: ObservedCount
    sdk_repair: ObservedCount
    sdk_total: ObservedCount
    data_capability: ObservedCount
    data_http: ObservedCount


class ClaimOrigin(_ReaderModel):
    claim_id: str
    role_key: AgentKey


class ReaderRole(_ReaderModel):
    role_key: AgentKey
    actor_id: str
    label: str
    origin: Literal["model", "code"]
    purpose: str
    status: str
    output_availability: OutputAvailability
    reason_code: str | None = None
    output_count: int | None = Field(default=None, ge=0)
    output_sequence: int | None = Field(default=None, ge=0)
    main_budget: ObservedCount
    sdk_main: ObservedCount
    sdk_repair: ObservedCount


class ReaderProcessDTO(_ReaderModel):
    schema_version: Literal[1] = 1
    run_id: str
    source_sequence: int = Field(ge=0)
    profile: str
    workflow_version: str | None = None
    availability: Literal["ready", "partial", "unavailable", "not_applicable"]
    reason_code: str | None = None
    question_origin: Literal["user", "default", "not_recorded"] = "not_recorded"
    primary_selection: Literal["synthesis", "code", "not_recorded"] = "not_recorded"
    counts: NativeCounts
    roles: tuple[ReaderRole, ...] = ()
    claim_origins: tuple[ClaimOrigin, ...] = ()
    source_failures: tuple[str, ...] = ()


class OutputRelation(_ReaderModel):
    entity_id: str
    kind: Literal["claim", "challenge"]
    in_record: bool
    is_key: bool
    dimensions: tuple[str, ...] = ()
    challenge_ids: tuple[str, ...] = ()


class ReaderAgentDTO(_ReaderModel):
    schema_version: Literal[1] = 1
    run_id: str
    source_sequence: int = Field(ge=0)
    role_key: AgentKey
    availability: OutputAvailability
    reason_code: str | None = None
    origin: Literal["model", "code"]
    input_description: str
    # Closed schema fields only: never an adapter, prompt, response or checkpoint.
    proposal: (
        SpecialistProposalV1
        | ChallengesProposalV2
        | ChallengesProposalV1
        | SynthesisProposalV2
        | SynthesisProposalV1
        | None
    ) = None
    relations: tuple[OutputRelation, ...] = ()
    claim_ids: tuple[str, ...] = ()
    input_fact_ids: tuple[str, ...] = ()
    challenge_ids: tuple[str, ...] = ()
    code_sections: tuple[
        Literal["facts", "sources", "checks", "verifications", "publication"], ...
    ] = ()
