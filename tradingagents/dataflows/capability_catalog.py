"""Model-facing capability catalog for bounded specialist evidence supplements.

Cards describe research questions, not vendors: models request a card id with
one ``query`` and a gap reason; the host injects the run ticker, routes
``backends``, qualifies results and assigns references. Backends never reach
the model-facing compact view.
"""

from dataclasses import asdict, dataclass

from tradingagents.agents.schemas._verification_plan import canonical_sha256

CATALOG_SCHEMA_VERSION = "capability-catalog-v1"

_OPERATING, _EVENT, _MARKET = "operating_quality", "event_context", "market_context"
_ALL_ROLES = (_OPERATING, _EVENT, _MARKET)


@dataclass(frozen=True)
class CapabilityCard:
    id: str
    title: str
    solves: str
    not_for: str
    inputs: dict[str, str]
    returns: str
    backends: tuple[str, ...]
    cost: str
    max_calls_per_run: int
    roles: tuple[str, ...]
    requires: tuple[str, ...] = ()
    prefetch_only: bool = False
    implemented: bool = False


CAPABILITY_CARDS = (
    # Prefetched by the minimum evidence chain; documented here, never requestable.
    CapabilityCard("security_identity", "证券身份与简介", "公司名称、交易所、上市日期、主营简介",
        "不用于判断经营质量", {"ticker": "A股代码"}, "已核实身份字段",
        ("eastmoney", "sina", "tushare"), "low", 0, _ALL_ROLES, prefetch_only=True),
    CapabilityCard("core_financials", "核心三表", "营收、利润、现金流等核心科目",
        "不用于补充细项科目", {"ticker": "A股代码"}, "合并口径报表字段",
        ("sina", "tushare"), "low", 0, (_OPERATING,), prefetch_only=True),
    CapabilityCard("adjusted_prices", "复权行情", "价格走势、成交与区间统计",
        "不用于预测未来价格", {"ticker": "A股代码"}, "复权日线与区间统计",
        ("tencent", "sina", "tushare"), "low", 0, (_MARKET,), prefetch_only=True),
    CapabilityCard("valuation_snapshot", "估值快照", "当前市盈率、市净率、市值",
        "不是公允价值结论", {"ticker": "A股代码"}, "带时间戳的估值快照",
        ("tencent", "tushare"), "low", 0, (_OPERATING, _MARKET), prefetch_only=True),
    # Requestable after an explicit gap.
    CapabilityCard("disclosure_search", "公告检索", "按标题关键词检索定期报告与临时公告",
        "不用于非公告类新闻；只出现在正文里的词不会命中",
        {"query": "空格分隔的 1–3 个标题关键词（如：增资扩股 进展公告）"},
        "按标题关键词检索到的公告标题、日期与链接",
        ("cninfo",), "medium", 2, _ALL_ROLES, implemented=True),
    CapabilityCard("shareholder_count", "股东户数", "股东户数及其季度变化",
        "不用于推断主力成本或股价走势", {"query": "留空"}, "按报告期的股东户数序列",
        ("eastmoney",), "low", 1, (_OPERATING, _MARKET), implemented=True),
    CapabilityCard("ir_qa", "投资者互动问答", "投资者提问与公司在互动易/上证e互动的回复",
        "回复是公司表述，不等于已核实事实", {"query": "留空"}, "近期问答记录",
        ("cninfo_irm", "sse_e_interaction"), "low", 1, (_OPERATING, _EVENT), implemented=True),
    CapabilityCard("financials_detail", "财报细项", "核心三表之外的细项科目（最小证据包在 detail policy 开启时预取）",
        "不用于重复核心三表或预取已覆盖的细项", {"query": "留空"}, "不单独派发；细项已由最小证据包提供",
        ("sina", "tushare"), "low", 0, (_OPERATING,), prefetch_only=True),
    CapabilityCard("valuation_history", "估值历史", "最近60个交易日的日频 PE/PB/PS/PCF 序列",
        "不是公允价值结论，也不计算分位", {"query": "留空"}, "最近60个交易日估值日频记录",
        ("baostock", "tushare"), "low", 1, (_OPERATING, _MARKET), implemented=True),
    CapabilityCard("northbound_flow", "北向资金（当日快照）", "沪深股通当日净买入（全市场累计，亿元）",
        "不是个股归因，也不能用于历史日期", {"query": "留空"}, "当日沪股通/深股通累计净买入与最后更新时间",
        ("ths",), "low", 1, (_MARKET,), implemented=True),
    CapabilityCard("longhubang", "龙虎榜", "上榜日期、上榜原因与净买入金额",
        "不用于识别特定投资者意图", {"query": "留空"}, "近30日上榜记录（不含席位明细）",
        ("eastmoney",), "low", 1, (_MARKET, _EVENT), implemented=True),
    CapabilityCard("holder_change", "增减持披露", "股东与高管的增减持公告记录",
        "不用于推断内部人动机", {"query": "留空"}, "近一年披露的增减持记录（不含回购）",
        ("eastmoney",), "low", 1, (_OPERATING, _EVENT), implemented=True),
    CapabilityCard("consensus_eps", "一致预期", "机构一致预期 EPS 样本",
        "样本有限，不等于完整市场共识，也不是已披露业绩", {"query": "留空"}, "按年度的机构预测样本",
        ("ths",), "low", 1, (_OPERATING,), implemented=True),
    CapabilityCard("industry_peers", "同行对比", "同行候选报价与估值（最小证据包已预取）",
        "不接受模型补证；候选同行不保证业务可比", {"query": "留空"}, "不单独派发；同行样本已由最小证据包提供",
        ("eastmoney", "tencent"), "medium", 0, (_OPERATING, _MARKET), prefetch_only=True),
    CapabilityCard("wind_enrich", "Wind 风险指标", "Beta、年化波动率、最大回撤、夏普比率（1 年窗口）",
        "不是未来收益预测，也不替代公司财报", {"query": "留空"}, "Wind 风险指标快照（需本机 Wind CLI）",
        ("wind",), "high", 1, _ALL_ROLES, requires=("wind_cli",), implemented=True),
)


def load_capability_catalog(*, role=None, available_requirements=frozenset()):
    """Cards a model may request: implemented, credential-satisfied and role-visible."""
    return tuple(card for card in CAPABILITY_CARDS
                 if card.implemented and not card.prefetch_only
                 and set(card.requires) <= set(available_requirements)
                 and (role is None or role in card.roles))


def compact_capability_cards(cards):
    return [{"id": c.id, "title": c.title, "solves": c.solves, "not_for": c.not_for,
             "inputs": c.inputs, "cost": c.cost} for c in cards]


def catalog_identity_digest(cards):
    return canonical_sha256({"version": CATALOG_SCHEMA_VERSION,
                             "cards": [asdict(card) for card in sorted(cards, key=lambda c: c.id)]})
