"""V8 collection: dedicated facts first, dual discovery and exact gap recovery."""

from datetime import date, timedelta

from tradingagents.agents.schemas._search import (
    AdmissionBatchV1,
    FieldRequirementV1,
    SearchRequestV1,
)
from tradingagents.agents.schemas._verification_plan import FinancialOperandV1
from tradingagents.dataflows.minimum_sources import MinimumEvidenceSources
from tradingagents.execution.budget import BudgetBucket, BudgetExhausted
from tradingagents.execution.search_coordinator import bounded_query, initial_requests
from tradingagents.observability.canonical import canonical_sha256
from tradingagents.research.native_record import build_native_record
from tradingagents.research.search_admission import admit_search_batch
from tradingagents.research.search_recovery import recover_fields, recovered_identity
from tradingagents.research.verification_tools import _financial_operand, _Unavailable


def recovery_requests(*, ticker, company_name, cutoff, capability, requirements):
    """One bounded paired query group per failed capability, exact missing fields."""
    fields = ' '.join(sorted({f.field for f in requirements}))
    period = ' '.join(sorted({str(f.period) for f in requirements if f.period}))
    terms = {'identity': '公司名称 上市日期 证券代码', 'profile': '公司简介 主营业务 所属行业',
             'financial': '营业收入 净利润 经营现金流 合并财务报表', 'price': '复权 日线 历史交易数据',
             'valuation': '估值快照 交易日期 股价 市盈率 市净率 总股本 口径'}.get(capability, capability)
    identity = canonical_sha256([f.model_dump(mode='json') for f in requirements])[:16]
    return tuple(SearchRequestV1(task_id=f'recovery.{capability}.{identity}.{provider}', provider=provider,
        kind='recovery', role='market_context' if capability == 'price' else 'operating_quality',
        capability=capability, ticker=ticker, company_name=company_name, cutoff=cutoff,
        query=bounded_query(provider=provider, company_name=company_name, ticker=ticker,
            terms=f'{period} {terms} {fields}', cutoff=cutoff), requirements=requirements)
        for provider in ('deepseek', 'tavily'))


