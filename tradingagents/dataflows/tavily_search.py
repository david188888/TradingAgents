"""Tavily generic search without legacy news routing or automatic upgrades."""

import os
from threading import Lock
from weakref import WeakKeyDictionary

from tradingagents.dataflows.news_key_health import NewsProviderKeyPool
from tradingagents.dataflows.search_transport import request_json, search_result

SEARCH_URL = 'https://api.tavily.com/search'
_pools = WeakKeyDictionary()
_pool_lock = Lock()


def configured_keys():
    multi = os.getenv('TAVILY_API_KEYS', '')
    values = [value.strip() for value in multi.split(',') if value.strip()]
    legacy = os.getenv('TAVILY_API_KEY', '').strip()
    return tuple(dict.fromkeys(values or ([legacy] if legacy else [])))


def search(request, *, session, budget):
    payload = {'query': request.query, 'max_results': 8, 'search_depth': request.depth,
        'topic': 'general', 'include_raw_content': True, 'include_answer': False,
        'auto_parameters': False, 'include_usage': True, 'include_published_date': True,
        'end_date': request.cutoff.isoformat()}
    if request.start_date:
        payload['start_date'] = request.start_date.isoformat()
    with _pool_lock:
        pool = _pools.setdefault(budget, NewsProviderKeyPool('tavily'))
        pool.configure(configured_keys())
        key = pool.acquire()
    data, failure = request_json(SEARCH_URL, payload, key=key or '',
        provider='tavily', task_id=request.task_id, session=session, budget=budget)
    if key:
        with _pool_lock:
            if failure is not None:
                pool.record_failure(key, cooldown_seconds=90 if failure.reason in ('tavily_http_401', 'tavily_http_402') else 20,
                                    reason=failure.reason)
            else:
                pool.record_success(key)
    return failure if failure is not None else search_result(data, request)
