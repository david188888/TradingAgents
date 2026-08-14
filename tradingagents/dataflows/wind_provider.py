"""Wind AIFin Market data provider.

Wraps the official ``wind-mcp-skill`` CLI (pinned 2.0.1) as a transport and
exposes source-neutral capabilities for A-share indices, China macro EDB series,
and equity risk metrics.

Design rules (see docs/wind-a-share-data-integration-plan.md):
- The transport calls the CLI via subprocess with ``@file`` params; it never
  re-implements the CLI's routing/validation/error classification.
- Only one Wind request is in flight at a time (Wind default concurrency is
  serial; the bundle-level parallelism must not propagate to Wind).
- ``null``/``INVALID`` means missing, never zero.
- ``analytics_data`` is never selected automatically.
- Symbol conversion only maps an already-canonical ``.SS`` to ``.SH``; it never
  guesses an exchange from a bare six-digit code.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import logging
import math
import os
import re
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from tradingagents.observability.provenance import capture_vendor_raw

from .coverage import CoveredText, PriceSeriesCoverageV1, SourceCoverageV1
from .errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIND_VENDOR = "wind"
SKILL_VERSION = "2.0.1"

# Default serial concurrency (Wind requirement).
DEFAULT_MAX_CONCURRENCY = 1
REQUEST_TIMEOUT_SECONDS = 120  # CLI itself has internal timeouts; this is a hard cap

# Wind CLI path: resolve symlinks because cli.mjs's IS_MAIN check compares
# import.meta.url (realpath) against process.argv[1] (symlink path) and fails
# silently (exit 0, no output) when they differ.
_DEFAULT_CLI_GLOB = str(
    Path.home() / ".claude" / "skills" / "wind-mcp-skill" / "scripts" / "cli.mjs"
)


def _resolve_cli_path() -> str:
    """Find the wind-mcp-skill CLI, resolving symlinks to the real path."""
    raw = os.getenv("WIND_CLI_PATH", _DEFAULT_CLI_GLOB)
    resolved = os.path.realpath(raw)
    if not os.path.isfile(resolved):
        raise WindNotConfiguredError(
            f"wind-mcp-skill CLI not found at {raw} (resolved: {resolved}). "
            "Install wind-mcp-skill or set WIND_CLI_PATH."
        )
    return resolved


# ---------------------------------------------------------------------------
# Wind-specific errors
# ---------------------------------------------------------------------------


class WindError(Exception):
    """Base class for Wind transport/provider errors."""

    def __init__(self, code: str, message: str = "", *, details: dict | None = None):
        self.code = code
        self.details = details or {}
        super().__init__(f"[{code}] {message}" if message else f"[{code}]")


class WindNotConfiguredError(VendorNotConfiguredError):
    """Wind API key or CLI is missing."""


class WindAuthError(WindError):
    """API key invalid or expired — manual recovery, no short retry."""


class WindQuotaError(WindError):
    """Daily quota exhausted or balance insufficient — manual/quota recovery."""


class WindRateLimitError(WindError, VendorRateLimitError):
    """QPS or concurrency limit — short cooldown, retry allowed."""


class WindNetworkError(WindError):
    """Temporary network/backend unavailability — bounded retry."""


class WindNoResultsError(WindError):
    """Tool succeeded but returned no matching data — not a transient error."""


class WindParamError(WindError):
    """Parameter or routing error — code defect, do not silently fall back."""


# ---------------------------------------------------------------------------
# Envelope & parsed table types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WindEnvelope:
    """Normalised result from one Wind CLI call."""

    is_error: bool
    server_type: str
    tool_name: str
    data: Any  # parsed inner JSON (the value of content[0].text)
    cli_meta: dict
    warnings: tuple[str, ...] = ()
    completeness: str = "unknown"

    @property
    def has_data(self) -> bool:
        return self.data is not None


@dataclass(frozen=True)
class WindTable:
    """A columns/rows table extracted from a Wind response."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    column_types: tuple[str, ...] = ()
    column_units: tuple[str | None, ...] = ()

    def row_dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]

    @property
    def is_empty(self) -> bool:
        return len(self.rows) == 0


@dataclass(frozen=True)
class WindEdbSeries:
    """One EDB indicator with metadata and optional observations."""

    code: str
    name: str
    freq: str
    unit: str
    source: str
    currency: str = ""
    magnitude: str = ""
    update_date: str = ""
    dates: tuple[str, ...] = ()
    values: tuple[float | None, ...] = ()


# ---------------------------------------------------------------------------
# Transport protocol & CLI implementation
# ---------------------------------------------------------------------------


@runtime_checkable
class WindTransport(Protocol):
    def call(
        self, server_type: str, tool_name: str, params: dict[str, Any]
    ) -> WindEnvelope: ...


