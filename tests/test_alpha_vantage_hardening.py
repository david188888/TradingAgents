"""Alpha Vantage request hardening.

Regressions for #990 (no request timeout -> can hang), #991 (invalid-key
responses mislabeled as rate limits and silently treated as transient), and
#1115 (fundamentals look-ahead filter never ran because the payload is a JSON
string, not a dict).
"""
import json

import pytest
import requests

import tradingagents.dataflows.alpha_vantage_common as av
import tradingagents.dataflows.alpha_vantage_fundamentals as avf
import tradingagents.dataflows.alpha_vantage_news as avn
import tradingagents.dataflows.alpha_vantage_stock as avs
from tradingagents.dataflows.errors import VendorRequestError


class _FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def _patched_get(body, capture=None):
    def fake_get(url, params=None, **kwargs):
        if capture is not None:
            capture.update(kwargs)
        return _FakeResponse(body)
    return fake_get


@pytest.mark.unit
def test_request_passes_timeout(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        requests,
        "get",
        _patched_get("Date,Close\n2025-01-02,1.0", captured),
    )
    av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})
    assert captured.get("timeout") == av.REQUEST_TIMEOUT  # #990


@pytest.mark.unit
def test_rate_limit_detected(monkeypatch):
    body = '{"Information": "Our standard API rate limit is 25 requests per day. ... your API key ..."}'
    monkeypatch.setattr(requests, "get", _patched_get(body))
    with pytest.raises(av.AlphaVantageRateLimitError):
        av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})


@pytest.mark.unit
def test_invalid_key_not_mislabeled_as_rate_limit(monkeypatch):
    # AV's invalid-key notice mentions "API key"; it must NOT be treated as a
    # (transient) rate limit, but surface as a real configuration error (#991).
    body = ('{"Information": "the parameter apikey is invalid or missing. '
            'Please claim your free API key on (https://www.alphavantage.co/support/#api-key)."}')
    monkeypatch.setattr(requests, "get", _patched_get(body))
    with pytest.raises(av.AlphaVantageNotConfiguredError):
        av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})
    with pytest.raises(av.AlphaVantageRateLimitError):  # sanity: rate-limit path still distinct
        monkeypatch.setattr(
            requests,
            "get",
            _patched_get('{"Note": "API call frequency is 5 calls per minute."}'),
        )
        av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})


_FUNDAMENTALS_JSON = json.dumps({
    "symbol": "AAPL",
    "annualReports": [
        {"fiscalDateEnding": "2025-12-31", "totalAssets": "1"},   # future -> must drop
        {"fiscalDateEnding": "2023-12-31", "totalAssets": "2"},   # past   -> must keep
    ],
    "quarterlyReports": [
        {"fiscalDateEnding": "2024-06-30", "totalAssets": "3"},   # future -> must drop
        {"fiscalDateEnding": "2023-09-30", "totalAssets": "4"},   # past   -> must keep
    ],
})


@pytest.mark.unit
def test_fundamentals_look_ahead_filter_runs_on_json_string(monkeypatch):
    # #1115: the payload arrives as a JSON *string*; the old dict-only guard let
    # future-dated fiscal periods leak into historical runs.
    monkeypatch.setattr(avf, "_make_api_request", lambda fn, params: _FUNDAMENTALS_JSON)
    out = avf.get_balance_sheet("AAPL", curr_date="2024-01-01")
    assert isinstance(out, str)  # callers still receive a str
    parsed = json.loads(out)
    assert [r["fiscalDateEnding"] for r in parsed["annualReports"]] == ["2023-12-31"]
    assert [r["fiscalDateEnding"] for r in parsed["quarterlyReports"]] == ["2023-09-30"]


@pytest.mark.unit
def test_fundamentals_no_curr_date_passes_through(monkeypatch):
    monkeypatch.setattr(avf, "_make_api_request", lambda fn, params: _FUNDAMENTALS_JSON)
    assert avf.get_income_statement("AAPL") == _FUNDAMENTALS_JSON


