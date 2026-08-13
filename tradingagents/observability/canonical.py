"""Canonical redacted business values and declared AgentState projections."""

from __future__ import annotations

import base64
import hashlib
import math
import types
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Annotated, Any, get_args, get_origin, get_type_hints

import rfc8785
from typing_extensions import is_typeddict

from tradingagents.agents.utils.agent_states import AgentState

from .redaction import RedactionResult, redact_recursive

SERIALIZER_VERSION = 1
BUSINESS_PROJECTION_VERSION = 1
RESERVED_OBSERVATION_FIELD = "_observation_commits"


class UnsupportedCanonicalValue(TypeError):
    pass


def _tag(kind: str, value: str) -> str:
    return f"$tradingagents:{kind}:{value}"


def _convert(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value

    value_type = type(value)
    if value_type.__module__.startswith("pandas."):
        if value_type.__name__ == "NAType":
            return _tag("missing", "pd-na")
        if value_type.__name__ == "NaTType":
            return _tag("missing", "nat")
        if value_type.__name__ == "Timedelta":
            return _tag("timedelta", value.isoformat())

    is_numpy_scalar = any(
        base.__module__ == "numpy" and base.__name__ == "generic" for base in value_type.__mro__
    )
    if is_numpy_scalar:
        if value_type.__name__ in {"datetime64", "timedelta64"}:
            rendered = str(value)
            if rendered == "NaT":
                return _tag("missing", "nat")
            return _tag(value_type.__name__, rendered)
        return _convert(value.item())

    if isinstance(value, float):
        if math.isnan(value):
            return _tag("float", "nan")
        if math.isinf(value):
            return _tag("float", "infinity" if value > 0 else "-infinity")
        return value
    if isinstance(value, bytes):
        encoded = base64.b64encode(value).decode("ascii")
        return _tag("bytes-base64", encoded)
    if isinstance(value, datetime):
        return _tag("datetime", value.isoformat())
    if isinstance(value, date):
        return _tag("date", value.isoformat())
    if isinstance(value, time):
        return _tag("time", value.isoformat())
    if isinstance(value, timedelta):
        return _tag(
            "timedelta",
            f"{value.days}:{value.seconds}:{value.microseconds}",
        )
    if isinstance(value, Enum):
        return _convert(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return _convert({item.name: getattr(value, item.name) for item in fields(value)})
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _convert(model_dump(mode="python"))
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            invalid = next(key for key in value if not isinstance(key, str))
            raise UnsupportedCanonicalValue(
                f"canonical mapping keys must be strings, got {type(invalid).__name__}"
            )
        output = {}
        for key in sorted(value):
            output[key] = _convert(value[key])
        return output
    if isinstance(value, (list, tuple)):
        return [_convert(item) for item in value]
    if isinstance(value, (set, frozenset)):
        converted = [_convert(item) for item in value]
        return sorted(converted, key=rfc8785.dumps)
    raise UnsupportedCanonicalValue(
        f"unsupported canonical value: {type(value).__module__}.{type(value).__qualname__}"
    )


@dataclass(frozen=True)
class CanonicalBusinessValueV1:
    value: Any
    redaction: RedactionResult

    @property
    def bytes(self) -> bytes:
        try:
            return rfc8785.dumps(self.value)
        except rfc8785.CanonicalizationError as exc:
            raise UnsupportedCanonicalValue(f"RFC 8785 serialization failed: {exc}") from exc

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.bytes).hexdigest()


def canonical_business_value(
    value: Any,
    *,
    additional_credential_names: tuple[str, ...] | frozenset[str] = (),
) -> CanonicalBusinessValueV1:
    redaction = redact_recursive(
        value,
        additional_credential_names=additional_credential_names,
    )
    return CanonicalBusinessValueV1(_convert(redaction.value), redaction)


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_business_value(value).bytes


def canonical_sha256(value: Any) -> str:
    return canonical_business_value(value).sha256


def _normalized_type_description(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is Annotated:
        return _normalized_type_description(get_args(annotation)[0])
    if origin in (types.UnionType,):
        return (
            "union["
            + ",".join(_normalized_type_description(arg) for arg in get_args(annotation))
            + "]"
        )
    if origin is not None:
        name = getattr(origin, "__qualname__", str(origin).replace("typing.", ""))
        args = get_args(annotation)
        if not args:
            return name
        return f"{name}[{','.join(_normalized_type_description(arg) for arg in args)}]"
    if is_typeddict(annotation):
        hints = get_type_hints(annotation, include_extras=True)
        required = getattr(annotation, "__required_keys__", frozenset(hints))
        described = ",".join(
            f"{name}{'!' if name in required else '?'}:{_normalized_type_description(hints[name])}"
            for name in sorted(hints)
        )
        return f"typed-dict:{annotation.__module__}.{annotation.__qualname__}{{{described}}}"
    if isinstance(annotation, type):
        return f"{annotation.__module__}.{annotation.__qualname__}"
    return str(annotation).replace("typing.", "")


@dataclass(frozen=True)
class ApplicationStateSchema:
    application_fields: tuple[str, ...]
    document: dict[str, Any]
    sha256: str


def derive_application_state_schema(state_type: type) -> ApplicationStateSchema:
    hints = get_type_hints(state_type, include_extras=True)
    application_fields = tuple(
        sorted(
            name
            for name in hints
            if name != RESERVED_OBSERVATION_FIELD
        )
    )
    document = {
        "projection_version": BUSINESS_PROJECTION_VERSION,
        "fields": [
            {"name": name, "type": _normalized_type_description(hints[name])}
            for name in application_fields
        ],
    }
    return ApplicationStateSchema(
        application_fields=application_fields,
        document=document,
        sha256=canonical_sha256(document),
    )


_FROZEN_V2_SCHEMA_SHA256 = (
    "0aa01f8a0cca522554920bec7f212e120ba3d1a70032a17ab9f89da1b2b8b6b2"
)
_FROZEN_V2_APPLICATION_FIELDS = (
    "a_share_supplement_bundle",
    "adjusted_price_bundle",
    "allowed_actions",
    "analysis_cutoff",
    "asset_type",
    "canonical_company_profile",
    "clamp_events",
    "company_of_interest",
    "context_compaction_facts",
    "evidence_gate_fault",
    "evidence_ledger",
    "evidence_ledger_artifact_id",
    "evidence_report",
    "evidence_status",
    "execution_outcome",
    "feature_contributions",
    "final_trade_decision",
    "fundamentals_prefetch_bundle",
    "fundamentals_report",
    "holding_context",
    "holding_review_summary",
    "horizon",
    "instrument_context",
    "investment_debate_state",
    "investment_plan",
    "market_report",
    "messages",
    "methodology_reports",
    "mode",
    "news_report",
    "news_window_bundle",
    "past_context",
    "portfolio_context",
    "reader_public_output",
    "research_case_candidate",
    "research_dossier",
    "risk_debate_state",
    "sender",
    "sentiment_report",
    "trade_date",
    "trader_investment_plan",
)
_FROZEN_V2_SCHEMA_DOCUMENT = {
    "projection_version": 1,
    "fields": [
        {"name": "a_share_supplement_bundle", "type": "builtins.str"},
        {"name": "adjusted_price_bundle", "type": "builtins.str"},
        {"name": "allowed_actions", "type": "list[dict[builtins.str,typing.Any]]"},
        {"name": "analysis_cutoff", "type": "dict[builtins.str,typing.Any]"},
        {"name": "asset_type", "type": "builtins.str"},
        {"name": "canonical_company_profile", "type": "dict[builtins.str,typing.Any]"},
        {"name": "clamp_events", "type": "list[dict[builtins.str,typing.Any]]"},
        {"name": "company_of_interest", "type": "builtins.str"},
        {"name": "context_compaction_facts", "type": "list[builtins.str]"},
        {"name": "evidence_gate_fault", "type": "union[builtins.str,builtins.NoneType]"},
        {"name": "evidence_ledger", "type": "dict[builtins.str,typing.Any]"},
        {"name": "evidence_ledger_artifact_id", "type": "union[builtins.str,builtins.NoneType]"},
        {"name": "evidence_report", "type": "builtins.str"},
        {"name": "evidence_status", "type": "builtins.str"},
        {"name": "execution_outcome", "type": "union[dict[builtins.str,typing.Any],builtins.NoneType]"},
        {"name": "feature_contributions", "type": "list[dict[builtins.str,typing.Any]]"},
        {"name": "final_trade_decision", "type": "builtins.str"},
        {"name": "fundamentals_prefetch_bundle", "type": "builtins.str"},
        {"name": "fundamentals_report", "type": "builtins.str"},
        {"name": "holding_context", "type": "union[dict[builtins.str,typing.Any],builtins.NoneType]"},
        {"name": "holding_review_summary", "type": "union[dict[builtins.str,typing.Any],builtins.NoneType]"},
        {"name": "horizon", "type": "builtins.str"},
        {"name": "instrument_context", "type": "builtins.str"},
        {
            "name": "investment_debate_state",
            "type": "typed-dict:tradingagents.agents.utils.agent_states.InvestDebateState{bear_history!:builtins.str,bull_history!:builtins.str,count!:builtins.int,current_response!:builtins.str,history!:builtins.str,judge_decision!:builtins.str}",
        },
        {"name": "investment_plan", "type": "builtins.str"},
        {"name": "market_report", "type": "builtins.str"},
        {
            "name": "messages",
            "type": "list[Union[langchain_core.messages.ai.AIMessage,langchain_core.messages.human.HumanMessage,langchain_core.messages.chat.ChatMessage,langchain_core.messages.system.SystemMessage,langchain_core.messages.function.FunctionMessage,langchain_core.messages.tool.ToolMessage,langchain_core.messages.ai.AIMessageChunk,langchain_core.messages.human.HumanMessageChunk,langchain_core.messages.chat.ChatMessageChunk,langchain_core.messages.system.SystemMessageChunk,langchain_core.messages.function.FunctionMessageChunk,langchain_core.messages.tool.ToolMessageChunk]]",
        },
        {"name": "methodology_reports", "type": "dict[builtins.str,dict[builtins.str,typing.Any]]"},
        {"name": "mode", "type": "builtins.str"},
        {"name": "news_report", "type": "builtins.str"},
        {"name": "news_window_bundle", "type": "builtins.str"},
        {"name": "past_context", "type": "builtins.str"},
        {"name": "portfolio_context", "type": "union[dict[builtins.str,typing.Any],builtins.NoneType]"},
        {
            "name": "reader_public_output",
            "type": "typed-dict:tradingagents.agents.utils.agent_states.ReaderPublicOutput{kind!:Literal[research,trader,portfolio,risk],value!:dict[builtins.str,typing.Any]}",
        },
        {"name": "research_case_candidate", "type": "dict[builtins.str,builtins.str]"},
        {"name": "research_dossier", "type": "dict[builtins.str,typing.Any]"},
        {
            "name": "risk_debate_state",
            "type": "typed-dict:tradingagents.agents.utils.agent_states.RiskDebateState{aggressive_history!:builtins.str,conservative_history!:builtins.str,count!:builtins.int,current_aggressive_response!:builtins.str,current_conservative_response!:builtins.str,current_neutral_response!:builtins.str,history!:builtins.str,judge_decision!:builtins.str,latest_speaker!:builtins.str,neutral_history!:builtins.str,risk_signals!:list[dict[builtins.str,typing.Any]]}",
        },
        {"name": "sender", "type": "builtins.str"},
        {"name": "sentiment_report", "type": "builtins.str"},
        {"name": "trade_date", "type": "builtins.str"},
        {"name": "trader_investment_plan", "type": "builtins.str"},
    ],
}
_AGENT_STATE_SCHEMA_V2 = ApplicationStateSchema(
    application_fields=_FROZEN_V2_APPLICATION_FIELDS,
    document=_FROZEN_V2_SCHEMA_DOCUMENT,
    sha256=_FROZEN_V2_SCHEMA_SHA256,
)
if canonical_sha256(_FROZEN_V2_SCHEMA_DOCUMENT) != _FROZEN_V2_SCHEMA_SHA256:
    raise RuntimeError("frozen production v2 AgentState descriptor is corrupt")


class _AgentStateV3(AgentState):
    research_preflight: Annotated[
        dict[str, Any],
        "Explicit v3-only pure preflight scaffold",
    ]


_AGENT_STATE_SCHEMA_V3 = derive_application_state_schema(_AgentStateV3)


def agent_state_schema_for(
    policy_version: str,
) -> ApplicationStateSchema:
    if policy_version == "horizon-policy-v2":
        return _AGENT_STATE_SCHEMA_V2
    if policy_version == "horizon-policy-v3":
        return _AGENT_STATE_SCHEMA_V3
    raise ValueError("unsupported runtime policy version")


# Compatibility aliases remain pinned to production v2 until atomic v3 activation.
APPLICATION_STATE_FIELDS = _AGENT_STATE_SCHEMA_V2.application_fields
AGENT_STATE_SCHEMA_DOCUMENT = _AGENT_STATE_SCHEMA_V2.document
AGENT_STATE_SCHEMA_SHA256 = _AGENT_STATE_SCHEMA_V2.sha256
AGENT_STATE_SCHEMA_V2_SHA256 = _AGENT_STATE_SCHEMA_V2.sha256
AGENT_STATE_SCHEMA_V3_SHA256 = _AGENT_STATE_SCHEMA_V3.sha256


@dataclass(frozen=True)
class BusinessStateProjectionV1:
    values: dict[str, Any]
    application_fields: tuple[str, ...] = APPLICATION_STATE_FIELDS
    agent_state_schema_sha256: str = AGENT_STATE_SCHEMA_SHA256
    projection_version: int = BUSINESS_PROJECTION_VERSION

    @classmethod
    def from_channel_values(
        cls,
        channel_values: Mapping[str, Any],
        *,
        policy_version: str = "horizon-policy-v2",
    ) -> BusinessStateProjectionV1:
        schema = agent_state_schema_for(policy_version)
        return cls(
            {
                name: channel_values[name]
                for name in schema.application_fields
                if name in channel_values
            },
            application_fields=schema.application_fields,
            agent_state_schema_sha256=schema.sha256,
        )

    @property
    def canonical(self) -> CanonicalBusinessValueV1:
        return canonical_business_value(self.values)

    @property
    def sha256(self) -> str:
        return self.canonical.sha256


def project_business_delta(
    delta: Mapping[str, Any],
    *,
    policy_version: str = "horizon-policy-v2",
) -> dict[str, Any]:
    schema = agent_state_schema_for(policy_version)
    unknown = set(delta) - set(schema.application_fields) - {
        RESERVED_OBSERVATION_FIELD
    }
    if unknown:
        raise UnsupportedCanonicalValue(
            "node output contains undeclared application keys: " + ", ".join(sorted(unknown))
        )
    return {
        name: delta[name]
        for name in schema.application_fields
        if name in delta
    }


def business_delta_sha256(
    delta: Mapping[str, Any],
    *,
    policy_version: str = "horizon-policy-v2",
) -> str:
    return canonical_sha256(
        project_business_delta(delta, policy_version=policy_version)
    )


def pending_writes_touch_business_state(
    pending_writes: list[tuple[str, str, Any]] | tuple[tuple[str, str, Any], ...],
    *,
    policy_version: str = "horizon-policy-v2",
) -> bool:
    fields = agent_state_schema_for(policy_version).application_fields
    return any(len(write) >= 2 and write[1] in fields for write in pending_writes)