class WindCliTransport:
    """Call wind-mcp-skill CLI via subprocess with @file params.

    - Resolves symlinks (cli.mjs IS_MAIN bug).
    - Uses @tempfile for params to avoid shell quote mangling.
    - Serialises all calls through a semaphore (default 1).
    - Passes WIND_API_KEY via env (never argv).
    """

    def __init__(
        self,
        *,
        cli_path: str | None = None,
        api_key: str | None = None,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        timeout: int = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._cli_path = cli_path or _resolve_cli_path()
        self._api_key = api_key or os.getenv("WIND_API_KEY", "")
        if not self._api_key:
            raise WindNotConfiguredError(
                "WIND_API_KEY is not set. Get a key from "
                "https://aifinmarket.wind.com.cn and set it in .env."
            )
        self._timeout = timeout
        self._sem = threading.BoundedSemaphore(max_concurrency)

    def call(
        self, server_type: str, tool_name: str, params: dict[str, Any]
    ) -> WindEnvelope:
        with self._sem:
            return self._do_call(server_type, tool_name, params)

    def _do_call(
        self, server_type: str, tool_name: str, params: dict[str, Any]
    ) -> WindEnvelope:
        # Write params to a temp file and pass @path to avoid shell quoting.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(params, f, ensure_ascii=False)
            param_path = f.name

        argv = [
            "node",
            self._cli_path,
            "call",
            server_type,
            tool_name,
            f"@{param_path}",
        ]
        env = {**os.environ, "WIND_API_KEY": self._api_key}

        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                env=env,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise WindNetworkError(
                "NETWORK_ERROR",
                f"Wind CLI timed out after {self._timeout}s "
                f"({server_type}.{tool_name})",
            ) from exc
        except OSError as exc:
            raise WindNetworkError(
                "NETWORK_ERROR", f"Failed to spawn Wind CLI: {exc}"
            ) from exc
        finally:
            with contextlib.suppress(OSError):
                os.unlink(param_path)

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        if stderr.strip():
            logger.debug(
                "Wind CLI stderr for %s.%s: %s",
                server_type,
                tool_name,
                stderr[:500],
            )
        if proc.returncode != 0:
            raise _classify_cli_error(stdout, stderr, server_type, tool_name)

        if not stdout.strip():
            raise WindNetworkError(
                "NETWORK_ERROR",
                f"Wind CLI produced no output (exit 0) for {server_type}.{tool_name}. "
                "This may indicate a symlink/IS_MAIN issue or CLI crash.",
            )

        return _parse_envelope(stdout, server_type, tool_name)

_transport_lock = threading.Lock()
_transport: WindTransport | None = None


def get_transport() -> WindTransport:
    """Return the process-wide WindCliTransport (lazy init)."""
    global _transport
    if _transport is not None:
        return _transport
    with _transport_lock:
        if _transport is None:
            from .config import get_config

            config = get_config()
            _transport = WindCliTransport(
                max_concurrency=int(
                    config.get("wind_max_concurrency", DEFAULT_MAX_CONCURRENCY)
                ),
                timeout=int(config.get("wind_request_timeout_seconds", REQUEST_TIMEOUT_SECONDS)),
            )
    return _transport


def _wind_enabled() -> bool:
    """Check the wind_enabled feature flag (defaults to False)."""
    from .config import get_config
    return bool(get_config().get("wind_enabled", False))


def _check_wind_enabled() -> None:
    """Raise WindNotConfiguredError if Wind is disabled in config."""
    if not _wind_enabled():
        raise WindNotConfiguredError(
            "Wind data source is disabled (wind_enabled=False). "
            "Set wind_enabled=True in config and WIND_API_KEY to activate."
        )


def set_transport(transport: WindTransport | None) -> None:
    """Replace the transport (for tests)."""
    global _transport
    with _transport_lock:
        _transport = transport


def _call_wind(
    server_type: str, tool_name: str, params: dict[str, Any]
) -> WindEnvelope:
    """Convenience wrapper that checks the feature flag and uses the singleton transport."""
    _check_wind_enabled()
    return get_transport().call(server_type, tool_name, params)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_INVALID_SENTINELS = {"INVALID", "N/A", "NA", "--", "-", "null", "None", ""}


def _coerce_numeric(value: Any) -> int | float | None:
    """Convert a Wind cell to a finite number, or None for missing."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    s = str(value).strip()
    if s in _INVALID_SENTINELS:
        return None
    # Remove thousand separators and trailing %
    s = s.replace(",", "")
    if s.endswith("%"):
        s = s[:-1]
    try:
        f = float(s)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(f):
        return None
    if f == int(f) and "." not in s and "e" not in s.lower():
        try:
            return int(s)
        except ValueError:
            return int(f)
    return f


def _coerce_cell(value: Any, col_type: str) -> Any:
    """Convert a cell based on its declared column type.

    Wind declares some numeric columns (e.g. kline OHLCV, price indicators)
    as type ``"string"``, so for string-typed cells we attempt a safe numeric
    coercion: the value must parse as a number AND round-trip back to the same
    string (preventing codes like ``"000300"`` or dates like ``"20260812"``
    from being silently converted).
    """
    if value is None or (isinstance(value, str) and value.strip() in _INVALID_SENTINELS):
        return None
    if col_type in ("number", "int", "float"):
        return _coerce_numeric(value)
    if col_type == "date":
        return str(value)
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if stripped.endswith("%"):
            stripped = stripped[:-1]
        if _safely_numeric(stripped):
            return _coerce_numeric(value)
    return str(value) if isinstance(value, str) else value


def _safely_numeric(s: str) -> bool:
    """Check if a string is numeric and safe to convert.

    Safe means:
    - Contains a decimal point (e.g. ``"4690.92"``) — never a code or date.
    - Is a long integer without leading zeros (e.g. ``"18493914800"`` volume) —
      codes and dates are 6-8 digits and may have leading zeros.
    - Is ``"0"``.

    Unsafe:
    - Leading-zero integers (``"000300"`` codes, ``"20260812"`` dates).
    - Short integers (``"300"`` constituent count is already type=number).
    """
    if not s:
        return False
    if "." in s:
        try:
            float(s)
            return not s.startswith("0") or s.startswith("0.")
        except ValueError:
            return False
    if s.isdigit():
        if s == "0":
            return True
        if s.startswith("0"):
            return False  # codes, dates, etc.
        # Long bare integers (> 8 digits) are almost always volume/amount.
        return len(s) > 8
    # Negative numbers
    if s.startswith("-") and s[1:].replace(".", "", 1).isdigit():
        try:
            float(s)
            return True
        except ValueError:
            return False
    return False


def _extract_tables(data: Any) -> list[WindTable]:
    """Extract all columns/rows tables from parsed inner JSON.

    Wind responses place tables at different paths depending on the tool:
    - price_indicators / kline: ``$.data`` itself is a table
    - fundamentals / basicinfo / risk: ``$.data.data[N]`` is a table
    """
    tables: list[WindTable] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if "columns" in obj and "rows" in obj:
                raw_cols = obj.get("columns") or []
                raw_rows = obj.get("rows")
                # A malformed rows payload must not become one pseudo-row per
                # character. Ignore the candidate table and let the provider
                # report NoMarketDataError if no valid table remains.
                if not isinstance(raw_rows, list):
                    raw_rows = None
                # Only treat as a table if columns is a non-empty list of dicts
                # with a "name" key. This avoids false matches on dicts that
                # happen to have a "columns" key with string values.
                if (
                    isinstance(raw_cols, list)
                    and raw_cols
                    and raw_rows is not None
                    and all(isinstance(c, dict) and "name" in c for c in raw_cols)
                ):
                    cols = [c.get("name", f"col_{i}") for i, c in enumerate(raw_cols)]
                    types = [c.get("type", "string") for c in raw_cols]
                    units = [c.get("unit") for c in raw_cols]
                    rows: list[tuple[Any, ...]] = []
                    for raw_row in raw_rows:
                        if not isinstance(raw_row, (list, tuple)) or len(raw_row) != len(types):
                            logger.warning("Skipping malformed Wind table row")
                            continue
                        row = tuple(
                            _coerce_cell(cell, types[i])
                            for i, cell in enumerate(raw_row)
                        )
                        rows.append(row)
                    tables.append(
                        WindTable(
                            columns=tuple(cols),
                            rows=tuple(rows),
                            column_types=tuple(types),
                            column_units=tuple(units),
                        )
                    )
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(data)
    return tables


def _extract_edb_series(data: Any) -> list[WindEdbSeries]:
    """Extract EDB series from an economic_data response.

    The inner JSON has two possible shapes:
    - ``{"data": {"code": 0, "data": [...]}, "error": null}`` (normal)
    - ``{"data": [...], "error": null}`` (defensive)
    We dig through until we find the list of series objects.
    """
    if not isinstance(data, dict):
        return []
    payload = data.get("data")
    # Normal shape: data.data is a list (may also have data.code)
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        payload = payload["data"]
    if not isinstance(payload, list):
        return []
    series_list: list[WindEdbSeries] = []
    for item in payload:
        if not isinstance(item, dict):
            logger.warning("Skipping non-dict EDB item: %s", type(item).__name__)
            continue
        meta = item.get("meta") or {}
        if not isinstance(meta, dict):
            logger.warning("Skipping malformed EDB metadata: %s", type(meta).__name__)
            meta = {}
        raw_dates = item.get("date", [])
        raw_values = item.get("value", [])
        if not isinstance(raw_dates, list) or not isinstance(raw_values, list):
            logger.warning("Skipping EDB item with non-list observations: %s", meta)
            continue
        if len(raw_dates) != len(raw_values):
            logger.warning("Skipping EDB item with mismatched date/value lengths: %s", meta)
            continue
        dates = tuple(str(d) for d in raw_dates)
        values = tuple(_coerce_numeric(v) for v in raw_values)
        series_list.append(
            WindEdbSeries(
                code=meta.get("code", ""),
                name=meta.get("name", meta.get("enName", "")),
                freq=meta.get("freq", meta.get("enFreq", "")),
                unit=meta.get("unit", meta.get("enUnit", "")),
                source=meta.get("source", meta.get("enSource", "")),
                currency=meta.get("currency", meta.get("enCurrency", "")),
                magnitude=meta.get("magnitude", meta.get("enMagnitude", "")),
                update_date=meta.get("updateDate", ""),
                dates=dates,
                values=values,
            )
        )
    return series_list


def _parse_envelope(stdout: str, server_type: str, tool_name: str) -> WindEnvelope:
    """Parse the CLI JSON envelope and extract inner data."""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise WindNetworkError(
            "NETWORK_ERROR", f"Wind CLI returned non-JSON output: {stdout[:300]}"
        ) from exc

    # Error envelope from CLI
    if envelope.get("ok") is False:
        err = envelope.get("error", {})
        code = str(err.get("code", "UNKNOWN"))
        msg = err.get("message", str(err.get("details", "")))
        raise _classify_wind_code(code, msg, err.get("details", {}))

    cli_meta = envelope.get("cli_meta", {})
    is_error = bool(envelope.get("isError", False))

    # Extract inner JSON from content[0].text
    inner_data: Any = None
    warnings: list[str] = []
    content = envelope.get("content", [])
    if content and isinstance(content, list):
        text = content[0].get("text", "") if isinstance(content[0], dict) else ""
        if text:
            try:
                inner_data = json.loads(text)
            except json.JSONDecodeError:
                inner_data = text  # plain text response
            if isinstance(inner_data, dict) and inner_data.get("error"):
                # Backend returned an error alongside data
                err_obj = inner_data["error"]
                if err_obj and err_obj.get("code") not in (None, 0):
                    warnings.append(
                        f"backend_error: {err_obj.get('code')} {err_obj.get('message', '')}"
                    )

    # Check for inner business-level errors
    if isinstance(inner_data, dict):
        inner_err = inner_data.get("error")
        if inner_err and isinstance(inner_err, dict):
            code = inner_err.get("code")
            if code and code != 0 and not inner_data.get("data"):
                raise _classify_wind_code(
                    str(code), inner_err.get("message", ""), inner_err
                )

    return WindEnvelope(
        is_error=is_error,
        server_type=server_type,
        tool_name=tool_name,
        data=inner_data,
        cli_meta=cli_meta,
        warnings=tuple(warnings),
        completeness=cli_meta.get("completeness", "unknown"),
    )


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

# Mapping of Wind CLI error codes to exception classes.
_CODE_MAP: dict[str, type[WindError]] = {
    "AUTH_ERROR": WindAuthError,
    "BALANCE_ERROR": WindQuotaError,
    "DAILY_LIMIT_ERROR": WindQuotaError,
    "RATE_LIMIT_ERROR": WindRateLimitError,
    "CONCURRENCY_LIMIT_ERROR": WindRateLimitError,
    "NETWORK_ERROR": WindNetworkError,
    "TEMPORARILY_UNAVAILABLE": WindNetworkError,
    "NO_RESULTS": WindNoResultsError,
    "MARKET_TARGET_NOT_FOUND": WindNoResultsError,
    "EDB_INDICATOR_NOT_FOUND": WindNoResultsError,
    "ROUTE_ERROR": WindParamError,
    "USAGE_ERROR": WindParamError,
    "INVALID_PARAMS_JSON": WindParamError,
    "PARAMS_FILE_ERROR": WindParamError,
    "PARAM_TYPE_ERROR": WindParamError,
    "PARAM_VALIDATION_ERROR": WindParamError,
    "PERIOD_PARSE_ERROR": WindParamError,
    "SETUP_ERROR": WindNotConfiguredError,
    "TOOL_RUNTIME_ERROR": WindNetworkError,
    # Defensive classification for a CLI/backend that surfaces HTTP status
    # codes instead of the documented symbolic error codes.
    "401": WindAuthError,
    "403": WindAuthError,
    "429": WindRateLimitError,
    "500": WindNetworkError,
    "502": WindNetworkError,
    "503": WindNetworkError,
    "504": WindNetworkError,
}


def _classify_wind_code(
    code: str, message: str, details: dict | None = None
) -> WindError:
    exc_cls = _CODE_MAP.get(code, WindError)
    return exc_cls(code, message, details=details)


def _classify_cli_error(
    stdout: str, stderr: str, server_type: str, tool_name: str
) -> WindError:
    """Classify a non-zero CLI exit into a typed WindError."""
    raw = stdout.strip() or stderr.strip()
    if not raw:
        return WindNetworkError(
            "NETWORK_ERROR",
            f"Wind CLI exited with no output ({server_type}.{tool_name})",
        )
    try:
        envelope = json.loads(raw)
        if envelope.get("ok") is False:
            err = envelope.get("error", {})
            return _classify_wind_code(
                str(err.get("code", "UNKNOWN")),
                err.get("message", err.get("agent_action", raw[:300])),
                err.get("details"),
            )
    except json.JSONDecodeError:
        pass
    return WindError("UNKNOWN", raw[:500])


# ---------------------------------------------------------------------------
# Symbol conversion & index registry
# ---------------------------------------------------------------------------

# Canonical internal suffix -> Wind suffix.
# Only .SS (Shanghai) needs conversion to .SH. .SZ/.BJ are already Wind-compatible.
_WIND_SUFFIX_MAP = {".SS": ".SH"}

# Known A-share index codes with explicit Wind suffix.
# A bare 000xxx code is ambiguous (SH index vs SZ stock like 000001 Ping An Bank),
# so we never guess — only codes in this registry are treated as indices.
_INDEX_REGISTRY: dict[str, dict[str, str]] = {
    # Major indices
    "000300.SH": {"name": "沪深300", "exchange": "SH", "type": "broad_market"},
    "000905.SH": {"name": "中证500", "exchange": "SH", "type": "broad_market"},
    "000852.SH": {"name": "中证1000", "exchange": "SH", "type": "broad_market"},
    "000016.SH": {"name": "上证50", "exchange": "SH", "type": "broad_market"},
    "000010.SH": {"name": "上证180", "exchange": "SH", "type": "broad_market"},
    "000688.SH": {"name": "科创50", "exchange": "SH", "type": "broad_market"},
    "000001.SH": {"name": "上证指数", "exchange": "SH", "type": "broad_market"},
    "399001.SZ": {"name": "深证成指", "exchange": "SZ", "type": "broad_market"},
    "399006.SZ": {"name": "创业板指", "exchange": "SZ", "type": "broad_market"},
    "399303.SZ": {"name": "国证2000", "exchange": "SZ", "type": "broad_market"},
}

# Reverse lookup: internal canonical symbol -> wind code
_INTERNAL_TO_WIND_INDEX = {
    "000300.SS": "000300.SH",
    "000905.SS": "000905.SH",
    "000852.SS": "000852.SH",
    "000016.SS": "000016.SH",
    "000010.SS": "000010.SH",
    "000688.SS": "000688.SH",
    "000001.SS": "000001.SH",
}


def to_wind_symbol(symbol: str, *, is_index: bool = False) -> str:
    """Convert an internal canonical symbol to a Wind code.

    - ``600519.SS`` → ``600519.SH`` (Shanghai stock)
    - ``000001.SZ`` → ``000001.SZ`` (Shenzhen, unchanged)
    - ``000300.SS`` with ``is_index=True`` → ``000300.SH``
    - Already-Wind codes (``.SH/.SZ/.BJ/.HI/.O``) pass through
    - Bare codes raise ValueError — never guess the exchange

    For indices, the caller must set ``is_index=True`` or use an explicit
    ``.SS`` suffix, because ``000001`` alone is ambiguous.
    """
    raw = symbol.strip().upper()

    # Already a Wind-style code
    if re.search(r"\.(SH|SZ|BJ|HI|O|OF|SI)$", raw):
        return raw

    # Internal canonical -> Wind suffix
    for internal_suffix, wind_suffix in _WIND_SUFFIX_MAP.items():
        if raw.endswith(internal_suffix):
            base = raw[: -len(internal_suffix)]
            return f"{base}{wind_suffix}"

    # .SZ and .BJ are already Wind-compatible
    if raw.endswith((".SZ", ".BJ")):
        return raw

    # For index: check internal index mapping
    if is_index and raw in _INTERNAL_TO_WIND_INDEX:
        return _INTERNAL_TO_WIND_INDEX[raw]

    # Bare 6-digit code — refuse to guess
    if re.fullmatch(r"\d{6}", raw):
        raise ValueError(
            f"Cannot convert bare code {raw!r} to Wind symbol without an explicit "
            f"exchange suffix or is_index=True. Use e.g. 600519.SS or 000300.SH."
        )

    raise ValueError(f"Unrecognised symbol format: {symbol!r}")


def resolve_index_code(index: str) -> str:
    """Resolve an index name or code to a Wind index code.

    Accepts:
    - A Wind index code (``000300.SH``)
    - An internal canonical (``000300.SS``)
    - A known Chinese name (``沪深300``, ``CSI300``)
    """
    raw = index.strip()
    # Direct Wind code
    if raw in _INDEX_REGISTRY:
        return raw
    # Internal canonical
    if raw in _INTERNAL_TO_WIND_INDEX:
        return _INTERNAL_TO_WIND_INDEX[raw]
    # Name lookup
    for code, info in _INDEX_REGISTRY.items():
        if raw in (info["name"], info.get("name_en", "")):
            return code
    # If it looks like a code with exchange, pass through
    if re.search(r"\.(SH|SZ|BJ)$", raw.upper()):
        return raw.upper()
    # Try as a natural-language name for Wind NER (get_index_quote accepts names)
    return raw


def get_index_info(index_code: str) -> dict[str, str] | None:
    """Return registry info for a known index code, or None."""
    return _INDEX_REGISTRY.get(index_code)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _today() -> str:
    return date.today().isoformat()


def _table_to_csv(table: WindTable) -> str:
    """Render a WindTable as RFC 4180-compatible CSV text."""
    rows: list[list[Any]] = [list(table.columns)]
    rows.extend(
        ["" if cell is None else cell for cell in row]
        for row in table.rows
    )
    return _rows_to_csv(rows)


def _rows_to_csv(rows: list[list[Any]]) -> str:
    """Render rows with correct quoting for commas, quotes, and newlines."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue().rstrip("\n")


def _latest_only_degradation(as_of: str | None) -> tuple[str, ...]:
    """Describe that snapshot-like Wind endpoints only return latest data."""
    if as_of and as_of != _today():
        return (f"requested_as_of_unavailable: latest_available_as_of_{_today()}",)
    return ()


def _make_coverage(
    capability: str,
    source_tool: str,
    *,
    item_count: int,
    as_of: str | None = None,
    requested_start: str | None = None,
    requested_end: str | None = None,
    actual_start: str | None = None,
    actual_end: str | None = None,
    completeness: str = "unknown",
    degradations: tuple[str, ...] = (),
) -> SourceCoverageV1:
    source_id = f"wind.{source_tool}"
    return SourceCoverageV1(
        capability=capability,
        source_id=source_id,
        requested_start=requested_start,
        requested_end=requested_end,
        actual_start=actual_start,
        actual_end=actual_end,
        item_count=item_count,
        completeness=completeness,  # type: ignore[arg-type]
        sources=(WIND_VENDOR, source_id),
        degradations=degradations,
        as_of=as_of or _today(),
    )


# ---------------------------------------------------------------------------
# Provider: Adjusted stock price history
# ---------------------------------------------------------------------------


def get_stock_adjusted_price_history(
    symbol: str,
    start_date: str,
    end_date: str,
) -> str:
    """Retrieve explicitly forward-adjusted daily A-share OHLCV from Wind."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        raise ValueError("start_date cannot be after end_date")
    windcode = to_wind_symbol(symbol)
    params = {
        "windcode": windcode,
        "begin_date": start_date,
        "end_date": end_date,
        "period": "1d",
        "aftype": "0",
        "issusp": "0",
    }
    envelope = _call_wind("stock_data", "get_stock_kline", params)
    tables = _extract_tables(envelope.data)
    if not tables or tables[0].is_empty:
        raise NoMarketDataError(
            symbol,
            canonical=windcode,
            detail="Wind returned no adjusted stock kline data",
        )

    table = tables[0]
    date_column = next(
        (
            column
            for column in table.columns
            if str(column).strip().upper() in {"TIME", "DATE", "TRADE_DATE", "日期"}
        ),
        None,
    )
    if date_column is None:
        raise WindParamError(
            "INVALID_PAYLOAD",
            "Wind stock kline response has no date column",
        )
    valid_rows = []
    valid_dates = []
    date_index = table.columns.index(date_column)
    for row in table.rows:
        value = str(row[date_index])[:10]
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            continue
        if start <= parsed <= end:
            valid_rows.append(row)
            valid_dates.append(parsed.isoformat())
    if not valid_dates:
        raise NoMarketDataError(
            symbol,
            canonical=windcode,
            detail=f"no adjusted rows inside {start_date}..{end_date}",
        )
    table = WindTable(
        columns=table.columns,
        rows=tuple(valid_rows),
        column_types=table.column_types,
        column_units=table.column_units,
    )

    actual_start = min(valid_dates)
    actual_end = max(valid_dates)
    exact_boundaries = actual_start == start_date and actual_end == end_date
    coverage = PriceSeriesCoverageV1(
        capability="adjusted_price_history",
        source_id="wind.stock_kline_qfq_daily",
        requested_start=start_date,
        requested_end=end_date,
        actual_start=actual_start,
        actual_end=actual_end,
        item_count=len(valid_dates),
        completeness="complete" if exact_boundaries else "unknown",
        sources=(WIND_VENDOR, "wind.stock_kline_qfq_daily"),
        degradations=(
            () if exact_boundaries else ("trading_calendar_boundaries_not_proven",)
        ),
        as_of=end_date,
        price_basis="qfq",
        adjustment_source="wind.stock_data.get_stock_kline(aftype=0)",
        adjustment_verified=True,
        granularity="daily",
    )
    capture_vendor_raw(
        {"table": table.row_dicts(), "params": params},
        metadata={
            "provider": WIND_VENDOR,
            "dataset": "adjusted_price_history",
            "symbol": symbol,
            "price_basis": "qfq",
        },
    )
    text = "\n".join(
        [
            f"# Adjusted stock data for {symbol} ({windcode}) from {start_date} to {end_date}",
            f"# Source: wind (stock_data.get_stock_kline, skill {SKILL_VERSION})",
            "# Price basis: qfq",
            "# Adjustment source: wind.stock_data.get_stock_kline(aftype=0)",
            "# This series is for historical returns, trend, and indicators; do not use it as an executable current-price quote.",
            "",
            _table_to_csv(table),
        ]
    )
    if envelope.warnings:
        text += "\n# Warnings: " + "; ".join(envelope.warnings)
    return CoveredText(text, coverage)


# ---------------------------------------------------------------------------
# Provider: Index capabilities
# ---------------------------------------------------------------------------


def get_index_snapshot(index: str, as_of: str | None = None) -> str:
    """Current-trading-day snapshot for an index (latest price, OHLC, volume)."""
    windcode = resolve_index_code(index)
    envelope = _call_wind(
        "index_data",
        "get_index_price_indicators",
        {"windcode": windcode},
    )
    tables = _extract_tables(envelope.data)
    if not tables or tables[0].is_empty:
        raise NoMarketDataError(index, canonical=windcode, detail="Wind returned no index snapshot")

    table = tables[0]
    capture_vendor_raw(
        {"table": table.row_dicts(), "warnings": envelope.warnings},
        metadata={"provider": WIND_VENDOR, "dataset": "index_snapshot", "index": index},
    )

    degradations = _latest_only_degradation(as_of)
    coverage = _make_coverage(
        "index_snapshot",
        "get_index_price_indicators",
        item_count=len(table.rows),
        completeness="unknown" if envelope.completeness != "complete" else "complete",
        degradations=degradations,
    )
    latest_note = (
        f"# Requested as-of: {as_of}; Wind endpoint returned latest available data."
        if degradations
        else None
    )
    text = "\n".join(
        [
            f"# Index snapshot for {index} ({windcode})",
            f"# Source: wind (index_data.get_index_price_indicators, skill {SKILL_VERSION})",
            f"# Retrieved: {_today()}",
        ]
        + ([latest_note] if latest_note else [])
        + ["", _table_to_csv(table)]
    )
    if envelope.warnings:
        text += "\n# Warnings: " + "; ".join(envelope.warnings)
    return CoveredText(text, coverage)


def get_index_history(
    index: str,
    start_date: str,
    end_date: str,
    period: str = "1d",
) -> str:
    """Historical OHLCV bars for an index."""
    windcode = resolve_index_code(index)
    params: dict[str, Any] = {
        "windcode": windcode,
        "begin_date": start_date,
        "end_date": end_date,
        "period": period,
    }
    envelope = _call_wind("index_data", "get_index_kline", params)
    tables = _extract_tables(envelope.data)
    if not tables or tables[0].is_empty:
        raise NoMarketDataError(
            index, canonical=windcode, detail="Wind returned no index kline data"
        )

    table = tables[0]
    capture_vendor_raw(
        {"table": table.row_dicts(), "params": params},
        metadata={"provider": WIND_VENDOR, "dataset": "index_history", "index": index},
    )

    # Determine actual date range from rows (TIME is the first column)
    actual_start = actual_end = None
    if table.rows and table.columns[0].upper() == "TIME":
        dates = [str(r[0])[:10] for r in table.rows if r[0]]
        if dates:
            actual_start = min(dates)
            actual_end = max(dates)

    coverage = _make_coverage(
        "index_history",
        "get_index_kline",
        item_count=len(table.rows),
        requested_start=start_date,
        requested_end=end_date,
        actual_start=actual_start,
        actual_end=actual_end,
        completeness="partial" if envelope.warnings else "unknown",
    )
    text = "\n".join(
        [
            f"# Index history for {index} ({windcode}) {start_date} to {end_date}",
            f"# Source: wind (index_data.get_index_kline, skill {SKILL_VERSION})",
            f"# Period: {period}",
            "",
            _table_to_csv(table),
        ]
    )
    return CoveredText(text, coverage)


def get_index_profile(index: str) -> str:
    """Static profile for an index (publisher, base date, constituent count)."""
    windcode = resolve_index_code(index)
    question = f"查询{windcode}指数的基本信息，包括发布机构、基日和成份股数量"
    envelope = _call_wind(
        "index_data", "get_index_basicinfo", {"question": question}
    )
    tables = _extract_tables(envelope.data)
    if not tables or tables[0].is_empty:
        raise NoMarketDataError(index, canonical=windcode, detail="Wind returned no index profile")

    table = tables[0]
    capture_vendor_raw(
        {"table": table.row_dicts()},
        metadata={"provider": WIND_VENDOR, "dataset": "index_profile", "index": index},
    )

    coverage = _make_coverage(
        "index_profile",
        "get_index_basicinfo",
        item_count=len(table.rows),
        completeness="unknown",
    )
    text = "\n".join(
        [
            f"# Index profile for {index} ({windcode})",
            f"# Source: wind (index_data.get_index_basicinfo, skill {SKILL_VERSION})",
            f"# Retrieved: {_today()}",
            "",
            _table_to_csv(table),
        ]
    )
    return CoveredText(text, coverage)


def get_index_fundamentals(index: str, as_of: str | None = None) -> str:
    """Valuation fundamentals for an index (PE, PB, dividend yield)."""
    windcode = resolve_index_code(index)
    question = f"查询{windcode}指数最新的PE、PB和股息率"
    envelope = _call_wind(
        "index_data", "get_index_fundamentals", {"question": question}
    )
    tables = _extract_tables(envelope.data)
    if not tables or tables[0].is_empty:
        raise NoMarketDataError(
            index, canonical=windcode, detail="Wind returned no index fundamentals"
        )

    table = tables[0]
    capture_vendor_raw(
        {"table": table.row_dicts()},
        metadata={"provider": WIND_VENDOR, "dataset": "index_fundamentals", "index": index},
    )

    degradations = _latest_only_degradation(as_of)
    coverage = _make_coverage(
        "index_fundamentals",
        "get_index_fundamentals",
        item_count=len(table.rows),
        completeness="unknown",
        degradations=degradations,
    )
    latest_note = (
        f"# Requested as-of: {as_of}; Wind endpoint returned latest available data."
        if degradations
        else None
    )
    text = "\n".join(
        [
            f"# Index fundamentals for {index} ({windcode})",
            f"# Source: wind (index_data.get_index_fundamentals, skill {SKILL_VERSION})",
            f"# Retrieved: {_today()}",
        ]
        + ([latest_note] if latest_note else [])
        + ["", _table_to_csv(table)]
    )
    return CoveredText(text, coverage)


# ---------------------------------------------------------------------------
# Provider: China macro EDB
# ---------------------------------------------------------------------------

# Audited EDB code allowlist. Production fetch must use codes from this list or
# codes explicitly returned by a search; we do not let the LLM invent codes.
_EDB_ALLOWLIST: dict[str, dict[str, str]] = {
    "M0001395": {
        "name": "中国:GDP:现价",
        "freq": "年",
        "unit": "亿元",
        "source": "国家统计局",
    },
    "M5567876": {
        "name": "中国:GDP:现价:当季值",
        "freq": "季",
        "unit": "亿元",
        "source": "国家统计局",
    },
}


def search_macro_series(query: str) -> str:
    """Search Wind EDB for macro/industry indicators matching a natural-language query.

    Returns a CSV of candidate indicators with codes, names, frequency, and units.
    The caller should review and add codes to the allowlist before using fetch in
    production.
    """
    envelope = _call_wind(
        "economic_data",
        "natural_language_get_edb_data",
        {"executionMode": "search", "question": query},
    )
    series_list = _extract_edb_series(envelope.data)
    if not series_list:
        raise NoMarketDataError(query, detail=f"No EDB indicators found for query: {query}")

    capture_vendor_raw(
        {"query": query, "results": [s.__dict__ for s in series_list]},
        metadata={"provider": WIND_VENDOR, "dataset": "edb_search", "query": query},
    )

    lines = [["code", "name", "freq", "unit", "source", "currency", "magnitude", "update_date"]]
    for s in series_list:
        lines.append([
            s.code, s.name, s.freq, s.unit, s.source,
            s.currency, s.magnitude, s.update_date,
        ])
    csv_text = _rows_to_csv(lines)
    text = "\n".join(
        [
            f"# EDB search results for: {query}",
            f"# Source: wind (economic_data.natural_language_get_edb_data, skill {SKILL_VERSION})",
            f"# Retrieved: {_today()}",
            f"# {len(series_list)} indicator(s) found. Review codes before using in production fetch.",
            "",
            csv_text,
        ]
    )
    coverage = _make_coverage(
        "macro_series_search",
        "natural_language_get_edb_data",
        item_count=len(series_list),
        completeness="unknown",
    )
    return CoveredText(text, coverage)


def get_macro_series(
    series_ids: str,
    start_date: str,
    end_date: str,
) -> str:
    """Fetch EDB time-series data by audited indicator code(s).

    ``series_ids`` is a comma-separated list of EDB codes (e.g. ``M0001395``).
    Codes should come from the allowlist or a prior search result; unknown codes
    are still passed to Wind but flagged in the output.
    """
    codes = [c.strip() for c in series_ids.split(",") if c.strip()]
    if not codes:
        raise ValueError("series_ids must contain at least one EDB code")

    from .config import get_config

    config = get_config()
    unknown = [c for c in codes if c not in _EDB_ALLOWLIST]
    if unknown and bool(config.get("wind_strict_edb_allowlist", False)):
        raise WindParamError(
            "EDB_ALLOWLIST_ERROR",
            f"EDB codes not in Wind allowlist: {', '.join(unknown)}",
        )

    envelope = _call_wind(
        "economic_data",
        "natural_language_get_edb_data",
        {
            "executionMode": "fetch",
            "question": ",".join(codes),
            "beginDate": start_date,
            "endDate": end_date,
        },
    )
    series_list = _extract_edb_series(envelope.data)
    if not series_list:
        raise NoMarketDataError(
            series_ids, detail=f"No EDB data returned for codes: {series_ids}"
        )

    capture_vendor_raw(
        {"codes": codes, "series": [s.__dict__ for s in series_list]},
        metadata={"provider": WIND_VENDOR, "dataset": "edb_fetch", "codes": series_ids},
    )

    rows: list[list[Any]] = [["code", "name", "date", "value", "unit", "freq", "source"]]
    total_obs = 0
    for s in series_list:
        for dt, val in zip(s.dates, s.values, strict=True):
            rows.append([s.code, s.name, dt, "" if val is None else val, s.unit, s.freq, s.source])
            total_obs += 1
    csv_text = _rows_to_csv(rows)

    warnings = list(envelope.warnings)
    if unknown:
        warnings.append(f"codes_not_in_allowlist: {','.join(unknown)}")

    text = "\n".join(
        [
            f"# EDB series: {series_ids}",
            f"# Source: wind (economic_data.natural_language_get_edb_data, skill {SKILL_VERSION})",
            f"# Window: {start_date} to {end_date}",
            f"# Retrieved: {_today()}",
            f"# {total_obs} observation(s) across {len(series_list)} series",
        ]
        + ([f"# Warnings: {'; '.join(warnings)}"] if warnings else [])
        + ["", csv_text]
    )
    coverage = _make_coverage(
        "macro_series",
        "natural_language_get_edb_data",
        item_count=total_obs,
        requested_start=start_date,
        requested_end=end_date,
        completeness="partial" if warnings else "unknown",
    )
    return CoveredText(text, coverage)


# ---------------------------------------------------------------------------
# Provider: Equity risk metrics
# ---------------------------------------------------------------------------


def get_equity_risk_metrics(
    symbol: str,
    window: str = "1y",
    fields: str | None = None,
    benchmark: str | None = None,
) -> str:
    """Quantitative risk metrics for an A-share stock (Beta, volatility, drawdown).

    ``window`` is a human-readable window (e.g. '1y', '6m', '3y') used to build
    the natural-language question for Wind. ``fields`` is a comma-separated list
    of desired metrics; defaults to Beta, annualised volatility, max drawdown.
    """
    windcode = to_wind_symbol(symbol)
    field_list = fields or "Beta、年化波动率、最大回撤、夏普比率"
    bench = f"，相对{benchmark}" if benchmark else ""
    question = f"查询{windcode}过去{window}的{field_list}{bench}"

    envelope = _call_wind(
        "stock_data", "get_risk_metrics", {"question": question}
    )
    tables = _extract_tables(envelope.data)
    if not tables or tables[0].is_empty:
        raise NoMarketDataError(
            symbol, canonical=windcode, detail="Wind returned no risk metrics"
        )

    table = tables[0]
    capture_vendor_raw(
        {"table": table.row_dicts(), "question": question},
        metadata={
            "provider": WIND_VENDOR,
            "dataset": "risk_metrics",
            "symbol": symbol,
        },
    )

    coverage = _make_coverage(
        "equity_risk_metrics",
        "get_risk_metrics",
        item_count=len(table.rows),
        completeness="unknown",
    )
    text = "\n".join(
        [
            f"# Equity risk metrics for {symbol} ({windcode})",
            f"# Source: wind (stock_data.get_risk_metrics, skill {SKILL_VERSION})",
            f"# Window: {window}",
            f"# Retrieved: {_today()}",
            "",
            _table_to_csv(table),
        ]
    )
    return CoveredText(text, coverage)