@pytest.mark.unit
def test_fundamentals_non_json_body_unchanged(monkeypatch):
    monkeypatch.setattr(avf, "_make_api_request", lambda fn, params: "not-json")
    assert avf.get_cashflow("AAPL", curr_date="2024-01-01") == "not-json"


_DAILY_CSV = (
    "timestamp,open,high,low,close,volume\n"
    "2024-05-13,1,1,1,1,10\n"
    "2024-05-10,1,1,1,1,10\n"
    "2024-05-09,1,1,1,1,10\n"
)


@pytest.mark.unit
def test_stock_data_is_trimmed_to_requested_window(monkeypatch):
    monkeypatch.setattr(avs, "_make_api_request", lambda *args, **kwargs: _DAILY_CSV)

    out = avs.get_stock("IBM", "2024-05-09", "2024-05-10")

    assert "2024-05-13" not in out
    assert "2024-05-10" in out and "2024-05-09" in out


@pytest.mark.unit
def test_unparseable_body_is_never_served_untrimmed(monkeypatch):
    monkeypatch.setattr(
        avs,
        "_make_api_request",
        lambda *args, **kwargs: "timestamp,close\nnot-a-date,1\n",
    )

    with pytest.raises(ValueError):
        avs.get_stock("IBM", "2024-05-09", "2024-05-10")


@pytest.mark.unit
def test_empty_body_still_passes_through(monkeypatch):
    monkeypatch.setattr(avs, "_make_api_request", lambda *args, **kwargs: "")

    assert avs.get_stock("IBM", "2024-05-09", "2024-05-10") == ""


@pytest.mark.unit
def test_request_error_message_carries_no_api_key(monkeypatch):
    key = "AVKEY1234567890XYZ"
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", key)

    def boom(*args, **kwargs):
        raise requests.Timeout(
            "Read timed out. url: "
            f"https://www.alphavantage.co/query?function=OVERVIEW&apikey={key}"
        )

    monkeypatch.setattr(requests, "get", boom)

    with pytest.raises(requests.Timeout) as caught:
        av._make_api_request("OVERVIEW", {"symbol": "IBM"})

    assert key not in str(caught.value)
    assert key not in repr(caught.value)
    assert caught.value.request is None
    assert caught.value.response is None
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


# --- Failure semantics: a failure must not reach the router as an answer -----


@pytest.mark.unit
def test_indicator_this_vendor_cannot_serve_lets_the_next_one_serve_it():
    """VWMA has no Alpha Vantage endpoint.

    The explanatory prose it used to return counted as a successful answer, so
    the fallback chain stopped at a vendor that cannot compute the indicator
    while the next vendor can.
    """
    import tradingagents.dataflows.alpha_vantage_indicator as avi
    from tradingagents.dataflows.errors import VendorRequestError

    with pytest.raises(VendorRequestError):
        avi.get_indicator("AAPL", "vwma", "2026-05-08", 30)


@pytest.mark.unit
def test_indicator_transport_failure_raises_instead_of_returning_error_text(monkeypatch):
    import tradingagents.dataflows.alpha_vantage_indicator as avi
    from tradingagents.dataflows.errors import VendorError

    def boom(*args, **kwargs):
        raise RuntimeError("alpha vantage exploded")

    monkeypatch.setattr(avi, "_make_api_request", boom)

    with pytest.raises(VendorError) as caught:
        avi.get_indicator("AAPL", "rsi", "2026-05-08", 30)

    assert "Error retrieving" not in str(caught.value)


# --- News windows: the analysis day belongs inside the window ---------------


@pytest.mark.unit
def test_ticker_news_window_includes_the_analysis_day(monkeypatch):
    """A plain date means midnight *starting* that day, so it was excluded."""
    seen: dict = {}
    monkeypatch.setattr(
        avn, "_make_api_request", lambda function, params: seen.update(params) or "{}"
    )

    avn.get_news("AAPL", "2026-03-10", "2026-03-14")

    assert seen["time_from"] == "20260310T0000"
    assert seen["time_to"] == "20260314T2359"