class SearchEvidenceSources(MinimumEvidenceSources):
    def __init__(self, request, run_id, session, fetch, coordinator):
        super().__init__(request, run_id, session, fetch)
        self.coordinator = coordinator
        self.search_batches = []
        self.admitted = AdmissionBatchV1(batch_id='collection.'+run_id)
        self.identity = None
        self.stop_reasons = []

    def _dedicated(self, inputs, capability, operation):
        try:
            return operation()
        except BudgetExhausted as exc:
            if exc.hit.bucket not in {BudgetBucket.DATA_CAPABILITY_CALLS, BudgetBucket.DATA_HTTP_ATTEMPTS}:
                raise
            if not any(c.capability == capability for c in inputs.capabilities):
                self._cap(inputs, capability, gaps=('dedicated_budget_exhausted',))
            return None

    def _financial(self, inputs, ts_code):
        return self._dedicated(inputs, 'fundamentals', lambda: super(SearchEvidenceSources, self)._financial(inputs, ts_code))

    def _events(self, inputs):
        return self._dedicated(inputs, 'event_coverage', lambda: super(SearchEvidenceSources, self)._events(inputs))

    def _prices(self, inputs, ts_code, identity):
        return self._dedicated(inputs, 'price_history', lambda: super(SearchEvidenceSources, self)._prices(inputs, ts_code, identity))

    def _search(self, requests):
        if self.request.effective_config.get('evidence_search_enabled', True) is False:
            return AdmissionBatchV1(batch_id='search-disabled')
        try:
            batch = self.coordinator.collect(requests, input_snapshot_id='collection.'+self.run_id)
        except (BudgetExhausted, TimeoutError):
            self.coordinator.budget.ensure_active()
            self.stop_reasons.append('search_budget_or_time_exhausted')
            return AdmissionBatchV1(batch_id='search-exhausted')
        self.search_batches.append(batch)
        admitted = admit_search_batch(batch, ticker=self.request.ticker, cutoff=self.request.analysis_date)
        requirements = tuple(dict.fromkeys(f for r in requests for f in r.requirements))
        admitted = recover_fields(admitted, requirements=requirements)
        self.admitted = AdmissionBatchV1(batch_id=self.admitted.batch_id,
            observations=(*self.admitted.observations, *admitted.observations),
            fields=tuple(dict.fromkeys((*self.admitted.fields, *admitted.fields))),
            rejections=tuple(dict.fromkeys((*self.admitted.rejections, *admitted.rejections))),
            conflicts=tuple(dict.fromkeys((*self.admitted.conflicts, *admitted.conflicts))))
        return admitted

    def _identity(self, inputs, ts_code):
        self.identity = self._dedicated(inputs, 'security_identity', lambda: super(SearchEvidenceSources, self)._identity(inputs, ts_code))
        if self.identity is None:
            requirements = tuple(FieldRequirementV1(ticker=ts_code, field=field, unit='text', basis='explicit_identity')
                                 for field in ('name', 'list_date'))
            admitted = self._search(recovery_requests(ticker=ts_code, company_name=ts_code,
                cutoff=inputs.cutoff, capability='identity', requirements=requirements))
            self.identity = recovered_identity(admitted.fields, ticker=ts_code, cutoff=inputs.cutoff)
        return self.identity

    def _record(self, draft, context):
        record = build_native_record(draft, context, mode='company_research', include_coverage=True,
            include_valuation=True, include_minimum=True, include_basics=True,
            include_structured_financial=True, search_admission=self.admitted,
            search_batches=tuple(self.search_batches))
        if self.request.effective_config.get('evidence_search_enabled', True) is False:
            record = type(record).model_validate({**record.model_dump(mode='python'),
                'search_stop_reasons': ('search_disabled',)})
        elif self.stop_reasons:
            record = type(record).model_validate({**record.model_dump(mode='python'),
                'search_stop_reasons': tuple(dict.fromkeys(self.stop_reasons))})
        return record

    def collect(self):
        draft, context = super().collect()
        self.source_admission = draft.capabilities
        if self.identity is None:
            return self._record(draft, context), context
        self._search(initial_requests(ticker=self.request.ticker, company_name=self.identity['name'],
                                      cutoff=self.request.analysis_date))
        record = self._record(draft, context)
        cutoff = date.fromisoformat(self.request.analysis_date)
        from tradingagents.research.structured_financial_checks import target_period
        period = target_period(record) or date(cutoff.year if cutoff.month >= 9 else cutoff.year-1,
                                               6 if cutoff.month >= 9 else 12, 30 if cutoff.month >= 9 else 31)
        missing = []
        for field in ('revenue', 'n_income_attr_p', 'n_income', 'n_cashflow_act'):
            table = 'cashflow' if field == 'n_cashflow_act' else 'income'
            for source in record.evidence:
                try:
                    _financial_operand(record, FinancialOperandV1(evidence_id=source.evidence_id,
                        table=table, field=field, report_period=period.isoformat()))
                except _Unavailable:
                    continue
                break
            else:
                missing.append(FieldRequirementV1(ticker=self.request.ticker, field=field, period=period,
                    unit='CNY', currency='CNY', basis='consolidated_actual'))
        if missing:
            self._search(recovery_requests(ticker=self.request.ticker, company_name=self.identity['name'],
                cutoff=cutoff, capability='financial', requirements=tuple(missing)))
        labels = {f.label for f in record.company_basics.introduction}
        profile = tuple(FieldRequirementV1(ticker=self.request.ticker, field=field, unit='text', basis='explicit_profile')
            for field, label in (('introduction', '公司简介'), ('main_business', '主营业务'), ('industry', '所属行业'))
            if label not in labels)
        if profile:
            self._search(recovery_requests(ticker=self.request.ticker, company_name=self.identity['name'],
                cutoff=cutoff, capability='profile', requirements=profile))
        if not record.metrics or not any(m.availability == 'available' for m in record.metrics):
            requirements = (FieldRequirementV1(ticker=self.request.ticker, field='adjusted_daily',
                period=cutoff, window_start=date.fromisoformat(draft.price_window_start) if hasattr(draft, 'price_window_start') else cutoff-timedelta(days=365),
                unit='CNY/share', currency='CNY', basis='dated_adjustment_complete_sessions'),)
            self._search(recovery_requests(ticker=self.request.ticker, company_name=self.identity['name'],
                cutoff=cutoff, capability='price', requirements=requirements))
        if record.valuation is None:
            # Discovery can still supply context. Only a complete dated and
            # basis-qualified snapshot could enter the valuation calculation;
            # the current text parser deliberately does not manufacture one.
            requirements = (FieldRequirementV1(ticker=self.request.ticker, field='dated_valuation_snapshot',
                period=cutoff, unit='text', currency='CNY', basis='same_session_explicit_valuation_basis'),)
            self._search(recovery_requests(ticker=self.request.ticker, company_name=self.identity['name'],
                cutoff=cutoff, capability='valuation', requirements=requirements))
        return self._record(draft, context), context
