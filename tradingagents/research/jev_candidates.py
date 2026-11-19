"""Deterministic, conservative candidate selection for Jev conflict checks."""

import re
from collections.abc import Iterable
from unicodedata import normalize

from tradingagents.agents.schemas._insight import EvidenceCard

_FISCAL = re.compile(
    r"(?P<revenue>营业(?:总)?收入|营收|主营收入|(?<![\w])(?:total_revenue|revenue)\b)"
    r"|(?P<profit>归母(?:净)?利润|归属于母公司(?:股东|所有者)的净利润|净利润|净利"
    r"|\b(?:n_income_attr_p|net_income|net profit)\b)"
    r"|(?P<operating_cash>经营活动(?:产生的)?现金流量(?:净额)?|经营(?:性)?现金流"
    r"|\b(?:n_cashflow_act|operating cash flow|cfo)\b)"
    r"|(?P<margin>毛利率|\b(?:gross_margin|gross margin)\b)"
    r"|(?P<debt>资产负债率|有息负债|\b(?:debt_to_assets|interest-bearing debt)\b)"
    r"|(?P<receivables>应收(?:账|帐)款|\b(?:accounts_receiv|receivables)\b)"
    r"|(?P<inventory>存货|库存|\b(?:inventories|inventory)\b)"
)
_PERIOD_ENDS = (
    (r"q1|一季度|第一季度|一季报|-03-31", 1),
    (r"q2|二季度|第二季度|(?:上)?半年(?:度|报)?|中报|h1|-06-30", 2),
    (r"q3|前三季度|三季度|第三季度|三季报|-09-30", 3),
    (r"q4|四季度|第四季度|年度|年报|全年|-12-31", 4),
)
_PERIOD = re.compile(
    r"(?<!\d)(?P<year>(?:19|20)\d{2})(?![\d万亿元%]|[.,]\d)"
    r"(?:\s*(?:年\s*)?(?:"
    + "|".join(f"(?P<end{quarter}>{patterns})" for patterns, quarter in _PERIOD_ENDS)
    + r")|年)?|(?P<fiscal_year>\bfy\s*(?:19|20)\d{2})(?!\d)"
)
_WORD = re.compile(r"[a-z][a-z0-9_]{1,}|(?<!\d)\d{6}(?!\d)")
_CJK = re.compile(r"[\u3400-\u9fff]+")
_REF = re.compile(r"\[[en]\d+\]")


def _features(text: str) -> tuple[set[str], set[tuple[int, int]], set[str]]:
    text = normalize("NFKC", text).casefold()
    fiscal = {match.lastgroup for match in _FISCAL.finditer(text) if match.lastgroup}
    periods = set()
    for match in _PERIOD.finditer(text):
        if year := match['year']:
            # 0 denotes a year without a quarter; matching endpoints is a ranking signal only.
            end = next((q for _, q in _PERIOD_ENDS if match[f'end{q}']), 0)
            periods.add((int(year), end))
        else:
            periods.add((int(match['fiscal_year'][-4:]), 4))
    remaining = _REF.sub(' ', _PERIOD.sub(' ', _FISCAL.sub(' ', text)))
    terms = set(_WORD.findall(remaining))
    for run in _CJK.findall(remaining):
        terms.update(run[i:i + 2] for i in range(len(run) - 1))
    return fiscal, periods, terms


def select_jev_candidates(
    evidence: Iterable[EvidenceCard],
    *,
    cited: Iterable[str],
    claim: str,
    reasoning: str,
    limit: int = 30,
) -> tuple[tuple[EvidenceCard, ...], bool]:
    """Preserve cited refs outside the cap if necessary; flag any omitted card as partial.

    Fiscal aliases and shared reporting windows promote relevant facts regardless of
    direction or amount. Remaining lexical overlap is a proxy for entity similarity.
    This is a ranking heuristic only; it never decides whether an Insight is clear.
    """
    cited = set(cited)
    mandatory, other = [], []
    for card in evidence:
        (mandatory if card.ref in cited else other).append(card)
    mandatory.sort(key=lambda card: (card.ref, card.fact_id))
    slots = max(0, limit - len(mandatory))
    if len(other) <= slots:
        other.sort(key=lambda card: (card.ref, card.fact_id))
        return (*mandatory, *other), False
    if not slots:
        return tuple(mandatory), True

    fiscal, periods, terms = _features(f'{claim}\n{reasoning}')

    def rank(card: EvidenceCard):
        card_fiscal, card_periods, card_terms = _features(card.text)
        metric_overlap = len(fiscal & card_fiscal)
        lexical_overlap = len(terms & card_terms)
        period_match = max((
            2 if end and end == card_end else 1 if not end or not card_end else 0
            for year, end in periods for card_year, card_end in card_periods if year == card_year
        ), default=0)
        return (-period_match if metric_overlap else 0, not metric_overlap,
                -lexical_overlap, -period_match, -metric_overlap, card.ref, card.fact_id)

    return (*mandatory, *sorted(other, key=rank)[:slots]), True
