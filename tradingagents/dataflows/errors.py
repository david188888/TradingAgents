"""Typed failures raised by source adapters."""

from __future__ import annotations


class ChinaDataUnavailableError(Exception):
    """An A-share source could not supply usable data."""


class VendorError(Exception):
    """Base for any condition where a vendor could not return usable data."""


class NoMarketDataError(VendorError):
    """A vendor returned no usable rows for a symbol (empty result or stale data).

    Carries both the symbol the user requested and the canonical symbol the
    vendor was actually queried with, plus a free-text ``detail``, so callers
    can build a clear message instead of emitting a vendor-specific empty
    string into the data channel.
    """

    def __init__(self, symbol: str, canonical: str | None = None, detail: str = ""):
        self.symbol = symbol
        self.canonical = canonical or symbol
        self.detail = detail
        msg = f"No market data for {symbol!r}"
        if canonical and canonical != symbol:
            msg += f" (queried as {canonical!r})"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


class VendorRateLimitError(VendorError):
    """A vendor throttled the request."""


class RateLimitError(VendorRateLimitError):
    """A direct HTTP source throttled the request."""


class VendorHTTPError(VendorError):
    """A provider returned a non-success HTTP response.

    ``status_code`` is structured so retry and circuit-breaker policy does not
    have to parse a vendor's human-readable response body.
    """

    def __init__(self, provider: str, status_code: int, detail: str = "") -> None:
        self.provider = provider
        self.status_code = status_code
        self.detail = detail
        message = f"{provider} HTTP {status_code}"
        if detail:
            message += f": {detail}"
        super().__init__(message)


class VendorAccessDeniedError(VendorHTTPError):
    """A provider denied access (403); retrying would be unsafe and pointless."""


class VendorNotConfiguredError(VendorError, ValueError):
    """A vendor was selected but its API key/configuration is missing.

    Also a ``ValueError`` for callers that handle configuration errors.
    """
