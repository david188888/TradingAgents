from __future__ import annotations

import pytest
import requests

from tradingagents.dataflows.errors import VendorAccessDeniedError, VendorNotConfiguredError
from tradingagents.dataflows.vendor_errors import public_vendor_reason_code
from tradingagents.dataflows.wind_provider import (
    WindAuthError,
    WindNetworkError,
    WindQuotaError,
    WindRateLimitError,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (WindAuthError("AUTH_ERROR"), "provider_auth_failed"),
        (WindQuotaError("DAILY_LIMIT_ERROR"), "provider_quota_exhausted"),
        (WindRateLimitError("RATE_LIMIT_ERROR"), "provider_rate_limited"),
        (WindNetworkError("NETWORK_ERROR"), "provider_network_failed"),
        (VendorAccessDeniedError("eastmoney", 403), "provider_access_denied"),
        (VendorNotConfiguredError("missing token"), "provider_not_configured"),
        (ValueError("invalid date"), "provider_invalid_request"),
    ],
)
def test_public_vendor_reason_code_is_stable(error, expected):
    assert public_vendor_reason_code(error) == expected


@pytest.mark.unit
def test_public_vendor_reason_code_detects_legacy_permission_and_proxy_messages():
    assert public_vendor_reason_code(Exception("您没有接口(balancesheet)访问权限")) == "provider_access_denied"
    assert public_vendor_reason_code(requests.exceptions.ProxyError("proxy connection failed")) == "provider_network_failed"
