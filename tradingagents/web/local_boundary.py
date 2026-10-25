"""Shared Host and Origin boundary for the loopback-only workbench."""

from urllib.parse import urlsplit


def is_local_request(request) -> bool:
    try:
        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return False
        expected = (
            request.url.scheme, host,
            request.url.port or (443 if request.url.scheme == "https" else 80),
        )
        origin = request.headers.get("origin")
        if origin is None:
            # Local API clients do not send Origin. Browsers do on mutations.
            return True
        parsed = urlsplit(origin)
        return (
            parsed.scheme, parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
        ) == expected
    except ValueError:
        return False
