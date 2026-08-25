"""The vendor data-error hierarchy: every "vendor couldn't return usable data"
condition derives from VendorError, so the router catches base types and any
vendor slots in without new handling.
"""
import copy
import unittest
from unittest import mock

import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.alpha_vantage_common import (
    AlphaVantageNotConfiguredError,
    AlphaVantageRateLimitError,
)
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    RateLimitError,
    VendorAccessDeniedError,
    VendorError,
    VendorHTTPError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)
from tradingagents.dataflows.fred import FredNotConfiguredError


@pytest.mark.unit
class HierarchyTests(unittest.TestCase):
    def test_all_conditions_derive_from_vendor_error(self):
        for cls in (
            NoMarketDataError,
            VendorRateLimitError,
            RateLimitError,
            VendorHTTPError,
            VendorAccessDeniedError,
            VendorNotConfiguredError,
        ):
            self.assertTrue(issubclass(cls, VendorError))

    def test_not_configured_is_still_a_value_error(self):
        # Back-compat: existing `except ValueError` callers keep working.
        self.assertTrue(issubclass(VendorNotConfiguredError, ValueError))

    def test_vendor_named_errors_subclass_the_generic_bases(self):
        self.assertTrue(issubclass(AlphaVantageRateLimitError, VendorRateLimitError))
        self.assertTrue(issubclass(AlphaVantageNotConfiguredError, VendorNotConfiguredError))
        self.assertTrue(issubclass(FredNotConfiguredError, VendorNotConfiguredError))
        # ... and therefore still ValueErrors
        self.assertTrue(issubclass(FredNotConfiguredError, ValueError))

    def test_symbol_utils_reexports_no_market_data_error(self):
        from tradingagents.dataflows.symbol_utils import (
            NoMarketDataError as ReExported,
        )
        self.assertIs(ReExported, NoMarketDataError)


@pytest.mark.unit
class RouterHandlesBaseTypesTests(unittest.TestCase):
    def setUp(self):
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)

    def tearDown(self):
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)

    def test_rate_limit_subclass_caught_by_base(self):
        # A vendor-named rate-limit error skips to the next vendor in the chain.
        set_config({"data_vendors": {"core_stock_apis": "alpha_vantage,yfinance"}})

        def _throttled(*a, **k):
            raise AlphaVantageRateLimitError("slow down")

        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": {"alpha_vantage": _throttled, "yfinance": lambda *a, **k: "YF"}},
            clear=False,
        ):
            out = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(out, "YF")

    def test_not_configured_falls_through_to_next_vendor(self):
        set_config({"data_vendors": {"core_stock_apis": "alpha_vantage,yfinance"}})

        def _unconfigured(*a, **k):
            raise AlphaVantageNotConfiguredError("no key")

        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": {"alpha_vantage": _unconfigured, "yfinance": lambda *a, **k: "YF"}},
            clear=False,
        ):
            out = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(out, "YF")

    def test_sole_unconfigured_vendor_surfaces_the_error(self):
        # With no fallback, the not-configured condition must surface (not vanish).
        set_config({"data_vendors": {"core_stock_apis": "alpha_vantage"}})

        def _unconfigured(*a, **k):
            raise AlphaVantageNotConfiguredError("no key")

        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": {"alpha_vantage": _unconfigured}},
            clear=False,
        ), self.assertRaises(AlphaVantageNotConfiguredError):
            interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")


@pytest.mark.unit
class RateLimitSignalTests(unittest.TestCase):
    """Wrapped exceptions must not lose the rate-limit signal.

    tushare reports quota exhaustion as a plain-text message and the china
    adapters wrap everything in ChinaDataUnavailableError; without signal
    preservation the cooldown table stayed at 0s and retries hammered the
    throttled provider.
    """

    def test_tushare_throttle_text_maps_to_rate_limit_cooldown(self):
        from tradingagents.dataflows.china_data import ChinaDataUnavailableError
        from tradingagents.dataflows.health import RATE_LIMIT_COOLDOWN_SECONDS
        from tradingagents.dataflows.vendor_errors import _cooldown_for_exception

        wrapped = ChinaDataUnavailableError(
            "Tushare daily request failed for 600519.SH: 抱歉，您每分钟最多访问该接口1次"
        )
        seconds, reason = _cooldown_for_exception(wrapped)
        self.assertEqual(seconds, RATE_LIMIT_COOLDOWN_SECONDS)
        self.assertEqual(reason, "rate_limit")

    def test_wrapped_429_cause_chain_maps_to_rate_limit_cooldown(self):
        import requests as _requests

        from tradingagents.dataflows.china_data import ChinaDataUnavailableError
        from tradingagents.dataflows.health import RATE_LIMIT_COOLDOWN_SECONDS
        from tradingagents.dataflows.vendor_errors import _cooldown_for_exception

        http_429 = _requests.HTTPError("429 Client Error: Too Many Requests")
        http_429.response = _requests.Response()
        http_429.response.status_code = 429
        wrapped = ChinaDataUnavailableError("Tushare qfq request failed")
        wrapped.__cause__ = http_429
        seconds, reason = _cooldown_for_exception(wrapped)
        self.assertEqual(seconds, RATE_LIMIT_COOLDOWN_SECONDS)
        self.assertEqual(reason, "rate_limit")

    def test_plain_china_unavailable_stays_uncooled(self):
        from tradingagents.dataflows.china_data import ChinaDataUnavailableError
        from tradingagents.dataflows.vendor_errors import _cooldown_for_exception

        seconds, _reason = _cooldown_for_exception(
            ChinaDataUnavailableError("Tushare returned no daily data for 600519.SH.")
        )
        self.assertEqual(seconds, 0.0)


if __name__ == "__main__":
    unittest.main()
