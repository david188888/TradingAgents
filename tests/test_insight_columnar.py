"""Offline checks for the lossless Insight catalog prompt representation."""

import json
from copy import deepcopy
from types import MappingProxyType

from tradingagents.research.insight_columnar import columnar_catalog


def _wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _decode(table):
    missing = table.get('missing', {})
    return [
        {key: value for c, (key, value) in enumerate(zip(table['columns'], cells, strict=False))
         if c not in missing.get(str(r), ())}
        for r, cells in enumerate(table['rows'])
    ]


def test_catalog_tables_round_trip_and_reduce_compact_json():
    text = '公司披露的原句。'
    context = {
        'evidence': [{'ref': f'E{i}', 'text': text, 'source_ids': [f'S{i}'],
                      'limitations': ['未经审计'], 'new_field': {'tags': [None, False]}} for i in range(9, 0, -1)],
        'sources': [{'evidence_id': f'S{i}', 'source_name': '年报', 'source_kind': 'filing',
                     'usable_as_of': '2026-03-31', 'public_url': None} for i in range(1, 10)],
        'numbers': [{'ref': f'N{i}', 'description': f'营业收入 {i}.00 元', 'limitations': []} for i in range(1, 10)],
        'source_passages': [{'evidence_id': f'S{i}', 'text': text,
                             'start': i, 'end': i + len(text)} for i in range(1, 10)],
        'passage_scope': 'Selected exact excerpts.',
        'extra': {'evidence': [{'ref': 'E1'}], 'enabled': False},
    }
    before = deepcopy(context)
    original_wire = _wire(context)
    encoded_wire = _wire(columnar_catalog(MappingProxyType(context)))
    assert len(encoded_wire.encode()) < len(original_wire.encode())
    decoded = json.loads(encoded_wire)
    for field in ('evidence', 'sources', 'numbers', 'source_passages'):
        decoded[field] = _decode(decoded[field])
    assert decoded == json.loads(original_wire)
    assert context == before


def test_sparse_columns_distinguish_absent_cells_from_explicit_null():
    rows = [{'ref': f'E{i}', 'source_ids': ['S1'], 'text': '原文'} for i in range(12)]
    rows[0]['alpha'] = None
    rows[1]['zeta'] = None
    rows[2].update(alpha=[], zeta=False)
    rows[3]['alpha'] = ''
    result = columnar_catalog({'evidence': rows})
    table = result['evidence']
    assert table['columns'] == ['ref', 'source_ids', 'text', 'alpha', 'zeta']
    assert table['missing'] == {'1': [3]}
    assert table['rows'][0][-1:] == [None]
    assert table['rows'][1][-2:] == [None, None]
    assert len(table['rows'][3]) == 4
    assert _decode(table) == rows
    reordered = [dict(reversed(list(row.items()))) for row in rows]
    assert columnar_catalog({'evidence': reordered}) == result


def test_keeps_non_tables_and_tables_that_would_grow_in_compact_json():
    context = {
        'evidence': [{'ref': 'E1'}, {'ref': 'E2'}],
        'sources': {'evidence': [{'ref': 'E1'}]},
        'numbers': [],
        'source_passages': None,
    }
    assert columnar_catalog(context) == context
    del context['source_passages']
    assert columnar_catalog(context) == context
