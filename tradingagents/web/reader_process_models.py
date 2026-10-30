"""Closed read-only process and per-role research output contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from tradingagents.agents.schemas._challenge_review import HypothesisReviewV1
from tradingagents.agents.schemas._factual_premise import PublicPremiseV1
from tradingagents.agents.schemas._insight import InsightReport
from tradingagents.agents.schemas._native_stage import (
    ChallengesProposalV1,
    ChallengesProposalV2,
    ChallengesProposalV3,
    SpecialistProposalV1,
    SynthesisProposalV1,
    SynthesisProposalV2,
    SynthesisProposalV3,
)
from tradingagents.agents.schemas._research_dialogue import ResponsesProposalV1
from tradingagents.agents.schemas._research_focus import FocusProposalV1
from tradingagents.llm_clients.chatgpt_errors import ModelFailureDiagnostic
from tradingagents.research.record_codec import ResearchRecord

AgentKey = Literal[
    "evidence",
    "operating_quality",
    "event_context",
    "market_context",
    "challenge",
    "synthesis",
    "response_operating_quality", "response_event_context", "response_market_context",
    "code_checks",
    "focus_response",
]
OutputAvailability = Literal[
    "available",
    "stage_available",
    "insight_stage_available",
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
    focus_budget: ObservedCount | None = None
    sdk_focus: ObservedCount | None = None


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
    focus_budget: ObservedCount | None = None
    sdk_focus: ObservedCount | None = None


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
    model_failures: tuple[ModelFailureDiagnostic, ...] = ()
    search_usage: 'SearchUsageV1 | None' = None

    @model_serializer(mode='wrap')
    def preserve_old_process_shape(self, handler):
        value = handler(self)
        if self.search_usage is None:
            value.pop('search_usage', None)
        return value


class OutputRelation(_ReaderModel):
    entity_id: str
    kind: Literal["claim", "challenge"]
    in_record: bool
    is_key: bool
    dimensions: tuple[str, ...] = ()
    challenge_ids: tuple[str, ...] = ()




class ReaderAgentDTO(_ReaderModel):
    insight_record: InsightReport | None = None
    challenge_reviews: tuple[HypothesisReviewV1, ...] = ()
    factual_premises: tuple[PublicPremiseV1, ...] = ()
    schema_version: Literal[1] = 1
    run_id: str
    source_sequence: int = Field(ge=0)
    role_key: AgentKey
    availability: OutputAvailability
    reason_code: str | None = None
    origin: Literal["model", "code"]
    input_description: str
    # Independently qualified public stage material, never a final assessment.
    stage_record: ResearchRecord | None = None
    # Closed schema fields only: never an adapter, prompt, response or checkpoint.
    proposal: (
        SpecialistProposalV1
        | ChallengesProposalV3
        | ChallengesProposalV2
        | ChallengesProposalV1
        | SynthesisProposalV3
        | ResponsesProposalV1
        | SynthesisProposalV2
        | SynthesisProposalV1
        | FocusProposalV1
        | None
    ) = None
    relations: tuple[OutputRelation, ...] = ()
    claim_ids: tuple[str, ...] = ()
    input_fact_ids: tuple[str, ...] = ()
    challenge_ids: tuple[str, ...] = ()
    code_sections: tuple[
        Literal["facts", "sources", "checks", "verifications", "publication"], ...
    ] = ()

    @model_validator(mode="after")
    def stage_is_not_a_final_report(self):
        if self.availability == "stage_available":
            if (self.stage_record is None or self.stage_record.run_id != self.run_id
                    or self.stage_record.assessment is not None
                    or self.origin == "model" and self.proposal is None or self.relations):
                raise ValueError("stage material requires an unassessed matching record")
        elif self.stage_record is not None:
            raise ValueError("stage record requires independent stage qualification")
        return self

    @model_serializer(mode="wrap")
    def compatible_review_shape(self, handler):
        value = handler(self)
        if self.insight_record is None:
            value.pop('insight_record', None)
        if not self.challenge_reviews:
            value.pop("challenge_reviews", None)
        return value


class SearchUsageV1(_ReaderModel):
    deepseek_search: int = Field(ge=0, le=50)
    tavily_search: int = Field(ge=0, le=50)
    page_attempts: int = Field(ge=0, le=8)
    review_attempts: int = Field(ge=0, le=9)
    rounds: int = Field(ge=0, le=3)
    active_seconds: float = Field(ge=0, le=90)


ReaderProcessDTO.model_rebuild()
