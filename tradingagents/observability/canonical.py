"""Canonical redacted business values and declared AgentState projections."""

from __future__ import annotations

import base64
import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any

import rfc8785

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
