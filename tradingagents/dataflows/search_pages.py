"""Bounded original-page retrieval and IP-pinned public document downloads."""

import http.client
import ipaddress
import os
import socket
import ssl
from contextlib import contextmanager
from urllib.parse import parse_qsl, urljoin, urlsplit

from tradingagents.agents.schemas._search import SearchHitV1, SearchOutcomeV1
from tradingagents.dataflows.catalyst_transport import _DATA_SLOTS
from tradingagents.dataflows.disclosure_documents import MAX_PDF_BYTES
from tradingagents.dataflows.search_transport import request_json
from tradingagents.dataflows.tavily_search import configured_keys


def validate_public_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('unsafe public URL')
    if parsed.port not in (None, 80, 443):
        raise ValueError('unsupported public port')
    if any(any(part in key.lower() for part in ('token', 'secret', 'key', 'signature', 'auth'))
           for key, _ in parse_qsl(parsed.query)):
        raise ValueError('credential-shaped URL')
    host = parsed.hostname
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        addresses = [r[4][0] for r in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)]
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError('nonpublic network target')
    return addresses[0]


def fetch_page(url: str, *, provider: str, task_id: str, session, budget) -> SearchOutcomeV1:
    if provider not in ('deepseek', 'tavily'):
        raise ValueError('unknown page provider')
    try:
        validate_public_url(url)
    except (ValueError, OSError):
        return SearchOutcomeV1(task_id=task_id, provider=provider, status='refused', reason='unsafe_or_unresolved_url')
    if provider == 'deepseek':
        endpoint = 'https://api.deepseek.com/v1/tools/fetch'
        key = os.getenv('DEEPSEEK_API_KEY', '').strip()
        payload = {'url': url}
    else:
        endpoint = 'https://api.tavily.com/extract'
        keys = configured_keys()
        key = keys[0] if keys else ''
        payload = {'urls': [url], 'extract_depth': 'basic', 'format': 'markdown', 'include_usage': True}
    data, failure = request_json(endpoint, payload, key=key, provider=provider,
        task_id=task_id, session=session, budget=budget, page=True)
    if failure is not None:
        return failure
    if provider == 'deepseek':
        body, title = data.get('content'), data.get('title', '')
    else:
        results = data.get('results')
        row = next((r for r in results if isinstance(r, dict) and r.get('url') == url), {}) if isinstance(results, list) else {}
        body, title = row.get('raw_content'), ''
    if not isinstance(body, str) or not body.strip():
        return SearchOutcomeV1(task_id=task_id, provider=provider, status='failed', reason='page_body_unavailable')
    return SearchOutcomeV1(task_id=task_id, provider=provider, status='ok', hits=(
        SearchHitV1(provider=provider, url=url, canonical_url=url, title=str(title or '')[:2000],
            content=body[:200000], truncated=len(body) > 200000),))


@contextmanager
def _open_public(url, ip, timeout):
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    cls = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
    options = {'context': ssl.create_default_context()} if parsed.scheme == 'https' else {}
    connection = cls(parsed.hostname, port, timeout=timeout, **options)
    # Connect to the already qualified IP while keeping the original hostname
    # for Host, TLS SNI and certificate checks. No second DNS lookup or proxy.
    connection._create_connection = lambda address, timeout, source_address=None: socket.create_connection(
        (ip, port), timeout, source_address)
    try:
        path = parsed.path or '/'
        if parsed.query:
            path += '?' + parsed.query
        connection.request('GET', path, headers={'User-Agent': 'TradingAgents/1.0'})
        yield connection.getresponse()
    finally:
        connection.close()


def download_public_document(url: str, *, task_id: str, budget) -> tuple[bytes, str]:
    for hop in range(3):
        budget.ensure_active()
        address = validate_public_url(url)
        remaining = budget.remaining_seconds()
        if remaining <= 0:
            raise TimeoutError('document deadline exceeded')
        if not _DATA_SLOTS.acquire(timeout=remaining):
            raise TimeoutError('document queue deadline exceeded')
        grant = None
        try:
            grant = budget.reserve_page(f'{task_id}.hop{hop}')
            budget.ledger.mark_dispatched(grant)
            with _open_public(url, address, min(12.0, budget.remaining_seconds())) as response:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader('Location')
                    budget.ledger.settle(grant, ok=False, usage_available=False)
                    if hop == 2 or not location:
                        raise ValueError('document redirect limit')
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise ValueError('document HTTP unavailable')
                length = response.getheader('Content-Length')
                if length and int(length) > MAX_PDF_BYTES:
                    raise ValueError('document byte limit')
                content = bytearray()
                while True:
                    budget.ensure_active()
                    if budget.remaining_seconds() <= 0:
                        raise TimeoutError('document activity timeout')
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    content.extend(chunk)
                    if len(content) > MAX_PDF_BYTES:
                        raise ValueError('document byte limit')
                budget.ledger.settle(grant, ok=True, usage_available=False)
                return bytes(content), url
        except Exception:
            if grant is not None:
                budget.ledger.settle(grant, ok=False, usage_available=False)
            raise
        finally:
            _DATA_SLOTS.release()
    raise ValueError('document redirect exhausted')
