import re
import time
from datetime import date, datetime, timedelta
from typing import Annotated

import pandas as pd
import requests

SavePathType = Annotated[str, "File path to save data. If None, data is not saved."]

# Tickers can contain letters, digits, dot, dash, underscore, caret
# (index symbols like ^GSPC), equals (futures like GC=F), and plus
# (forex/CFD symbols like XAUUSD+). None of these enable directory
# traversal, so the value never escapes a containing directory when
# interpolated into a path. Anything else is rejected.
_TICKER_PATH_RE = re.compile(r"^[A-Za-z0-9._\-\^=+]+$")


def safe_ticker_component(value: str, *, max_len: int = 32) -> str:
    """Validate ``value`` is safe to interpolate into a filesystem path.

    Tickers come from user CLI input or from LLM tool calls, both of which
    can be influenced by attacker-controlled content (e.g. prompt injection
    embedded in fetched news). Without validation, a value like
    ``"../../../etc/foo"`` flows into ``os.path.join`` / ``Path /`` and
    escapes the configured cache, checkpoint, or results directory.

    Returns ``value`` unchanged when it matches the allowed pattern; raises
    ``ValueError`` otherwise.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"ticker must be a non-empty string, got {value!r}")
    if len(value) > max_len:
        raise ValueError(f"ticker exceeds {max_len} chars: {value!r}")
    if not _TICKER_PATH_RE.fullmatch(value):
        raise ValueError(
            f"ticker contains characters not allowed in a filesystem path: {value!r}"
        )
    # The regex above allows '.', so values like '.', '..', '...' would pass,
    # and as a path component they traverse the parent directory. Reject any
    # value that's only dots.
    if set(value) == {"."}:
        raise ValueError(f"ticker cannot consist solely of dots: {value!r}")
    return value


def save_output(data: pd.DataFrame, tag: str, save_path: SavePathType = None) -> None:
    if save_path:
        data.to_csv(save_path, encoding="utf-8")
        print(f"{tag} saved to {save_path}")


def get_current_date():
    return date.today().strftime("%Y-%m-%d")


def get_scrubbed(
    url: str,
    *,
    params: dict,
    timeout: float,
    secret: str,
    passthrough: tuple[int, ...] = (),
):
    """GET a URL without retaining a query-string secret in request errors.

    ``requests`` includes the full prepared URL in HTTP and transport errors.
    Providers that authenticate through query parameters would therefore leak
    their API key into logs or tracebacks. Re-raise the same exception class
    with a scrubbed message and without attached request/response objects. The
    final raise stays outside the ``except`` block so the original exception is
    not retained as ``__context__``.
    """
    response = None
    try:
        response = requests.get(url, params=params, timeout=timeout)
        if response.status_code not in passthrough:
            response.raise_for_status()
        return response
    except requests.RequestException as exc:
        message = str(exc).replace(secret, "***") if secret else str(exc)
        error = type(exc)(message)
        # Keep the status code as plain data. The router classifies throttles and
        # access denials from it, and re-attaching the original response would
        # re-expose the secret-bearing URL through the object graph.
        status_code = getattr(response, "status_code", None)
        if not isinstance(status_code, int):
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if isinstance(status_code, int):
            error.status_code = status_code
    raise error


# How long a reachability verdict is reused. A batch analysis over many symbols
# asks the same question repeatedly; without reuse a provider outage would cost
# one probe (and one timeout) per empty result.
REACHABILITY_TTL_SECONDS = 60.0

# url -> (monotonic timestamp, reachable). Process-lived on purpose: the probe
# answers "is the vendor answering right now", which is a property of the run,
# not of the request.
_REACHABILITY_CACHE: dict[str, tuple[float, bool]] = {}


def vendor_reachable(
    url: str,
    timeout: float = 5.0,
    *,
    ttl_seconds: float | None = None,
) -> bool:
    """Whether a vendor host answers at all, for telling silence from an outage.

    Some clients (notably yfinance) return an empty result instead of raising
    when a request fails, which makes "the vendor is down" and "this symbol has
    no data" indistinguishable. Probe only when a result is empty, never on a
    successful path.

    Only a transport failure (DNS, TCP, TLS, timeout) counts as unreachable: any
    HTTP answer proves the host is alive, so a 403/404/429 from the probe is
    reported as reachable rather than misread as an outage. The probe therefore
    separates "the host does not answer at all" from silence, and nothing finer.

    The verdict is cached for ``REACHABILITY_TTL_SECONDS`` so a batch run does
    not send one probe per empty symbol. Pass ``ttl_seconds=0`` to force a fresh
    probe. A probe that fails is reported as unreachable, so the caller's
    fallback favors "vendor failure" over an unproven "no data" claim.
    """
    ttl = REACHABILITY_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    now = time.monotonic()
    cached = _REACHABILITY_CACHE.get(url)
    if cached is not None and now - cached[0] < ttl:
        return cached[1]

    try:
        requests.head(url, timeout=timeout, allow_redirects=True)
        reachable = True
    except requests.RequestException:
        reachable = False

    _REACHABILITY_CACHE[url] = (now, reachable)
    return reachable


def decorate_all_methods(decorator):
    def class_decorator(cls):
        for attr_name, attr_value in cls.__dict__.items():
            if callable(attr_value):
                setattr(cls, attr_name, decorator(attr_value))
        return cls

    return class_decorator


def get_next_weekday(date):

    if not isinstance(date, datetime):
        date = datetime.strptime(date, "%Y-%m-%d")

    if date.weekday() >= 5:
        days_to_add = 7 - date.weekday()
        next_weekday = date + timedelta(days=days_to_add)
        return next_weekday
    else:
        return date
