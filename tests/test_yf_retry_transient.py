"""yf_retry transient transport retry behaviour (#TLS retry)."""

import time

import pytest
from curl_cffi.requests.exceptions import (
    CertificateVerifyError,
    ConnectionError,
    SSLError,
    Timeout,
)
from yfinance.exceptions import YFRateLimitError

from tradingagents.dataflows.stockstats_utils import yf_retry


class _CallCounter:
    """Helper that raises a given exception the first ``failures`` times."""

    def __init__(self, exc, failures=1, result="ok"):
        self.exc = exc
        self.failures = failures
        self.calls = 0
        self.result = result

    def __call__(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc
        return self.result


@pytest.mark.parametrize(
    "exc_type",
    [
        ConnectionError("Failed to connect"),
        SSLError("TLS connect error"),
        Timeout("timed out"),
    ],
)
def test_yf_retry_retries_transient_curl_errors(exc_type):
    counter = _CallCounter(exc_type, failures=1)
    result = yf_retry(counter, max_retries=2, base_delay=0.01)
    assert result == "ok"
    assert counter.calls == 2


def test_yf_retry_gives_up_after_max_retries_on_transient_error():
    counter = _CallCounter(SSLError("still failing"), failures=99)
    with pytest.raises(SSLError):
        yf_retry(counter, max_retries=2, base_delay=0.01)
    assert counter.calls == 3  # initial + 2 retries


def test_yf_retry_does_not_retry_certificate_verification_error():
    counter = _CallCounter(CertificateVerifyError("bad cert"), failures=99)
    with pytest.raises(CertificateVerifyError):
        yf_retry(counter, max_retries=2, base_delay=0.01)
    assert counter.calls == 1  # never retried


def test_yf_retry_still_retries_rate_limit():
    counter = _CallCounter(YFRateLimitError(), failures=1)
    result = yf_retry(counter, max_retries=2, base_delay=0.01)
    assert result == "ok"
    assert counter.calls == 2


def test_yf_retry_propagates_unknown_errors_immediately():
    counter = _CallCounter(ValueError("unexpected"), failures=99)
    with pytest.raises(ValueError):
        yf_retry(counter, max_retries=2, base_delay=0.01)
    assert counter.calls == 1


def test_yf_retry_uses_exponential_backoff():
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)

    counter = _CallCounter(ConnectionError("flaky"), failures=99)
    original_sleep = time.sleep
    time.sleep = fake_sleep
    try:
        with pytest.raises(ConnectionError):
            yf_retry(counter, max_retries=3, base_delay=2.0)
    finally:
        time.sleep = original_sleep
    assert sleeps == [2.0, 4.0, 8.0]
