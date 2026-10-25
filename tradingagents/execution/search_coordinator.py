"""Run-scoped dual search with durable replay, bounded retries and page reuse."""

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from http.client import HTTPException
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from tradingagents.agents.schemas._search import (
    SearchBatchV1,
    SearchDocumentV1,
    SearchOutcomeV1,
    SearchRequestV1,
)
from tradingagents.dataflows import deepseek_search, tavily_search
from tradingagents.dataflows.native_qualification import NativeSourceUnavailable
from tradingagents.dataflows.search_documents import parse_search_document
from tradingagents.dataflows.search_pages import download_public_document, fetch_page
from tradingagents.execution.budget import BudgetConflictError, BudgetExhausted
from tradingagents.execution.models import AnalysisCancelled
from tradingagents.observability.canonical import canonical_sha256
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict


def bounded_query(*, provider, ticker, company_name, terms, cutoff):
    cutoff = date.fromisoformat(cutoff) if isinstance(cutoff, str) else cutoff
    prefix = f'{company_name[:32]} {ticker} '
    suffix = ' before:'+(cutoff+timedelta(days=1)).isoformat()
    limit = 128 if provider == 'deepseek' else 400
    return prefix+terms[:limit-len(prefix)-len(suffix)].strip()+suffix


def initial_requests(*, ticker, company_name, cutoff):
    cutoff = date.fromisoformat(cutoff) if isinstance(cutoff, str) else cutoff
    return tuple(SearchRequestV1(task_id=f'initial.{topic}.{provider}', provider=provider,
        kind='initial', ticker=ticker, company_name=company_name, cutoff=cutoff,
        role='event_context' if topic == '新闻' else 'operating_quality',
        capability='news' if topic == '新闻' else 'industry',
        query=bounded_query(provider=provider, ticker=ticker, company_name=company_name, terms=topic, cutoff=cutoff))
        for topic in ('新闻', '行业政策', '竞争格局') for provider in ('deepseek', 'tavily'))


def compile_queries(gap, *, ticker, company_name, round_id):
    queries = (gap.question, '反例 风险 '+gap.evidence_needed)
    return tuple(SearchRequestV1(task_id=f'{gap.gap_id}.{provider}.{index}', provider=provider,
        kind='supplement', ticker=ticker, company_name=company_name, cutoff=gap.cutoff,
        role=gap.role, capability=gap.capability,
        query=bounded_query(provider=provider, ticker=ticker, company_name=company_name, terms=query, cutoff=gap.cutoff),
        round_id=round_id, gap_id=gap.gap_id, requirements=gap.requirements)
        for provider in ('deepseek', 'tavily') for index, query in enumerate(queries))


def canonical_url(url):
    parsed = urlsplit(url)
    pairs = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith('utm_') and key.lower() != 'spm']
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or '/', urlencode(sorted(pairs)), ''))


