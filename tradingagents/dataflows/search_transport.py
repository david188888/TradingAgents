"""One observable search HTTP attempt, without implicit retries or chat SDKs."""

from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

from tradingagents.agents.schemas._search import SearchHitV1, SearchOutcomeV1
from tradingagents.dataflows.catalyst_transport import _DATA_SLOTS, BudgetedSession


def request_json(url, payload, *, key, provider, task_id, session, budget, page=False):
    budget.ensure_active()
    if isinstance(session, BudgetedSession):
        raise ValueError('search requires its own transport, not the dedicated-data pool')
    if not key:
        return None, SearchOutcomeV1(task_id=task_id, provider=provider,
            status='unavailable', reason='credentials_missing')
    if budget.remaining_seconds() <= 0:
        raise TimeoutError('search activity exhausted')
    while not _DATA_SLOTS.acquire(timeout=min(0.1, budget.remaining_seconds())):
        budget.ensure_active()
        if budget.remaining_seconds() <= 0:
            raise TimeoutError('search queue deadline exceeded')
    grant = None
    try:
        budget.ensure_active()
        grant = budget.reserve_page(task_id) if page else budget.reserve_search(provider, task_id)
        budget.ledger.mark_dispatched(grant)
        try:
            response = session.post(url, json=payload, headers={'Authorization': 'Bearer ' + key},
                timeout=min(15.0, budget.remaining_seconds()), allow_redirects=False)
            status = response.status_code
            if status != 200:
                budget.ledger.settle(grant, ok=False, usage_available=False)
                return None, SearchOutcomeV1(task_id=task_id, provider=provider, status='refused' if status == 403 else 'failed',
                    reason=f'{provider}_http_{status}', retryable=status in (408, 429) or status >= 500)
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError('invalid response shape')
            budget.ledger.settle(grant, ok=True, usage_available=False)
            return data, None
        except requests.RequestException:
            budget.ledger.settle(grant, ok=False, usage_available=False)
            return None, SearchOutcomeV1(task_id=task_id, provider=provider, status='failed',
                reason='transport_unavailable', retryable=True)
        except (ValueError, TypeError):
            budget.ledger.settle(grant, ok=False, usage_available=False)
            return None, SearchOutcomeV1(task_id=task_id, provider=provider, status='failed',
                reason='transport_or_response_invalid', retryable=False)
    finally:
        _DATA_SLOTS.release()


def normalized_hit(row, provider):
    url = row.get('url')
    if not isinstance(url, str) or not url.startswith(('https://', 'http://')):
        raise ValueError('invalid result URL')
    published = row.get('date') if provider == 'deepseek' else row.get('published_date')
    precision = 'timestamp'
    try:
        timestamp = datetime.fromisoformat(published.replace('Z', '+00:00')) if published else None
        if provider == 'tavily' and isinstance(published, str) and len(published) == 10 and timestamp:
            # Date-only estimates are compared as A-share calendar days. The
            # explicit precision prevents representing midnight as measured time.
            timestamp = timestamp.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
            precision = 'day'
        if timestamp and timestamp.tzinfo is None:
            timestamp = None
    except (ValueError, AttributeError):
        timestamp = None
        if provider == 'tavily' and isinstance(published, str):
            try:
                timestamp = parsedate_to_datetime(published)
                if timestamp.tzinfo is None:
                    timestamp = None
            except (ValueError, TypeError, OverflowError):
                pass
    body = row.get('content') if provider == 'deepseek' else row.get('raw_content')
    summary = row.get('summary', row.get('snippet', '')) if provider == 'deepseek' else row.get('content', '')
    body = body if isinstance(body, str) else ''
    return SearchHitV1(provider=provider, url=url, canonical_url=url,
        title=str(row.get('title') or '')[:2000], summary=str(summary or '')[:8000],
        content=body[:200000], published_at=timestamp, published_precision=precision, publisher=row.get('site_name'),
        score=row.get('rerank_score' if provider == 'deepseek' else 'score'),
        authority=row.get('authority') if provider == 'deepseek' else None,
        truncated=len(body) > 200000)


def search_result(data, request):
    try:
        rows = data.get('results')
        if not isinstance(rows, list):
            raise ValueError('missing search results')
        hits = tuple(normalized_hit(row, request.provider) for row in rows[:8])
        usage = data.get('usage', {}).get('credits') if isinstance(data.get('usage'), dict) else None
        return SearchOutcomeV1(task_id=request.task_id, provider=request.provider,
            status='ok' if hits else 'empty', hits=hits, usage=usage)
    except (ValueError, TypeError, AttributeError):
        return SearchOutcomeV1(task_id=request.task_id, provider=request.provider,
            status='failed', reason='provider_response_unqualified')
