"""Qualify discovered official PDF identity before exposing selected pages."""

from urllib.parse import urlsplit

from tradingagents.agents.schemas._search import SearchDocumentV1
from tradingagents.dataflows.disclosure_documents_v2 import parse_document
from tradingagents.dataflows.ticker_utils import to_tushare_symbol


def parse_search_document(data, *, hit, ticker, cutoff, ensure_active=lambda: None):
    if hit.published_at is None:
        raise ValueError('document publication unknown')
    path = urlsplit(hit.url).path
    identifier = path.rsplit('/', 1)[-1].split('.')[0]
    parsed = parse_document(data, {'Announcement ID': identifier, 'PDF URL': hit.url,
        'Title': hit.title, 'Published': hit.published_at.date().isoformat()},
        ts_code=to_tushare_symbol(ticker), cutoff=cutoff.isoformat(), ensure_active=ensure_active)
    return SearchDocumentV1(pdf_sha256=parsed['pdf_sha256'], parser_version=parsed['parser_version'],
        security_id=parsed['ts_code'], title=parsed['title'], page_count=parsed['page_count'],
        pages=tuple(parsed['excerpts']))
