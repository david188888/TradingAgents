"""Normalize evidence-backed calendar dates without relaxing quantity validation."""

import re
import unicodedata
from collections.abc import Iterable, Iterator
from datetime import date

_DIGITS = '零一二三四五六七八九'
_TO_CHINESE = str.maketrans('0123456789', _DIGITS)
_FROM_CHINESE = str.maketrans(_DIGITS + '〇', '01234567890')


def _chinese_number(value: int) -> str:
    tens, ones = divmod(value, 10)
    if not tens:
        return _DIGITS[ones]
    return (_DIGITS[tens] if tens > 1 else '') + '十' + (_DIGITS[ones] if ones else '')


_CHINESE_VALUES = {_chinese_number(value): value for value in range(1, 32)}
_DATE = re.compile(
    r'(?P<iso>[0-9]{4}-[0-9]{2}-[0-9]{2})'
    r'|(?P<year>[0-9]{4})年(?P<month>[0-9]{1,2})月(?P<day>[0-9]{1,2})日'
    rf'|(?P<cn_year>[{_DIGITS}〇]{{4}})年(?P<cn_month>[一二三四五六七八九十]{{1,2}})月'
    r'(?P<cn_day>[一二三四五六七八九十]{1,3})日'
)
_TOKEN_EDGE = re.compile(r'[A-Za-z_]')
_REFERENCE = re.compile(r'\[[ENI][0-9]+\]')
_OPERATOR = r'[-+‐‑‒–—−~～/×÷=]'
_NUMERIC_EDGE = rf'[\d{_DIGITS}〇两兩十百千万億亿半]'
_LEFT_CONTEXT = re.compile(
    rf'{_OPERATOR}\Z|(?:[$¥€£]|\b(?:CNY|RMB|USD)|人民币|美元)\s*\Z'
    rf'|(?:{_NUMERIC_EDGE}|[年月日号])\s*\)?\s*(?:{_OPERATOR}|至|到)\s*\(?\s*\Z'
    rf'|{_NUMERIC_EDGE}[.,:]\Z',
    re.I,
)
_RIGHT_CONTEXT = re.compile(
    rf'{_OPERATOR}|[.,:](?={_NUMERIC_EDGE})'
    rf'|\s*\)?\s*(?:{_OPERATOR}|至|到)\s*\(?\s*{_NUMERIC_EDGE}',
)
# Don't hide the last number in an ISO-shaped quantity recognized by _QUANTITY.
_ISO_QUANTITY_SUFFIX = re.compile(
    r'\s*(?:%|亿元|万元|亿|万|元|美元|人民币|倍|股|吨|辆|个百分点|基点'
    r'|percent|basis\s+points?|dollars?|yuan|shares?|times|million|billion)',
    re.I,
)


def _calendar_dates(text: str) -> Iterator[tuple[re.Match[str], date]]:
    for match in _DATE.finditer(text):
        start, end = match.span()
        # Match the literal date, but inspect its context as the compiler does:
        # aliases cannot separate a quantity and its unit or range delimiter.
        left = unicodedata.normalize('NFKC', _REFERENCE.sub('', text[:start]))
        right = unicodedata.normalize('NFKC', _REFERENCE.sub('', text[end:]))
        if any(char.isnumeric() or _TOKEN_EDGE.fullmatch(char) for char in (left[-1:], right[:1])):
            continue
        if _LEFT_CONTEXT.search(left) or _RIGHT_CONTEXT.match(right):
            continue
        try:
            if match['iso']:
                if _ISO_QUANTITY_SUFFIX.match(right):
                    continue
                value = date.fromisoformat(match['iso'])
            elif match['year']:
                value = date(int(match['year']), int(match['month']), int(match['day']))
            else:
                value = date(int(match['cn_year'].translate(_FROM_CHINESE)),
                             _CHINESE_VALUES[match['cn_month']], _CHINESE_VALUES[match['cn_day']])
        except (KeyError, ValueError):
            continue
        yield match, value


def normalize_supported_dates(text: str, evidence_texts: Iterable[str], *, analysis_date: date) -> str:
    """Rewrite standalone full dates attested in cited text or equal to analysis_date.

    Callers supply only already-qualified evidence cited by this item. Unsupported
    dates, report periods, ranges, and non-date quantities are left untouched.
    """
    candidates = list(_calendar_dates(text))
    missing = {value for _, value in candidates if value < analysis_date}
    supported = {analysis_date}
    if missing:
        for evidence in evidence_texts:
            found = {value for _, value in _calendar_dates(evidence)} & missing
            supported.update(found)
            missing.difference_update(found)
            if not missing:
                break

    parts = []
    offset = 0
    for match, value in candidates:
        if value not in supported:
            continue
        year = f'{value.year:04d}'.translate(_TO_CHINESE)
        # 零 is a CJK ideograph; the numeric scanner rejects the symbol 〇.
        parts.extend((text[offset:match.start()],
                      f'{year}年{_chinese_number(value.month)}月{_chinese_number(value.day)}日'))
        offset = match.end()
    parts.append(text[offset:])
    return ''.join(parts)
