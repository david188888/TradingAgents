"""Reject ambiguous extraction without weakening official conflict checks."""

import pytest

from tradingagents.dataflows.disclosure_documents_v2 import financial_rows


def pages(cells):
    return [{"page": 7, "text": "主要会计数据\n单位：元\n本报告期  上年同期\n营业收入  " + cells},
            {"page": 34, "text": "合并利润表\n单位：元\n2026年半年度  2025年半年度\n其中：营业收入  22,130,027,990.11  19,359,903,999.02"}]


@pytest.mark.parametrize("cells", [
    "22,130,027,990.1119,359,903,999.02    14.31",
    "22130027990.1119359903999.02  14.31",
    "22,130,027,990.11  19,359,903,999.02garbage",
])
def test_glued_or_malformed_key_cells_preserve_consolidated_values(cells):
    gaps = []
    rows = financial_rows(pages(cells), "2026-06-30", gaps=gaps)
    assert gaps == ["official_financial_cells_ambiguous:revenue"]
    assert len(rows) == 1 and rows[0]["page"] == 34
    assert (rows[0]["current"], rows[0]["previous"]) == (
        "22130027990.11", "19359903999.02")


@pytest.mark.parametrize("cells,expected", [
    ("22,130,027,990.11  19,359,903,999.02  14.31", ("22130027990.11", "19359903999.02")),
    ("100.1234  80.5678  24.27%", ("100.1234", "80.5678")),
    ("-100.41-80.23  -25.15%", ("-100.41", "-80.23")),
])
def test_explicit_cells_preserve_precision_and_unambiguous_signs(cells, expected):
    rows = financial_rows(pages(cells), "2026-06-30")
    assert len(rows) == 2
    assert (rows[0]["current"], rows[0]["previous"]) == expected


def test_statement_note_and_not_applicable_change_are_annotations():
    source = pages("-100.41-80.23  不适用")
    source[1]["text"] = source[1]["text"].replace(
        "其中：营业收入  ", "其中：营业收入  七  (61)  ")
    rows = financial_rows(source, "2026-06-30")
    assert len(rows) == 2
    assert rows[1]["previous"] == "19359903999.02"
