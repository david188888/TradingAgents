"""Closed current Insight process and per-role contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.agents.schemas._insight import InsightReport
from tradingagents.llm_clients.chatgpt_errors import ModelFailureDiagnostic

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
    "insight_stage_available",
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
    source_failures: tuple[str, ...] = ()
    model_failures: tuple[ModelFailureDiagnostic, ...] = ()
    search_usage: 'SearchUsageV1 | None' = None



class ReaderAgentDTO(_ReaderModel):
    insight_record: InsightReport | None = None
    schema_version: Literal[1] = 1
    run_id: str
    source_sequence: int = Field(ge=0)
    role_key: AgentKey
    availability: OutputAvailability
    reason_code: str | None = None
    origin: Literal["model", "code"]
    input_description: str


class SearchUsageV1(_ReaderModel):
    deepseek_search: int = Field(ge=0, le=50)
    tavily_search: int = Field(ge=0, le=50)
    page_attempts: int = Field(ge=0, le=8)
    review_attempts: int = Field(ge=0, le=9)
    rounds: int = Field(ge=0, le=3)
    active_seconds: float = Field(ge=0, le=90)

ReaderProcessDTO.model_rebuild()
