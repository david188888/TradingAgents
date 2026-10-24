"""Search-discovered official PDFs reuse the bounded real disclosure parser."""

import json
from pathlib import Path

from tests.search_fixtures import make_search_request
from tradingagents.agents.schemas._search import FieldRequirementV1, SearchBatchV1
from tradingagents.dataflows.search_documents import parse_search_document
from tradingagents.research.search_admission import admit_search_batch
from tradingagents.research.search_recovery import recover_fields


def test_pdf_selected_pages_recover_financial_field(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    import pypdf

    from tradingagents.agents.schemas._search import SearchHitV1
    raw = json.loads(Path('tests/fixtures/600803-official-table-excerpts-v2.json').read_text())['documents'][0]
    pages = raw['pages']
    # Bind each fixture page separately rather than late-binding the loop.
    def reader(*args, **kwargs):
        return SimpleNamespace(is_encrypted=False, pages=[
            SimpleNamespace(extract_text=(lambda text: lambda **kw: text)(p['text'])) for p in pages])
    monkeypatch.setattr(pypdf, 'PdfReader', reader)
    cutoff = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    url = 'https://static.cninfo.com.cn/finalpage/2026-08-29/1225526373.PDF'
    hit = SearchHitV1(provider='deepseek', url=url, canonical_url=url, title=raw['title'],
        published_at=datetime(2026, 8, 29, tzinfo=timezone.utc))
    document = parse_search_document(b'%PDF-fixture', hit=hit, ticker='600803.SH', cutoff=cutoff)
    batch = SearchBatchV1(batch_id='pdf', input_snapshot_id='v0',
        requests=(make_search_request(ticker='600803.SH', company_name='新奥股份', cutoff=cutoff,
            role='operating_quality'),), hits=(hit.model_copy(update={'document': document}),))
    admitted = admit_search_batch(batch, ticker='600803.SH', cutoff=cutoff)
    field = FieldRequirementV1(ticker='600803.SH', field='revenue', period='2026-06-30',
        unit='CNY', currency='CNY', basis='consolidated_actual')
    recovered = recover_fields(admitted, requirements=(field,))
    assert recovered.fields and recovered.fields[0].value == '63990230000'
    assert any('PDF' in o.source.content.locator_label for o in recovered.observations)
