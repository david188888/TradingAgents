"""Recovered fields enter deterministic checks with immutable input revisions."""

from datetime import date

import pytest
from pydantic import ValidationError

from tests.search_fixtures import make_v2_record
from tests.test_search_recovery import demand, recover, report
from tradingagents.agents.schemas._research_record_v2 import ResearchRecordV2
from tradingagents.research.evidence_revisions import (
    affected_roles,
    append_admission,
    recompute_revision,
)


def test_recovered_financial_field_enters_check():
    record = make_v2_record(analysis_date=date.today())
    new = append_admission(record, recover(report()), round_id='1')
    assert new.snapshots[0] == record.snapshots[0]
    assert len(new.snapshots) == 2 and len(new.recovered_fields) == 1
    assert affected_roles(record, new) == ('operating_quality',)
    computed = recompute_revision(new, journal=None)
    assert computed.revision_calculations[0].value == '120.50'
    assert computed.revision_calculations[0].input_snapshot_id == new.snapshots[-1].snapshot_id
    assert len(computed.snapshots) == 3


def test_no_increment_does_not_append_snapshot():
    record = make_v2_record(analysis_date=date.today())
    admitted = recover(report())
    new = append_admission(record, admitted, round_id='1')
    assert append_admission(new, admitted, round_id='2') == new


def test_recovered_field_tamper_rejected():
    record = make_v2_record(analysis_date=date.today())
    new = append_admission(record, recover(report()), round_id='1')
    payload = new.model_dump(mode='json')
    payload['recovered_fields'][0]['value'] = '999'
    with pytest.raises(ValidationError):
        ResearchRecordV2.model_validate(payload)


def test_new_price_fields_require_full_window():
    admitted = recover('公司代码：600519\n近一年涨幅20%', demand(field='adjusted_daily', unit='CNY/share'))
    assert admitted.fields == ()


def test_recovered_comparative_table_calculates_growth():
    record = make_v2_record(analysis_date=date.today())
    new = append_admission(record, recover(report()), round_id='1')
    computed = recompute_revision(new, journal=None)
    operations = {c.operation: c for c in computed.revision_calculations}
    assert operations['difference'].value == '20.50'
    assert operations['growth'].value == '0.205'
    assert operations['growth'].unit == 'ratio'
    assert operations['growth'].prior_period == '2024-12-31'
    assert recompute_revision(computed, journal=None) == computed


def test_new_catalog_binds_actual_revision_and_old_snapshot_replays():
    from tradingagents.research.numeric_catalog import build_numeric_catalog
    record = make_v2_record(analysis_date=date.today())
    original = build_numeric_catalog(record)
    new = recompute_revision(append_admission(record, recover(report()), round_id='1'), journal=None)
    catalog = build_numeric_catalog(new)
    growth = next(a for a in catalog['anchors'] if a['definition_key'] == 'recovered.revenue.growth')
    assert growth['value'] == '0.205'
    assert growth['snapshot_id'] == new.snapshots[-1].snapshot_id
    assert build_numeric_catalog(new, snapshot_id=record.snapshots[0].snapshot_id) == original


def test_recovered_field_participates_in_bounded_predicate():
    from tradingagents.agents.schemas._verification_plan import FinancialOperandV1
    from tradingagents.research.verification_tools import _financial_operand
    record = make_v2_record(analysis_date=date.today())
    new = append_admission(record, recover(report()), round_id='1')
    field = new.recovered_fields[0]
    value, lineage = _financial_operand(new, FinancialOperandV1(evidence_id=field.evidence_id,
        table='income', field='revenue', report_period='2025-12-31'))
    assert str(value) == '120.50'
    assert lineage['source_content_sha256'] == field.source_content_sha256


def test_requested_currency_must_match_recovered_currency():
    assert not recover(report(), demand(currency='USD')).fields


def test_original_verification_retains_v2_chain_and_predicate_scope(tmp_path):
    from tests.test_bounded_verification import inputs, journal_for
    from tradingagents.execution.verification_executor import execute_verification
    from tradingagents.research.record_codec import parse_research_record
    journal = journal_for(tmp_path)
    original, plan = inputs(run_id=journal.ledger.run_id)
    payload = original.model_dump(mode='json')
    payload.update(schema_version='research-record-v2', workflow_version='evidence-production-v8')
    record = parse_research_record(payload)
    output = execute_verification(record, plan, ledger=journal.ledger)
    assert output.record.schema_version == 'research-record-v2'
    assert len(output.record.snapshots) == 2
    assert output.record.hypotheses == record.hypotheses
    assert output.record.verifications[0].scope == 'predicate_only'
    assert execute_verification(record, plan, ledger=journal.ledger) == output


