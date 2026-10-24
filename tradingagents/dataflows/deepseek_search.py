"""DeepSeek's standalone search API, independent of the research LLM."""

import os

from tradingagents.agents.schemas._search import SearchOutcomeV1
from tradingagents.dataflows.search_transport import request_json, search_result

SEARCH_URL = 'https://api.deepseek.com/v1/tools/search'


def search(request, *, session, budget):
    if request.provider != 'deepseek' or len(request.query) > 128:
        return SearchOutcomeV1(task_id=request.task_id, provider='deepseek',
            status='refused', reason='invalid_provider_or_query_length')
    payload = {'query': request.query, 'count': 8, 'need_content': True}
    data, failure = request_json(SEARCH_URL, payload, key=os.getenv('DEEPSEEK_API_KEY', '').strip(),
        provider='deepseek', task_id=request.task_id, session=session, budget=budget)
    return failure if failure is not None else search_result(data, request)
