"""Original material and publication time are required for admitted observations."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from tests.search_fixtures import make_search_request
from tradingagents.agents.schemas._search import SearchBatchV1, SearchHitV1
from tradingagents.research.search_admission import admit_search_batch


def material(body='公司代码：600519\n测试公司公布年度报告。', **changes):
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    published = datetime.combine(today-timedelta(days=1), datetime.min.time(), timezone.utc)
    hit = SearchHitV1(provider='deepseek', url='https://www.cninfo.com.cn/test',
        canonical_url='https://www.cninfo.com.cn/test', title='测试公司报告',
        content=body, published_at=published, **changes)
    request = make_search_request(cutoff=today, query='测试公司 报告', role='operating_quality')
    return SearchBatchV1(batch_id='batch', input_snapshot_id='v0', requests=(request,), hits=(hit,))


def test_provider_summary_has_no_original_quote():
    batch = material('', summary='只有摘要')
    admitted = admit_search_batch(batch, ticker='600519.SH', cutoff=batch.requests[0].cutoff)
    assert not admitted.observations and admitted.rejections


def test_date_unknown_not_today():
    batch = material()
    batch = batch.model_copy(update={'hits': (batch.hits[0].model_copy(update={'published_at': None}),)})
    assert not admit_search_batch(batch, ticker='600519.SH', cutoff=batch.requests[0].cutoff).observations


def test_original_observation_retains_source_and_scope():
    batch = material()
    admitted = admit_search_batch(batch, ticker='600519.SH', cutoff=batch.requests[0].cutoff)
    assert admitted.observations
    source = admitted.observations[0].source
    assert source.content.text == batch.hits[0].content
    assert source.source_name.startswith('web.') and source.public_url
    assert 'source_reported_not_independently_verified' in source.limitations


def test_historical_page_vintage_unverified():
    batch = material()
    past = batch.requests[0].cutoff-timedelta(days=5)
    assert not admit_search_batch(batch, ticker='600519.SH', cutoff=past).observations
