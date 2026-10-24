"""Deterministic recovery of exact requested fields from qualified original text."""

import re
from datetime import date
from decimal import Decimal

from tradingagents.agents.schemas._search import QualifiedFieldV1
from tradingagents.dataflows.disclosure_documents_v2 import financial_rows

FINANCIAL_FIELDS = {'revenue': 'revenue', 'n_income': 'consolidated_net_income',
                    'n_income_attr_p': 'parent_net_income', 'n_cashflow_act': 'cfo'}
TEXT_FIELDS = {'name': '公司名称', 'list_date': '上市日期', 'main_business': '主营业务',
               'introduction': '公司简介', 'industry': '所属行业'}


def qualified_financial_rows(record, source):
    """Re-read only cells covered by an admitted field's original table."""
    if record.schema_version != 'research-record-v2' or source.content is None or source.content.truncated:
        return ()
    result = []
    for field in record.recovered_fields:
        if (field.evidence_id != source.evidence_id or field.field not in FINANCIAL_FIELDS
                or field.period is None or field.unit != 'CNY' or field.currency not in (None, 'CNY')
                or field.basis != 'consolidated_actual'):
            continue
        for row in financial_rows([{'page': 1, 'text': source.content.text}], field.period.isoformat()):
            if (row['field'] == FINANCIAL_FIELDS[field.field] and row['current'] is not None
                    and Decimal(row['current']) == Decimal(field.value) and row['unit'] == 'CNY'
                    and row not in result):
                result.append(row)
    return tuple(result)


def recovered_statement(record, source):
    """A code-owned view for arithmetic; source identity/content stay unchanged."""
    tables = {}
    names = {value: key for key, value in FINANCIAL_FIELDS.items()}
    for row in qualified_financial_rows(record, source):
        field = names[row['field']]
        table = 'cashflow' if field == 'n_cashflow_act' else 'income'
        for attribute, period in (('current', row['period']), ('previous', row['prior_period'])):
            if row[attribute] is None:
                continue
            values = tables.setdefault(table, {})
            values.setdefault(period, {'end_date': period, 'ann_date': source.published_at.date().isoformat()})[field] = row[attribute]
    return {table: list(rows.values()) for table, rows in tables.items()}


def recovered_identity(fields, *, ticker, cutoff):
    """Unique explicitly labelled identity; no model name inference."""
    from tradingagents.dataflows.ticker_utils import to_tushare_symbol
    selected = [f for f in fields if to_tushare_symbol(f.ticker) == to_tushare_symbol(ticker)]
    names = {f.value for f in selected if f.field == 'name' and f.unit == 'text'}
    dates = {f.value for f in selected if f.field == 'list_date' and f.unit == 'text'}
    if len(names) == len(dates) == 1:
        listed = next(iter(dates))
        if date.fromisoformat(listed) <= date.fromisoformat(str(cutoff)):
            return {'ts_code': to_tushare_symbol(ticker), 'name': next(iter(names)), 'list_date': listed.replace('-', '')}
    return None


def recover_fields(admitted, *, requirements):
    fields, rejected, conflicts = list(admitted.fields), list(admitted.rejections), list(admitted.conflicts)
    for requirement in requirements:
        candidates = []
        for observation in admitted.observations:
            source = observation.source
            content = source.content
            if content is None or content.truncated:
                continue
            text = content.text
            compact = re.sub(r'\s', '', text)
            codes = re.findall(r'(?:证券代码|股票代码|公司代码)[:：]?(\d{6})', compact)
            if not codes or set(codes) != {requirement.ticker[:6]}:
                continue
            value, locator = None, None
            if requirement.field in FINANCIAL_FIELDS and requirement.period is not None:
                period = requirement.period.isoformat()
                marker = period[:4]+'年'+('半年度报告' if period.endswith('06-30') else '年度报告')
                if marker not in compact or requirement.basis != 'consolidated_actual' or requirement.unit != 'CNY' or requirement.currency not in (None, 'CNY'):
                    continue
                if source.published_at is None or requirement.period > source.published_at.date():
                    continue
                rows = financial_rows([{'page': 1, 'text': text}], period)
                matches = [r for r in rows if r['field'] == FINANCIAL_FIELDS[requirement.field]
                           and r['unit'] == 'CNY' and r['current'] is not None]
                values = {r['current'] for r in matches}
                if len(values) == 1:
                    value = next(iter(values))
                    locator = matches[0]['raw_header']+' | '+matches[0]['raw_row']
            elif requirement.field in TEXT_FIELDS and requirement.unit == 'text':
                match = re.search(r'(?m)^\s*'+TEXT_FIELDS[requirement.field]+r'\s*[:：]\s*([^\n]{1,700})$', text)
                if match:
                    value, locator = match[1].strip(), match[0]
                    if requirement.field == 'list_date':
                        try:
                            listed = date.fromisoformat(value)
                            if listed > source.published_at.date():
                                value = None
                        except ValueError:
                            value = None
            if value is not None:
                candidates.append(QualifiedFieldV1(**requirement.model_dump(), value=value,
                    evidence_id=source.evidence_id, locator=locator[:500],
                    source_content_sha256=content.content_sha256))
        unique = {str(Decimal(f.value)) if f.unit != 'text' else f.value for f in candidates}
        if len(unique) > 1:
            conflicts.append('field_conflict:'+requirement.field)
        if candidates:
            fields.extend(field for field in candidates if field not in fields)
        else:
            rejected.append('field_not_recovered:'+requirement.field)
    return admitted.model_copy(update={'fields': tuple(fields), 'rejections': tuple(dict.fromkeys(rejected)),
                                       'conflicts': tuple(dict.fromkeys(conflicts))})
