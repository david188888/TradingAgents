"""Discovered URLs cannot bypass page, redirect, or public-network limits."""

import socket
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from tests.test_search_budget import Journal
from tests.test_search_providers import Session
from tradingagents.dataflows import search_pages
from tradingagents.execution.budget import BudgetBucket as B
from tradingagents.execution.search_budget import SearchBudget


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('93.184.216.34', 443))])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-not-real')
    monkeypatch.setenv('TAVILY_API_KEY', 'test-not-real')


def test_page_redirect_private_target_rejected():
    j = Journal()
    with pytest.raises(ValueError):
        search_pages.validate_public_url('http://127.0.0.1/private')
    result = search_pages.fetch_page('http://169.254.169.254/token', provider='deepseek',
        task_id='unsafe', session=Session(), budget=SearchBudget(j.ledger))
    assert result.status == 'refused' and not j.ledger.records()


def test_fetch_uses_page_pool_and_body_is_original():
    j = Journal()
    session = Session(data={'title': '文件', 'content': '原文'})
    result = search_pages.fetch_page('https://example.com/a', provider='deepseek',
        task_id='page', session=session, budget=SearchBudget(j.ledger))
    assert result.status == 'ok' and result.hits[0].content == '原文'
    assert j.ledger.consumed(B.SEARCH_PAGE) == 1
    assert j.ledger.consumed(B.DEEPSEEK_SEARCH) == 0


def test_redirect_hops_charge_same_8_pool(monkeypatch):
    j = Journal()
    calls = []
    @contextmanager
    def opener(url, ip, timeout):
        calls.append((url, ip))
        location = 'http://127.0.0.1/private' if len(calls) == 2 else '/next'
        yield SimpleNamespace(status=302, getheader=lambda key: location if key == 'Location' else None)
    monkeypatch.setattr(search_pages, '_open_public', opener)
    with pytest.raises(ValueError):
        search_pages.download_public_document('https://example.com/a', task_id='doc', budget=SearchBudget(j.ledger))
    assert len(calls) == 2 and j.ledger.consumed(B.SEARCH_PAGE) == 2


def test_oversize_pdf_rejected(monkeypatch):
    j = Journal()
    @contextmanager
    def opener(*args):
        yield SimpleNamespace(status=200, getheader=lambda key: str(20*1024*1024+1) if key == 'Content-Length' else None)
    monkeypatch.setattr(search_pages, '_open_public', opener)
    with pytest.raises(ValueError, match='byte'):
        search_pages.download_public_document('https://example.com/a.pdf', task_id='doc', budget=SearchBudget(j.ledger))


def test_provider_security_refusal_is_not_page_fallback():
    result = search_pages.fetch_page('https://example.com/a', provider='deepseek',
        task_id='policy', session=Session(status=403), budget=SearchBudget(Journal().ledger))
    assert result.status == 'refused' and not result.retryable