@pytest.mark.unit
def test_global_news_window_includes_the_current_day(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        avn, "_make_api_request", lambda function, params: seen.update(params) or "{}"
    )

    avn.get_global_news("2026-03-14", look_back_days=7)

    assert seen["time_from"] == "20260307T0000"
    assert seen["time_to"] == "20260314T2359"


@pytest.mark.unit
def test_plain_date_still_means_midnight_by_default():
    """The window start, and every other caller, keep the old meaning."""
    assert av.format_datetime_for_api("2026-03-14") == "20260314T0000"
    assert av.format_datetime_for_api("2026-03-14", end_of_day=True) == "20260314T2359"
    # Already-formatted and datetime inputs are untouched by the flag.
    assert av.format_datetime_for_api("20260314T1200") == "20260314T1200"
    from datetime import datetime

    assert av.format_datetime_for_api(datetime(2026, 3, 14, 8, 30)) == "20260314T0830"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        # An unrecognised Information/Note body is a vendor failure, not data.
        ("Information: the RSI endpoint is temporarily unavailable", VendorRequestError),
        ("", VendorRequestError),
        # A usable-looking CSV whose shape does not match the indicator.
        ("time,other\n2026-05-01,1\n", VendorRequestError),
    ],
    ids=["unrecognised-body", "empty-body", "missing-column"],
)
def test_indicator_payload_failures_never_return_as_report_text(monkeypatch, payload, expected):
    """A returned "Error: ..." string counted as a successful answer.

    The router classifies returned text as data, so the fallback chain stopped at
    a vendor that could not answer while the next vendor could.
    """
    import tradingagents.dataflows.alpha_vantage_indicator as avi
    from tradingagents.dataflows.errors import VendorRequestError

    monkeypatch.setattr(avi, "_make_api_request", lambda *a, **k: payload)

    with pytest.raises(VendorRequestError):
        avi.get_indicator("AAPL", "rsi", "2026-05-08", 30)


@pytest.mark.unit
def test_indicator_window_without_rows_is_no_data_not_a_report(monkeypatch):
    """The vendor answered and had no rows in the window; another vendor may."""
    import tradingagents.dataflows.alpha_vantage_indicator as avi
    from tradingagents.dataflows.errors import NoMarketDataError

    monkeypatch.setattr(avi, "_make_api_request", lambda *a, **k: "time,RSI\n2026-01-02,50\n")

    with pytest.raises(NoMarketDataError):
        avi.get_indicator("AAPL", "rsi", "2026-05-08", 30)


@pytest.mark.unit
def test_scrubbed_http_error_keeps_its_status_code_without_the_response(monkeypatch):
    """Scrubbing must not cost the router its rate-limit signal.

    ``requests`` quotes the URL in HTTP errors, so the exception is rebuilt with
    a scrubbed message and no attached request/response. The status code is what
    the router uses to pick a cooldown, so it is carried over as plain data.
    """
    from tradingagents.dataflows import utils as flow_utils
    from tradingagents.dataflows.health import RATE_LIMIT_COOLDOWN_SECONDS
    from tradingagents.dataflows.vendor_errors import _cooldown_for_exception

    key = "AVKEY1234567890XYZ"
    url = f"https://www.alphavantage.co/query?function=OVERVIEW&apikey={key}"

    class FakeResponse:
        status_code = 429

        def raise_for_status(self):
            raise requests.HTTPError(f"429 Client Error: Too Many Requests for url: {url}")

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())

    with pytest.raises(requests.HTTPError) as caught:
        flow_utils.get_scrubbed(url, params={}, timeout=5.0, secret=key)

    assert key not in str(caught.value)
    assert caught.value.request is None
    assert caught.value.response is None
    assert caught.value.status_code == 429
    assert _cooldown_for_exception(caught.value) == (
        RATE_LIMIT_COOLDOWN_SECONDS,
        "rate_limit",
    )
