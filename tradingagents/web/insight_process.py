"""Read-only Insight stage material and execution progress."""

from tradingagents.agents.schemas._insight import InsightBatch, InsightCatalog, InsightReport
from tradingagents.research.insight_report import validate_insight_report
from tradingagents.web.reader_process_models import ReaderAgentDTO, ReaderProcessDTO, ReaderRole


def stage_report(ctx):
    cp = ctx.checkpoint
    if ctx.record is not None:
        return ctx.record
    catalogs = {key: InsightCatalog.model_validate(value) for key, value in cp.get('insight.catalog_history', {}).items()}
    if not catalogs:
        return None
    items, superseded = [], []
    for role in ('operating_quality', 'event_context', 'market_context'):
        for suffix in ('', '.supplement_1', '.supplement_2', '.supplement_3'):
            saved = cp.get('insight.batch.' + role + suffix)
            if saved is None:
                continue
            batch = InsightBatch.model_validate(saved)
            if suffix:
                superseded.extend(i.insight_id for i in items if i.role == role and i.status != 'excluded')
                items = [i.model_copy(update={'status': 'excluded'}) if i.role == role else i for i in items]
            items.extend(batch.items)
    replies = []
    for role in ('operating_quality', 'event_context', 'market_context'):
        value = cp.get('insight.responses.' + role)
        if value is None:
            continue
        replies.extend(value['responses'])
        withdrawn = {r['target_id'] for r in value['responses'] if r['action'] in {'withdraw', 'revise'}}
        items = [i.model_copy(update={'status': 'excluded'}) if i.insight_id in withdrawn else i for i in items]
        items.extend(InsightBatch.model_validate(value['replacement_items']).items)
    if cp.get('insight.review_catalog'):
        catalogs['review'] = InsightCatalog.model_validate(cp['insight.review_catalog'])
    report = InsightReport(run_id=ctx.snapshot.run_id, ticker=ctx.snapshot.ticker,
        analysis_date=ctx.snapshot.analysis_date, catalogs=catalogs, insights=tuple(items),
        superseded_ids=tuple(superseded), reviews=cp.get('insight.reviews', ()), responses=tuple(replies),
        # A stage never presents an uncommitted overall judgement as a published rating.
        synthesis=None, stages=cp.get('insight.stages', {}),
        focus_question=ctx.snapshot.metadata.get('research_question'),
        focus_insights=InsightBatch.model_validate(cp.get('insight.focus', {})).items)
    return validate_insight_report(report)


def insight_agent(ctx, role):
    base = {'run_id': ctx.snapshot.run_id, 'source_sequence': ctx.sequence, 'role_key': role,
        'origin': 'code' if role in {'evidence', 'code_checks'} else 'model',
        'input_description': '已保存观点、来源与程序数值；这里只读，不调用模型。'}
    try:
        record = stage_report(ctx)
        if record is None:
            return ReaderAgentDTO(**base, availability='not_recorded', reason_code='output_not_recorded')
        status = record.stages.get(role)
        if role == 'focus_response' and not record.focus_question:
            return ReaderAgentDTO(**base, availability='not_applicable', reason_code='focus_not_requested')
        if status not in {'completed', 'failed'} and role not in {'evidence', 'code_checks'}:
            return ReaderAgentDTO(**base, availability='not_recorded', reason_code='output_not_recorded')
        return ReaderAgentDTO(**base, availability='available' if ctx.record is not None else 'insight_stage_available',
            insight_record=record)
    except (ValueError, KeyError, TypeError):
        return ReaderAgentDTO(**base, availability='unavailable', reason_code='insight_output_invalid')


def insight_process(ctx):
    from tradingagents.web.reader_process_projection import ROLE_INFO, native_counts
    roles = []
    statuses = {e.actor_id: e.payload.get('new_status') for e in ctx.events if e.type == 'role.status_changed'}
    for role in ROLE_INFO:
        if role == 'focus_response' and not ctx.snapshot.metadata.get('research_question'):
            continue
        output = insight_agent(ctx, role)
        counts = native_counts(ctx.checkpoint, role=role)
        roles.append(ReaderRole(role_key=role, actor_id='native.' + role, label=ROLE_INFO[role][0],
            origin=output.origin, purpose='核查保存的引用、数值与有效版本。' if output.origin == 'code'
                else '提出研究观点、质疑或综合判断，明确证据与局限。',
            status=statuses.get('native.' + role, ctx.checkpoint.get('insight.stages', {}).get(role, 'pending')),
            output_availability=output.availability, reason_code=output.reason_code,
            output_sequence=ctx.sequence if output.insight_record is not None else None,
            main_budget=counts.main_budget, sdk_main=counts.sdk_main, sdk_repair=counts.sdk_repair,
            focus_budget=counts.focus_budget, sdk_focus=counts.sdk_focus))
    return ReaderProcessDTO(run_id=ctx.snapshot.run_id, source_sequence=ctx.sequence, profile='evidence_v1',
        workflow_version='evidence-production-v9', availability='ready' if ctx.checkpoint.get('insight.report') else 'partial',
        primary_selection='synthesis', counts=native_counts(ctx.checkpoint), roles=tuple(roles))