class SearchCoordinator:
    def __init__(self, session, budget, journal, *, sleeper=time.sleep):
        self.session, self.budget, self.journal = session, budget, journal
        self.ledger, self.sleeper = budget.ledger, sleeper
        self._document_failures = []

    def task_identity(self, request, snapshot_id):
        value = request.model_dump(mode='json', exclude={'task_id'})
        return canonical_sha256({'request': value, 'input': snapshot_id})

    def _execute(self, request, snapshot_id):
        identity = self.task_identity(request, snapshot_id)
        key = 'search.output.' + identity
        cached = self.ledger.cached_result(key)
        if cached is not None:
            return SearchOutcomeV1.model_validate(cached['outcome'])
        logical = f'search.{request.provider}.{identity}'
        if any(r.logical_call_id == logical and r.dispatched_at is not None for r in self.ledger.records()):
            return SearchOutcomeV1(task_id=request.task_id, provider=request.provider,
                status='refused', reason='dispatch_outcome_unknown')
        function = deepseek_search.search if request.provider == 'deepseek' else tavily_search.search
        bound = request.model_copy(update={'task_id': identity})
        for attempt in range(2):
            self.budget.ensure_active()
            try:
                result = function(bound, session=self.session, budget=self.budget)
            except BudgetExhausted:
                result = SearchOutcomeV1(task_id=identity, provider=request.provider,
                    status='refused', reason='search_budget_exhausted')
            except TimeoutError:
                self.budget.ensure_active()
                result = SearchOutcomeV1(task_id=identity, provider=request.provider,
                    status='refused', reason='search_time_exhausted')
            if not result.retryable or attempt == 1:
                break
            delay = min(0.5, self.budget.remaining_seconds())
            if delay <= 0:
                break
            self.sleeper(delay)
        result = result.model_copy(update={'task_id': request.task_id})
        self.ledger.record_result(key, {'outcome': result.model_dump(mode='json')})
        return result

    def _body(self, hit, request=None):
        if request is not None and request.requirements and urlsplit(hit.url).path.lower().endswith('.pdf'):
            qualified = self._pdf(hit, request)
            if qualified.document is not None:
                return qualified
        if hit.content:
            return hit
        for provider in (hit.provider, 'tavily' if hit.provider == 'deepseek' else 'deepseek'):
            identity = canonical_sha256({'url': hit.canonical_url, 'provider': provider})
            key = 'search.page.output.' + identity
            cached = self.ledger.cached_result(key)
            if cached is not None:
                outcome = SearchOutcomeV1.model_validate(cached['outcome'])
            else:
                logical = 'search.page.' + identity
                if any(r.logical_call_id == logical and r.dispatched_at for r in self.ledger.records()):
                    continue
                try:
                    outcome = fetch_page(hit.url, provider=provider, task_id=identity,
                        session=self.session, budget=self.budget)
                except BudgetExhausted:
                    return hit
                except TimeoutError:
                    self.budget.ensure_active()
                    return hit
                self.ledger.record_result(key, {'outcome': outcome.model_dump(mode='json')})
            if outcome.status == 'ok':
                page = outcome.hits[0]
                return hit.model_copy(update={'content': page.content, 'truncated': page.truncated,
                                               'title': hit.title or page.title})
            if outcome.status == 'refused':
                return hit
        if request is not None and urlsplit(hit.url).path.lower().endswith('.pdf'):
            return self._pdf(hit, request)
        return hit

    def _pdf(self, hit, request):
        identity = 'pdf.' + canonical_sha256({'url': hit.url, 'ticker': request.ticker,
                                              'cutoff': request.cutoff.isoformat()})
        key = 'search.document.' + identity
        cached = self.ledger.cached_result(key)
        if cached is not None:
            if cached.get('reason'):
                self._document_failures.append(cached['reason'])
            return hit.model_copy(update={'document': SearchDocumentV1.model_validate(cached['document']),
                'url': cached.get('final_url', hit.url)}) if cached.get('document') else hit
        if any(r.logical_call_id.startswith('search.page.'+identity+'.hop') and r.dispatched_at is not None
               for r in self.ledger.records()):
            return hit
        document = None
        reason = None
        target = hit
        try:
            data, final_url = download_public_document(hit.url, task_id=identity, budget=self.budget)
            target = hit.model_copy(update={'url': final_url})
            document = parse_search_document(data, hit=target, ticker=request.ticker, cutoff=request.cutoff,
                ensure_active=self.budget.ensure_search_active)
        except (CatalystCheckpointConflict, BudgetConflictError, AnalysisCancelled):
            raise
        except BudgetExhausted:
            self.budget.ensure_active()
            reason = 'document_budget_exhausted'
        except TimeoutError:
            self.budget.ensure_active()
            reason = 'document_time_exhausted'
        except (OSError, HTTPException):
            reason = 'document_transport_unavailable'
        except (NativeSourceUnavailable, ValueError):
            reason = 'document_unqualified'
        if reason:
            self._document_failures.append(reason)
        self.ledger.record_result(key, {'document': document.model_dump(mode='json') if document else None,
            'reason': reason, 'final_url': target.url})
        return target.model_copy(update={'document': document})

    def collect(self, requests, *, input_snapshot_id):
        self._document_failures = []
        if len({(r.ticker, r.cutoff) for r in requests}) > 1:
            raise ValueError('search batch must share company and cutoff')
        identity = canonical_sha256({'requests': [r.model_dump(mode='json') for r in requests],
                                     'input': input_snapshot_id})
        key = 'search.batch.' + identity
        cached = self.ledger.cached_result(key)
        if cached is not None:
            return SearchBatchV1.model_validate(cached['batch'])
        self.budget.ensure_active()
        if not requests:
            return SearchBatchV1(batch_id=identity, input_snapshot_id=input_snapshot_id)
        with self.budget.activity_batch(identity):
            with ThreadPoolExecutor(max_workers=2) as pool:
                pending = [pool.submit(self._execute, request, input_snapshot_id) for request in requests]
                outcomes = tuple(future.result() for future in pending)
            merged = {}
            families = {}
            family_requests = {}
            for request, outcome in zip(requests, outcomes, strict=True):
                for hit in outcome.hits:
                    url = canonical_url(hit.url)
                    fingerprint = hashlib.sha256(' '.join(hit.content.split()).encode()).hexdigest() if len(hit.content) >= 200 else None
                    family = families.setdefault(fingerprint, url) if fingerprint else url
                    family_requests.setdefault(family, []).append(request)
                    candidate = hit.model_copy(update={'canonical_url': url, 'family_id': family})
                    old = merged.get(family)
                    if old is None or (not candidate.truncated, len(candidate.content)) > (not old.truncated, len(old.content)):
                        merged[family] = candidate
            # Extraction needs the demands that discovered this source, including
            # a later financial demand for a URL also found by a background task.
            extracted = tuple(self._body(hit, next(
                (request for request in family_requests[family] if request.requirements),
                family_requests[family][0])) for family, hit in merged.items())
            # Fetch/Extract may reveal that initially distinct discovery URLs
            # are the same syndicated text. Keep their discovery/role linkage,
            # but never count them as independent source families.
            grouped = []
            bodies = []
            for hit in extracted:
                body = ' '.join(hit.content.split())
                family = hit.family_id
                if len(body) >= 200:
                    family = next((old.family_id for old, text in bodies
                        if body == text or (hit.truncated and body in text)
                        or (old.truncated and text in body)), family)
                    bodies.append((hit.model_copy(update={'family_id': family}), body))
                grouped.append(hit.model_copy(update={'family_id': family}))
            hits = tuple(grouped)
        reasons = tuple(dict.fromkeys((*[o.reason for o in outcomes if o.reason], *self._document_failures)))
        self.budget.ensure_active()
        result = SearchBatchV1(batch_id=identity, input_snapshot_id=input_snapshot_id,
            requests=requests, outcomes=outcomes, hits=hits, stop_reasons=reasons)
        self.ledger.record_result(key, {'batch': result.model_dump(mode='json')})
        return result
