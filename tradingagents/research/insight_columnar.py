"""Lossless columnar encoding for model-facing Insight catalog rows."""

import json
from collections import Counter
from collections.abc import Mapping
from typing import Any

COLUMNAR_CATALOG_INSTRUCTION = (
    'For catalog tables, read each row array in columns order. Unlisted trailing cells are absent. '
    'The optional missing map lists absent column indices by row index (both zero-based); '
    'ignore those null placeholders. Other nulls are explicit. Object rows are unchanged.'
)


def columnar_catalog(context: Mapping[str, Any]) -> dict[str, Any]:
    """Encode only top-level catalog row lists, without mutating the context.

    Keep the input row order; order columns by decreasing field frequency and
    then by field name, so commonly omitted fields tend to be trailing. Both
    formats can coexist: use a table only when its compact JSON is smaller.
    """
    result = dict(context)
    for field in ('evidence', 'sources', 'numbers', 'source_passages'):
        rows = context.get(field)
        if not isinstance(rows, list) or len(rows) < 2 or not all(isinstance(row, dict) for row in rows):
            continue

        counts = Counter(key for row in rows for key in row)
        columns = sorted(counts, key=lambda key: (-counts[key], key))
        values, missing = [], {}
        for row_index, row in enumerate(rows):
            cells = [row.get(key) for key in columns]
            absent = [index for index, key in enumerate(columns) if key not in row]
            while absent and absent[-1] == len(cells) - 1:
                cells.pop()
                absent.pop()
            if absent:
                missing[str(row_index)] = absent
            values.append(cells)

        table = {'columns': columns, 'rows': values}
        if missing:
            table['missing'] = missing
        options = {'ensure_ascii': False, 'separators': (',', ':')}
        if len(json.dumps(table, **options)) < len(json.dumps(rows, **options)):
            result[field] = table
    return result
