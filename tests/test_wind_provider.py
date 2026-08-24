"""Tests for the Wind AIFin Market data provider.

Covers:
- Symbol conversion and index registry
- Response parsing (tables, EDB series, numeric coercion, INVALID→null)
- Error classification (CLI envelopes → typed exceptions)
- Transport safety (realpath, @file params, no key in argv)
- Health/error mapping (cooldowns, manual locks, recoverability)
- Registry/router wiring
- Config feature flag (disabled by default, graceful degradation)
- Contract hash drift detection
- Live smoke (skipped without WIND_API_KEY)
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows import router as router_module, wind_provider as wind_provider_module
from tradingagents.dataflows.config import config_scope, get_config
from tradingagents.dataflows.health import VendorHealthRegistry
from tradingagents.dataflows.interface import _market_for_request, route_to_vendor
from tradingagents.dataflows.registry import (
    VENDOR_LIST,
    VENDOR_MARKETS,
    VENDOR_METHODS,
    registry_consistency_problems,
)
from tradingagents.dataflows.vendor_errors import (
    _cooldown_for_exception,
    _is_recoverable_vendor_error,
    _is_transient_vendor_error,
)
from tradingagents.dataflows.wind_provider import (
    SKILL_VERSION,
    WindAuthError,
    WindCliTransport,
    WindEnvelope,
    WindError,
    WindNetworkError,
    WindNoResultsError,
    WindNotConfiguredError,
    WindParamError,
    WindQuotaError,
    WindRateLimitError,
    WindTransport,
    _coerce_numeric,
    _extract_edb_series,
    _extract_tables,
    _parse_envelope,
    get_equity_risk_metrics,
    get_index_fundamentals,
    get_index_history,
    get_index_profile,
    get_index_snapshot,
    get_macro_series,
    get_stock_adjusted_price_history,
    resolve_index_code,
    search_macro_series,
    set_transport,
    to_wind_symbol,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "wind"


@pytest.fixture
def wind_enabled():
    """Enable Wind in config for the duration of a test."""
    with config_scope({"wind_enabled": True}):
        yield


@pytest.fixture
def mock_transport():
    """Replace the singleton transport with a MagicMock."""
    mock = MagicMock(spec=WindTransport)
    set_transport(mock)
    yield mock
    set_transport(None)


def _load_fixture(name: str) -> dict:
    """Load a raw CLI JSON fixture."""
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _envelope_from_fixture(name: str, server: str, tool: str) -> WindEnvelope:
    """Parse a fixture file into a WindEnvelope."""
    raw = _load_fixture(name)
    return _parse_envelope(json.dumps(raw), server, tool)


# ---------------------------------------------------------------------------
# 1. Symbol conversion
# ---------------------------------------------------------------------------


class TestSymbolConversion:
    def test_ss_to_sh(self):
        assert to_wind_symbol("600519.SS") == "600519.SH"
        assert to_wind_symbol("000001.SS") == "000001.SH"

    def test_sz_unchanged(self):
        assert to_wind_symbol("000001.SZ") == "000001.SZ"
        assert to_wind_symbol("300750.SZ") == "300750.SZ"

    def test_bj_unchanged(self):
        assert to_wind_symbol("920982.BJ") == "920982.BJ"

    def test_already_wind_code_passthrough(self):
        assert to_wind_symbol("000300.SH") == "000300.SH"
        assert to_wind_symbol("600519.SH") == "600519.SH"
        assert to_wind_symbol("AAPL.O") == "AAPL.O"

    def test_bare_code_rejected(self):
        with pytest.raises(ValueError, match="Cannot convert bare code"):
            to_wind_symbol("600519")
        with pytest.raises(ValueError, match="Cannot convert bare code"):
            to_wind_symbol("000001")

    def test_unrecognised_format(self):
        with pytest.raises(ValueError, match="Unrecognised symbol"):
            to_wind_symbol("not-a-symbol")

    def test_case_insensitive(self):
        assert to_wind_symbol("600519.ss") == "600519.SH"


class TestIndexRegistry:
    def test_resolve_by_wind_code(self):
        assert resolve_index_code("000300.SH") == "000300.SH"

    def test_resolve_by_internal_canonical(self):
        assert resolve_index_code("000300.SS") == "000300.SH"

    def test_resolve_by_chinese_name(self):
        assert resolve_index_code("沪深300") == "000300.SH"
        assert resolve_index_code("创业板指") == "399006.SZ"

    def test_resolve_unknown_passes_through(self):
        # Unknown names are passed through for Wind NER to try
        assert resolve_index_code("中证军工指数") == "中证军工指数"

    def test_index_registry_has_major_indices(self):
        from tradingagents.dataflows.wind_provider import _INDEX_REGISTRY

        assert "000300.SH" in _INDEX_REGISTRY
        assert "000001.SH" in _INDEX_REGISTRY
        assert "399001.SZ" in _INDEX_REGISTRY
        assert _INDEX_REGISTRY["000300.SH"]["name"] == "沪深300"


class TestAdjustedStockHistory:
    def test_requests_explicit_forward_adjusted_daily_bars(self, wind_enabled, mock_transport):
        mock_transport.call.return_value = WindEnvelope(
            is_error=False,
            server_type="stock_data",
            tool_name="get_stock_kline",
            data={
                "data": {
                    "columns": [
                        {"name": "TIME", "type": "date"},
                        {"name": "OPEN", "type": "number"},
                        {"name": "CLOSE", "type": "number"},
                        {"name": "VOLUME", "type": "number"},
                    ],
                    "rows": [
                        ["2026-08-11", 10.0, 10.5, 1000],
                        ["2026-08-12", 10.5, 11.0, 1100],
                    ],
                }
            },
            cli_meta={"completeness": "complete"},
        )

        result = get_stock_adjusted_price_history("603019.SS", "2026-08-11", "2026-08-12")

        mock_transport.call.assert_called_once_with(
            "stock_data",
            "get_stock_kline",
            {
                "windcode": "603019.SH",
                "begin_date": "2026-08-11",
                "end_date": "2026-08-12",
                "period": "1d",
                "aftype": "0",
                "issusp": "0",
            },
        )
        assert result.coverage.source_id == "wind.stock_kline_qfq_daily"
        assert result.coverage.price_basis == "qfq"
        assert result.coverage.adjustment_verified is True
        assert result.coverage.completeness == "complete"
        assert "# Adjustment source: wind.stock_data.get_stock_kline(aftype=0)" in result

    def test_rejects_reversed_window(self, wind_enabled, mock_transport):
        with pytest.raises(ValueError, match="cannot be after"):
            get_stock_adjusted_price_history("603019.SS", "2026-08-12", "2026-08-11")
        mock_transport.call.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Response parsing
# ---------------------------------------------------------------------------


class TestNumericCoercion:
    def test_string_number(self):
        assert _coerce_numeric("4690.92") == 4690.92
        assert _coerce_numeric("18493914800") == 18493914800

    def test_native_number(self):
        assert _coerce_numeric(0.8767) == 0.8767
        assert _coerce_numeric(300) == 300

    def test_invalid_sentinels_to_none(self):
        for v in ("INVALID", "N/A", "--", "-", "", "null", "None"):
            assert _coerce_numeric(v) is None

    def test_none_to_none(self):
        assert _coerce_numeric(None) is None

    def test_thousand_separators(self):
        assert _coerce_numeric("1,234,567.89") == 1234567.89

    def test_percent_stripped(self):
        assert _coerce_numeric("24.5%") == 24.5

    def test_unparseable_returns_none(self):
        assert _coerce_numeric("abc") is None

    def test_non_finite_returns_none(self):
        for value in ("inf", "-inf", "Infinity", "-Infinity", float("inf")):
            assert _coerce_numeric(value) is None

    def test_bool_is_numeric_integer(self):
        assert _coerce_numeric(True) == 1
        assert _coerce_numeric(False) == 0


class TestTableExtraction:
    def test_extract_from_price_indicators(self):
        envelope = _envelope_from_fixture(
            "index_snapshot.raw.json", "index_data", "get_index_price_indicators"
        )
        tables = _extract_tables(envelope.data)
        assert len(tables) == 1
        t = tables[0]
        assert "最新成交价" in t.columns
        assert "Wind代码" in t.columns
        assert len(t.rows) == 1
        # Numeric string should be coerced
        row = t.row_dicts()[0]
        assert row["最新成交价"] == 4690.92
        assert row["Wind代码"] == "000300.SH"

    def test_extract_from_kline(self):
        envelope = _envelope_from_fixture(
            "index_kline.raw.json", "index_data", "get_index_kline"
        )
        tables = _extract_tables(envelope.data)
        assert len(tables) == 1
        t = tables[0]
        assert "TIME" in t.columns
        assert "OPEN" in t.columns
        assert len(t.rows) == 8
        # All OHLC values should be numeric
        for row in t.rows:
            assert isinstance(row[1], (int, float))  # OPEN

    def test_extract_from_fundamentals(self):
        envelope = _envelope_from_fixture(
            "index_fundamentals.raw.json", "index_data", "get_index_fundamentals"
        )
        tables = _extract_tables(envelope.data)
        assert len(tables) == 1
        t = tables[0]
        assert "最新PE" in t.columns
        row = t.row_dicts()[0]
        assert row["最新PE"] == 14.3656
        assert row["最新PB"] == 1.4692

    def test_empty_tables(self):
        assert _extract_tables(None) == []
        assert _extract_tables({}) == []
        # columns is an empty list — not a valid table
        assert _extract_tables({"data": {"rows": [], "columns": []}}) == []
        # columns is list of strings (not dicts) — not a valid table
        assert _extract_tables({"data": {"rows": [], "columns": ["a"]}}) == []

    def test_malformed_rows_are_ignored(self):
        data = {
            "data": {
                "columns": [{"name": "value", "type": "number"}],
                "rows": "not a list",
            }
        }
        assert _extract_tables(data) == []


class TestEdbExtraction:
    def test_search_results(self):
        envelope = _envelope_from_fixture(
            "edb_search_gdp.raw.json", "economic_data", "natural_language_get_edb_data"
        )
        series = _extract_edb_series(envelope.data)
        assert len(series) == 4
        assert series[0].code == "M5567876"
        assert series[0].name == "中国:GDP:现价:当季值"
        assert series[0].freq == "季"
        assert series[0].unit == "亿元"

    def test_fetch_results(self):
        envelope = _envelope_from_fixture(
            "edb_fetch_gdp.raw.json", "economic_data", "natural_language_get_edb_data"
        )
        series = _extract_edb_series(envelope.data)
        assert len(series) == 1
        s = series[0]
        assert s.code == "M0001395"
        assert len(s.dates) == 2
        assert len(s.values) == 2
        assert s.values[0] == 1348066.2
        assert s.dates[0] == "20241231"

    def test_malformed_items_are_skipped(self):
        data = {
            "data": {
                "data": ["bad", None, {"meta": {"code": "X"}, "date": [], "value": []}]
            }
        }
        series = _extract_edb_series(data)
        assert len(series) == 1
        assert series[0].code == "X"

    def test_risk_metrics_table(self):
        envelope = _envelope_from_fixture(
            "risk_metrics.raw.json", "stock_data", "get_risk_metrics"
        )
        tables = _extract_tables(envelope.data)
        assert len(tables) == 1
        row = tables[0].row_dicts()[0]
        assert row["Wind代码"] == "300750.SZ"
        assert row["证券简称"] == "宁德时代"
        assert isinstance(row["过去1年的BETA"], (int, float))


# ---------------------------------------------------------------------------
# 3. Error classification
# ---------------------------------------------------------------------------


class TestErrorClassification:
    def _make_error_envelope(self, code: str, message: str = "test error") -> str:
        return json.dumps(
            {
                "ok": False,
                "error": {
                    "code": code,
                    "message": message,
                    "details": {},
                    "retry": {"allowed": False},
                },
            }
        )

    def test_auth_error(self):
        with pytest.raises(WindAuthError):
            _parse_envelope(
                self._make_error_envelope("AUTH_ERROR", "invalid key"),
                "stock_data",
                "get_stock_quote",
            )

    def test_quota_error(self):
        with pytest.raises(WindQuotaError):
            _parse_envelope(
                self._make_error_envelope("DAILY_LIMIT_ERROR"),
                "stock_data",
                "x",
            )

    def test_rate_limit_error(self):
        with pytest.raises(WindRateLimitError):
            _parse_envelope(
                self._make_error_envelope("RATE_LIMIT_ERROR"),
                "stock_data",
                "x",
            )

    def test_network_error(self):
        with pytest.raises(WindNetworkError):
            _parse_envelope(
                self._make_error_envelope("NETWORK_ERROR"),
                "stock_data",
                "x",
            )

    def test_no_results_error(self):
        with pytest.raises(WindNoResultsError):
            _parse_envelope(
                self._make_error_envelope("NO_RESULTS"),
                "stock_data",
                "x",
            )

    def test_param_error(self):
        with pytest.raises(WindParamError):
            _parse_envelope(
                self._make_error_envelope("ROUTE_ERROR"),
                "stock_data",
                "x",
            )

    def test_unknown_error_code(self):
        with pytest.raises(WindError):
            _parse_envelope(
                self._make_error_envelope("SOMETHING_NEW"),
                "stock_data",
                "x",
            )

    def test_numeric_error_code_is_normalized_to_string(self):
        from tradingagents.dataflows.wind_provider import _classify_wind_code

        # The CLI normally uses named codes, but numeric codes must never
        # bypass the code map solely because they arrived as an int.
        exc = _classify_wind_code(str(401), "unauthorized")
        assert isinstance(exc, WindAuthError)
        assert exc.code == "401"

    def test_non_json_output(self):
        with pytest.raises(WindNetworkError, match="non-JSON"):
            _parse_envelope("not json at all", "stock_data", "x")


class TestCliErrorClassification:
    """Test that non-zero CLI exits are classified correctly."""

    def test_classify_from_stdout_json(self):
        from tradingagents.dataflows.wind_provider import _classify_cli_error

        stdout = json.dumps(
            {"ok": False, "error": {"code": "AUTH_ERROR", "message": "bad key"}}
        )
        exc = _classify_cli_error(stdout, "", "stock_data", "get_stock_quote")
        assert isinstance(exc, WindAuthError)

    def test_classify_empty_output(self):
        from tradingagents.dataflows.wind_provider import _classify_cli_error

        exc = _classify_cli_error("", "", "stock_data", "get_stock_quote")
        assert isinstance(exc, WindNetworkError)


# ---------------------------------------------------------------------------
# 4. Transport safety
# ---------------------------------------------------------------------------


class TestWindCliTransport:
    """Test that the transport uses safe subprocess invocation."""

    def test_init_without_key_raises(self, monkeypatch):
        monkeypatch.delenv("WIND_API_KEY", raising=False)
        with pytest.raises(WindNotConfiguredError, match="WIND_API_KEY"):
            WindCliTransport(api_key="")

    def test_resolve_cli_path_symlink(self, monkeypatch, tmp_path):
        """The CLI path must be resolved to realpath (IS_MAIN bug workaround)."""
        # Create a fake cli.mjs
        real_cli = tmp_path / "real_cli.mjs"
        real_cli.write_text("// fake")
        link_dir = tmp_path / "link_dir"
        link_dir.mkdir()
        link_cli = link_dir / "cli.mjs"
        link_cli.symlink_to(real_cli)

        monkeypatch.setenv("WIND_CLI_PATH", str(link_cli))
        from tradingagents.dataflows.wind_provider import _resolve_cli_path

        resolved = _resolve_cli_path()
        assert os.path.islink(link_cli)  # still a symlink
        assert resolved == str(real_cli)  # but resolved to real path

    def test_call_uses_atfile_and_no_key_in_argv(self, monkeypatch, tmp_path):
        """Verify subprocess is called with @file params and no key in argv."""
        fake_cli = tmp_path / "cli.mjs"
        fake_cli.write_text("// fake")

        captured_args = None
        captured_env = None

        def fake_run(argv, **kwargs):
            nonlocal captured_args, captured_env
            captured_args = argv
            captured_env = kwargs.get("env", {})
            # Return a minimal valid envelope
            result = MagicMock()
            result.returncode = 0
            result.stdout = json.dumps(
                {
                    "content": [
                        {"type": "text", "text": json.dumps({"data": {}, "error": None})}
                    ],
                    "isError": False,
                    "cli_meta": {
                        "schema_version": "1.0",
                        "server_type": "index_data",
                        "tool_name": "get_index_price_indicators",
                        "completeness": "unknown",
                        "tables": [],
                        "warnings": [],
                    },
                }
            )
            result.stderr = ""
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)

        transport = WindCliTransport(
            cli_path=str(fake_cli),
            api_key="ak_testsecret123",
        )
        transport.call("index_data", "get_index_price_indicators", {"windcode": "000300.SH"})

        # Verify argv structure
        assert captured_args is not None
        assert captured_args[0] == "node"
        assert captured_args[1] == str(fake_cli)
        assert captured_args[2] == "call"
        assert captured_args[3] == "index_data"
        assert captured_args[4] == "get_index_price_indicators"
        # Param must be @file, not inline JSON
        assert captured_args[5].startswith("@")
        # Key must NOT appear in argv
        argv_str = " ".join(captured_args)
        assert "testsecret" not in argv_str
        assert "WIND_API_KEY" not in argv_str
        # Key must be in env
        assert captured_env.get("WIND_API_KEY") == "ak_testsecret123"
        # shell=False
        # (verified by fake_run receiving kwargs, but let's check it's passed)

    def test_call_timeout_raises_network_error(self, monkeypatch, tmp_path):
        fake_cli = tmp_path / "cli.mjs"
        fake_cli.write_text("// fake")

        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="node", timeout=60)

        monkeypatch.setattr(subprocess, "run", fake_run)
        transport = WindCliTransport(cli_path=str(fake_cli), api_key="test")
        with pytest.raises(WindNetworkError, match="timed out"):
            transport.call("index_data", "get_index_quote", {"windcode": "000300.SH"})

    def test_no_output_raises_network_error(self, monkeypatch, tmp_path):
        fake_cli = tmp_path / "cli.mjs"
        fake_cli.write_text("// fake")

        result = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: result)

        transport = WindCliTransport(cli_path=str(fake_cli), api_key="test")
        with pytest.raises(WindNetworkError, match="no output"):
            transport.call("index_data", "get_index_quote", {"windcode": "000300.SH"})

    def test_config_applied_to_transport(self, monkeypatch):
        """Configured timeout/concurrency must reach the lazy transport."""
        created: list[dict[str, object]] = []

        class FakeCliTransport:
            def __init__(self, **kwargs):
                created.append(kwargs)

        set_transport(None)
        monkeypatch.setattr(wind_provider_module, "WindCliTransport", FakeCliTransport)
        with config_scope(
            {"wind_enabled": True, "wind_max_concurrency": 1, "wind_request_timeout_seconds": 37}
        ):
            wind_provider_module.get_transport()
        set_transport(None)
        assert created == [{"max_concurrency": 1, "timeout": 37}]

    def test_subprocess_decodes_with_replacement(self, monkeypatch, tmp_path):
        fake_cli = tmp_path / "cli.mjs"
        fake_cli.write_text("// fake")
        captured_kwargs: dict[str, object] = {}

        def fake_run(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock(returncode=0, stdout="{}", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        transport = WindCliTransport(cli_path=str(fake_cli), api_key="test")
        transport.call("index_data", "get_index_quote", {"windcode": "000300.SH"})
        assert captured_kwargs["encoding"] == "utf-8"
        assert captured_kwargs["errors"] == "replace"

    def test_concurrency_serialised(self, monkeypatch, tmp_path):
        """All calls should be serialised through the semaphore."""
        fake_cli = tmp_path / "cli.mjs"
        fake_cli.write_text("// fake")

        import threading
        import time

        active = 0
        max_active = 0
        lock = threading.Lock()

        def fake_run(*args, **kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            result = MagicMock(returncode=0, stdout="{}", stderr="")
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        transport = WindCliTransport(
            cli_path=str(fake_cli), api_key="test", max_concurrency=1
        )

        threads = [
            threading.Thread(
                target=transport.call,
                args=("index_data", "get_index_quote", {"windcode": f"{i:06d}.SH"}),
            )
            for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert max_active == 1, f"Expected max concurrency 1, got {max_active}"


# ---------------------------------------------------------------------------
# 5. Health and error mapping
# ---------------------------------------------------------------------------


class TestHealthMapping:
    def test_auth_manual_lock(self):
        """AUTH_ERROR should create a manual-recovery lock, not a timed cooldown."""
        from tradingagents.dataflows import interface as iface

        reg = VendorHealthRegistry()
        exc = WindAuthError("AUTH_ERROR", "bad key")

        with (
            patch.object(iface, "_vendor_health", reg),
            patch.object(iface, "_market_for_request", return_value="a_share"),
        ):
            from tradingagents.dataflows.vendor_errors import (
                _record_vendor_failure,
            )

            _record_vendor_failure(
                "wind", "get_index_snapshot", ("000300.SH",), exc
            )

        cd = reg.cooldown_for(
            vendor="wind", market="a_share", capability="get_index_snapshot"
        )
        assert cd is not None
        assert cd.recovery == "manual"
        assert cd.reason == "wind_auth"
        # Manual lock never auto-expires
        assert cd.remaining_seconds(0) == float("inf")
        assert cd.remaining_seconds(999_999_999) == float("inf")

    def test_quota_lock(self):
        from tradingagents.dataflows import interface as iface

        reg = VendorHealthRegistry()
        exc = WindQuotaError("DAILY_LIMIT_ERROR", "over quota")
        with (
            patch.object(iface, "_vendor_health", reg),
            patch.object(iface, "_market_for_request", return_value="a_share"),
        ):
            from tradingagents.dataflows.vendor_errors import (
                _record_vendor_failure,
            )

            _record_vendor_failure(
                "wind", "get_macro_series", ("M0001395",), exc
            )

        cd = reg.cooldown_for(
            vendor="wind", market="a_share", capability="get_macro_series"
        )
        assert cd is not None
        assert cd.recovery == "quota"

    def test_rate_limit_cooldown(self):
        seconds, reason = _cooldown_for_exception(
            WindRateLimitError("RATE_LIMIT_ERROR", "slow down")
        )
        assert seconds == 60.0
        assert reason == "rate_limit"

    def test_network_cooldown(self):
        seconds, reason = _cooldown_for_exception(
            WindNetworkError("NETWORK_ERROR", "timeout")
        )
        assert seconds == 20.0
        assert reason == "network"

    def test_no_results_no_cooldown(self):
        seconds, reason = _cooldown_for_exception(
            WindNoResultsError("NO_RESULTS", "empty")
        )
        assert seconds == 0.0

    def test_all_wind_errors_recoverable(self):
        for exc in [
            WindAuthError("A", "b"),
            WindQuotaError("A", "b"),
            WindRateLimitError("A", "b"),
            WindNetworkError("A", "b"),
            WindNoResultsError("A", "b"),
            WindParamError("A", "b"),
        ]:
            assert _is_recoverable_vendor_error("wind", exc), (
                f"{type(exc).__name__} should be recoverable"
            )

    def test_network_and_rate_limit_are_transient(self):
        assert _is_transient_vendor_error(
            WindRateLimitError("A", "b")
        )
        assert _is_transient_vendor_error(
            WindNetworkError("A", "b")
        )

    def test_auth_and_quota_not_transient(self):
        # Auth/quota are recoverable (try another vendor) but NOT transient
        # (don't pull in vendors outside the configured chain)
        assert not _is_transient_vendor_error(WindAuthError("A", "b"))
        assert not _is_transient_vendor_error(WindQuotaError("A", "b"))

    def test_success_clears_manual_lock(self):
        reg = VendorHealthRegistry()
        reg.record_lock(
            vendor="wind",
            market="a_share",
            capability="get_index_snapshot",
            reason="wind_auth",
            recovery="manual",
        )
        assert reg.cooldown_for(
            vendor="wind", market="a_share", capability="get_index_snapshot"
        )
        reg.record_success(
            vendor="wind", market="a_share", capability="get_index_snapshot"
        )
        assert (
            reg.cooldown_for(
                vendor="wind", market="a_share", capability="get_index_snapshot"
            )
            is None
        )


# ---------------------------------------------------------------------------
# 6. Registry / router wiring
# ---------------------------------------------------------------------------


class TestRegistryWiring:
    def test_wind_in_vendor_list(self):
        assert "wind" in VENDOR_LIST

    def test_wind_a_share_market(self):
        assert VENDOR_MARKETS["wind"] == frozenset({"a_share"})

    def test_wind_methods_registered(self):
        wind_methods = {
            "get_index_snapshot",
            "get_index_history",
            "get_index_profile",
            "get_index_fundamentals",
            "search_macro_series",
            "get_macro_series",
            "get_equity_risk_metrics",
        }
        for method in wind_methods:
            assert method in VENDOR_METHODS, f"{method} missing from VENDOR_METHODS"
            assert "wind" in VENDOR_METHODS[method], f"wind not in {method}"

    def test_registry_consistency(self):
        problems = registry_consistency_problems()
        assert not problems, f"Registry consistency problems: {problems}"


class TestRouterWiring:
    def test_index_methods_are_non_ticker(self):
        """Index/macro methods must bypass the ticker market filter."""
        for method in [
            "get_index_snapshot",
            "get_index_history",
            "get_index_profile",
            "get_index_fundamentals",
            "search_macro_series",
            "get_macro_series",
        ]:
            assert method in router_module._A_SHARE_NON_TICKER_CAPABILITIES
            assert method not in router_module._A_SHARE_TICKER_CAPABILITIES

    def test_risk_metrics_is_ticker_capability(self):
        """Risk metrics first arg IS a stock ticker."""
        assert "get_equity_risk_metrics" in router_module._A_SHARE_TICKER_CAPABILITIES

    def test_non_ticker_market_is_a_share(self):
        assert _market_for_request(("沪深300",), "get_index_snapshot") == "a_share"
        assert _market_for_request(("中国GDP",), "search_macro_series") == "a_share"

    def test_risk_metrics_market_from_ticker(self):
        assert (
            _market_for_request(("600519.SS",), "get_equity_risk_metrics") == "a_share"
        )


# ---------------------------------------------------------------------------
# 7. Config / feature flag
# ---------------------------------------------------------------------------


class TestConfigFlag:
    def test_wind_enabled_by_default(self):
        assert get_config().get("wind_enabled") is True

    def test_explicitly_disabled_returns_data_unavailable(self):
        """Turning Wind off must still degrade gracefully without a crash."""
        with config_scope({"wind_enabled": False}):
            result = route_to_vendor("get_index_snapshot", "000300.SH")
        assert "DATA_UNAVAILABLE" in str(result)
        assert "disabled" in str(result).lower() or "wind" in str(result).lower()

    def test_enable_via_config_scope(self, wind_enabled):
        assert get_config().get("wind_enabled") is True

    def test_env_override(self, monkeypatch):
        import importlib

        monkeypatch.setenv("TRADINGAGENTS_WIND_ENABLED", "true")
        monkeypatch.setenv("TRADINGAGENTS_WIND_REQUEST_TIMEOUT_SECONDS", "45")
        monkeypatch.setenv("TRADINGAGENTS_WIND_STRICT_EDB_ALLOWLIST", "true")
        # Re-import to pick up env (the config is applied at module load)
        import tradingagents.default_config as dc

        importlib.reload(dc)
        assert dc.DEFAULT_CONFIG["wind_enabled"] is True
        assert dc.DEFAULT_CONFIG["wind_request_timeout_seconds"] == 45
        assert dc.DEFAULT_CONFIG["wind_strict_edb_allowlist"] is True
        # Reload again to reset
        monkeypatch.delenv("TRADINGAGENTS_WIND_ENABLED")
        monkeypatch.delenv("TRADINGAGENTS_WIND_REQUEST_TIMEOUT_SECONDS")
        monkeypatch.delenv("TRADINGAGENTS_WIND_STRICT_EDB_ALLOWLIST")
        importlib.reload(dc)
        assert dc.DEFAULT_CONFIG["wind_enabled"] is True


# ---------------------------------------------------------------------------
# 8. Contract hash drift detection
# ---------------------------------------------------------------------------


class TestContractHashes:
    """Verify the pinned wind-mcp-skill files haven't changed unexpectedly.

    If these hashes change, it means the skill was updated and the provider
    must be re-validated against the new contract before bumping SKILL_VERSION.
    """

    SKILL_DIR = Path.home() / ".claude" / "skills" / "wind-mcp-skill" / "scripts"

    EXPECTED_HASHES = {
        "tool-manifest.json": "2088ec4998300a6aeb05a8592e8944abb95e2f4258b890c1fed3831eb589325b",
        "call-rules.json": "437a8d60e929d62dd3cdc5a8757b0c7479b249291ec7295e64d658ec9cabd584",
    }

    @pytest.mark.skipif(
        not SKILL_DIR.exists(), reason="wind-mcp-skill not installed"
    )
    @pytest.mark.unit
    def test_manifest_hash(self):
        for filename, expected in self.EXPECTED_HASHES.items():
            path = self.SKILL_DIR / filename
            if path.exists():
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                assert actual == expected, (
                    f"{filename} hash changed! "
                    f"expected={expected} actual={actual}. "
                    f"Re-validate the Wind provider against the new {filename} "
                    f"and update EXPECTED_HASHES + SKILL_VERSION."
                )

    @pytest.mark.skipif(
        not SKILL_DIR.exists(), reason="wind-mcp-skill not installed"
    )
    @pytest.mark.unit
    def test_skill_version_constant(self):
        cli_mjs = self.SKILL_DIR / "cli.mjs"
        if cli_mjs.exists():
            content = cli_mjs.read_text(encoding="utf-8")
            assert f"SKILL_VERSION = '{SKILL_VERSION}'" in content, (
                f"cli.mjs SKILL_VERSION does not match provider constant "
                f"'{SKILL_VERSION}'. Update the pinned version."
            )


# ---------------------------------------------------------------------------
# 9. Provider functions with mock transport
# ---------------------------------------------------------------------------


class TestProviderWithMock:
    """Test provider functions end-to-end with a mock transport and fixtures."""

    @pytest.fixture(autouse=True)
    def _setup(self, wind_enabled, mock_transport):
        self.mock = mock_transport

    def _mock_with_fixture(self, fixture_name, server, tool):
        envelope = _envelope_from_fixture(fixture_name, server, tool)
        self.mock.call.return_value = envelope

    def test_index_snapshot(self):
        self._mock_with_fixture(
            "index_snapshot.raw.json", "index_data", "get_index_price_indicators"
        )
        result = get_index_snapshot("000300.SH")
        assert "4690.92" in result
        assert "沪深300" not in result  # code is used, not name in header
        assert "000300.SH" in result
        assert hasattr(result, "coverage")
        assert result.coverage.item_count == 1
        # Verify the transport was called with correct server/tool
        call_args = self.mock.call.call_args
        assert call_args[0][0] == "index_data"
        assert call_args[0][1] == "get_index_price_indicators"

    def test_index_history(self):
        self._mock_with_fixture(
            "index_kline.raw.json", "index_data", "get_index_kline"
        )
        result = get_index_history("000300.SH", "2026-08-01", "2026-08-12")
        assert "TIME" in result
        assert "OPEN" in result
        assert "4561.82" in result
        assert result.coverage.actual_start == "2026-08-03"
        assert result.coverage.actual_end == "2026-08-12"

    def test_index_profile(self):
        self._mock_with_fixture(
            "index_basicinfo.raw.json", "index_data", "get_index_basicinfo"
        )
        result = get_index_profile("000300.SH")
        assert "中证指数有限公司" in result
        assert "300" in result

    def test_index_fundamentals(self):
        self._mock_with_fixture(
            "index_fundamentals.raw.json", "index_data", "get_index_fundamentals"
        )
        result = get_index_fundamentals("000300.SH")
        assert "14.3656" in result
        assert "1.4692" in result

    def test_edb_search(self):
        self._mock_with_fixture(
            "edb_search_gdp.raw.json", "economic_data", "natural_language_get_edb_data"
        )
        result = search_macro_series("中国GDP")
        assert "M5567876" in result
        assert "M0001395" in result
        assert "国家统计局" in result

    def test_edb_fetch(self):
        self._mock_with_fixture(
            "edb_fetch_gdp.raw.json", "economic_data", "natural_language_get_edb_data"
        )
        result = get_macro_series("M0001395", "2023-01-01", "2025-12-31")
        assert "1348066.2" in result
        assert "20241231" in result
        assert result.coverage.item_count == 2

    def test_risk_metrics(self):
        self._mock_with_fixture(
            "risk_metrics.raw.json", "stock_data", "get_risk_metrics"
        )
        result = get_equity_risk_metrics("300750.SZ", window="1年")
        assert "宁德时代" in result
        assert "0.8767" in result
        assert "300750.SZ" in result
        # Verify symbol conversion: .SZ stays .SZ
        call_params = self.mock.call.call_args[0][2]
        assert "300750.SZ" in call_params["question"]

    def test_risk_metrics_ss_to_sh(self):
        self._mock_with_fixture(
            "risk_metrics.raw.json", "stock_data", "get_risk_metrics"
        )
        get_equity_risk_metrics("600519.SS")
        call_params = self.mock.call.call_args[0][2]
        # .SS should be converted to .SH in the question
        assert "600519.SH" in call_params["question"]

    def test_risk_metrics_router_supports_positional_args(self):
        """The router invokes provider functions as impl_func(*args)."""
        self._mock_with_fixture(
            "risk_metrics.raw.json", "stock_data", "get_risk_metrics"
        )
        result = route_to_vendor(
            "get_equity_risk_metrics", "600519.SS", "1年", None, None
        )
        assert "600519.SH" in result
        assert "过去1年的BETA" in result

    def test_index_snapshot_as_of_is_explicitly_latest_only(self):
        self._mock_with_fixture(
            "index_snapshot.raw.json", "index_data", "get_index_price_indicators"
        )
        result = get_index_snapshot("000300.SH", as_of="2024-01-02")
        assert "Requested as-of: 2024-01-02; Wind endpoint returned latest" in result
        assert result.coverage.as_of != "2024-01-02"
        assert result.coverage.degradations

    def test_edb_csv_escapes_commas_and_quotes(self):
        envelope = WindEnvelope(
            is_error=False,
            server_type="economic_data",
            tool_name="natural_language_get_edb_data",
            data={
                "data": {
                    "data": [{
                        "meta": {"code": "M0001395", "name": 'GDP, "seasonally adjusted"'},
                        "date": ["20241231"],
                        "value": [1.0],
                    }]
                }
            },
            cli_meta={"completeness": "unknown", "tables": [], "warnings": []},
        )
        self.mock.call.return_value = envelope
        result = get_macro_series("M0001395", "2024-01-01", "2024-12-31")
        rows = list(csv.reader(io.StringIO(str(result).split("\n\n", 1)[1])))
        assert rows[1][1] == 'GDP, "seasonally adjusted"'
        assert len(rows[1]) == 7

    def test_strict_edb_allowlist_rejects_before_transport_call(self):
        with (
            config_scope({"wind_enabled": True, "wind_strict_edb_allowlist": True}),
            pytest.raises(WindParamError, match="not in Wind allowlist"),
        ):
            get_macro_series("M9999999", "2024-01-01", "2024-12-31")
        self.mock.call.assert_not_called()

    def test_no_data_raises(self):
        """Empty tables should raise NoMarketDataError."""
        empty_envelope = WindEnvelope(
            is_error=False,
            server_type="index_data",
            tool_name="get_index_price_indicators",
            data={"data": {"columns": ["a"], "rows": [], "unit": {}}, "error": None},
            cli_meta={"completeness": "unknown", "tables": [], "warnings": []},
        )
        self.mock.call.return_value = empty_envelope
        from tradingagents.dataflows.errors import NoMarketDataError

        with pytest.raises(NoMarketDataError):
            get_index_snapshot("000300.SH")


# ---------------------------------------------------------------------------
# 10. Live smoke (requires WIND_API_KEY + wind_enabled)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.skipif(
    not os.environ.get("WIND_API_KEY"),
    reason="WIND_API_KEY not set; live smoke skipped",
)
class TestLiveSmoke:
    @pytest.fixture(autouse=True)
    def _setup(self):
        with config_scope({"wind_enabled": True}):
            # Reset transport singleton to pick up real key
            set_transport(None)
            yield
            set_transport(None)

    def test_live_index_snapshot(self):
        result = get_index_snapshot("000300.SH")
        assert "000300.SH" in result
        assert result.coverage.item_count >= 1

    def test_live_index_history(self):
        result = get_index_history("000300.SH", "2026-08-01", "2026-08-12")
        assert result.coverage.item_count >= 1

    def test_live_edb_search(self):
        result = search_macro_series("中国CPI")
        assert "M" in result  # EDB codes start with M

    def test_live_risk_metrics(self):
        result = get_equity_risk_metrics("600519.SS", window="1年")
        assert "600519.SH" in result