def test_check_revisions_keep_old_inputs_and_refresh_latest():
    from tradingagents.research.minimum_evidence import compute_checks
    record = make_v2_record(analysis_date=date.today())
    record = ResearchRecordV2.model_validate({**record.model_dump(mode='python'),
        'evidence_checks': compute_checks(record), 'challenge_bindings': (), 'challenges': ()})
    new = append_admission(record, recover(report()), round_id='1')
    computed = recompute_revision(new, journal=None)
    assert computed.check_revisions[0] == record.evidence_checks
    assert computed.evidence_checks.input_snapshot_id == computed.snapshots[-1].snapshot_id
    damaged = computed.model_dump(mode='json')
    damaged['check_revisions'][0]['input_sha256'] = '0'*64
    with pytest.raises(ValidationError):
        ResearchRecordV2.model_validate(damaged)


def test_api_and_web_disagreement_stays_conflicted():
    from tests.test_bounded_verification import inputs, source_text
    from tradingagents.agents.schemas._research_record import SourceContentV1
    from tradingagents.agents.schemas._research_record_v2 import make_evidence_snapshot_v2
    original, _ = inputs()
    source = original.evidence[0].model_copy(update={'content': SourceContentV1.model_validate(
        source_text({'income': [{'end_date': '20251231', 'ann_date': '20260401', 'revenue': 999}]}))})
    payload = original.model_dump(mode='python')
    payload.update(schema_version='research-record-v2', workflow_version='evidence-production-v8',
        analysis_date=date.today(), evidence=(source,),
        snapshots=(make_evidence_snapshot_v2((source,)),))
    for hypothesis in payload['hypotheses']:
        hypothesis['input_snapshot_id'] = payload['snapshots'][0].snapshot_id
    record = ResearchRecordV2.model_validate(payload)
    computed = recompute_revision(append_admission(record, recover(report()), round_id='1'), journal=None)
    assert all(c.status == 'conflict' for c in computed.revision_calculations)


def test_same_material_in_later_batch_is_not_a_new_revision():
    from tests.test_search_admission import material
    from tradingagents.research.search_admission import admit_search_batch
    batch = material(report())
    from tradingagents.research.search_recovery import recover_fields
    a = recover_fields(admit_search_batch(batch, ticker='600519.SH', cutoff=date.today()), requirements=(demand(),))
    record = make_v2_record(analysis_date=date.today())
    first = append_admission(record, a, round_id='1')
    repeated = batch.model_copy(update={'batch_id': 'later'})
    second = admit_search_batch(repeated, ticker=record.ticker, cutoff=record.analysis_date)
    assert append_admission(first, second, round_id='2') == first


def test_current_conflict_removes_old_dependent_arithmetic_but_history_replays():
    from tradingagents.research.numeric_catalog import build_numeric_catalog
    seed = make_v2_record(analysis_date=date.today())
    first = recompute_revision(append_admission(seed, recover(report()), round_id='1'), journal=None)
    old = build_numeric_catalog(first)
    admitted = append_admission(first, recover(report().replace('120.50', '180.50')), round_id='2')
    assert not [a for a in build_numeric_catalog(admitted)['anchors'] if a['definition_key'].startswith('recovered.revenue.')]
    changed = recompute_revision(admitted, journal=None)
    assert not [a for a in build_numeric_catalog(changed)['anchors'] if a['definition_key'].startswith('recovered.revenue.')]
    assert build_numeric_catalog(changed, snapshot_id=first.snapshots[-1].snapshot_id) == old


def test_later_qualification_does_not_change_old_catalog_or_checks():
    from tradingagents.research.minimum_evidence import compute_checks
    from tradingagents.research.numeric_catalog import build_numeric_catalog
    seed = make_v2_record(analysis_date=date.today())
    seed = ResearchRecordV2.model_validate({**seed.model_dump(mode='python'), 'evidence_checks': compute_checks(seed),
        'challenges': (), 'challenge_bindings': ()})
    admitted = recover(report())
    first = append_admission(seed, admitted.model_copy(update={'fields': ()}), round_id='1')
    old = build_numeric_catalog(first)
    later = append_admission(first, admitted, round_id='2')
    assert affected_roles(first, later) == ('operating_quality',)
    assert build_numeric_catalog(later, snapshot_id=first.snapshots[-1].snapshot_id) == old
    from tradingagents.research.record_codec import snapshot_view
    assert compute_checks(snapshot_view(later, first.snapshots[-1].snapshot_id)) == first.evidence_checks
    ResearchRecordV2.model_validate(later.model_dump(mode='json'))


def test_conflicting_comparison_bases_remove_old_growth():
    from tradingagents.research.numeric_catalog import build_numeric_catalog
    first = recompute_revision(append_admission(make_v2_record(analysis_date=date.today()), recover(report()), round_id='1'), journal=None)
    current = recompute_revision(append_admission(first, recover(report().replace('100.00', '0.00')), round_id='2'), journal=None)
    definitions = {a['definition_key'] for a in build_numeric_catalog(current)['anchors']}
    assert 'recovered.revenue.value' in definitions
    assert 'recovered.revenue.growth' not in definitions
    assert 'recovered.revenue.difference' not in definitions
