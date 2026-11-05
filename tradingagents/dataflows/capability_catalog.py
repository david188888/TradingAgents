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
    CapabilityCard("news_search", "新闻与行业检索", "公司新闻、行业动态、政策与竞争信息",
        "不用于为既有观点寻找支持", {"query": "要核实的具体问题"}, "带日期与来源的检索摘录",
        ("deepseek", "tavily"), "medium", 3, _ALL_ROLES, implemented=True),
    CapabilityCard("disclosure_search", "公告检索", "定期报告、临时公告的原文摘录",
        "不用于非公告类新闻", {"query": "公告主题关键词"}, "官方公告标题与摘录",
        ("cninfo",), "medium", 2, _ALL_ROLES, implemented=True),
    CapabilityCard("shareholder_count", "股东户数", "股东户数及其季度变化",
        "不用于推断主力成本或股价走势", {"query": "留空"}, "按报告期的股东户数序列",
        ("eastmoney",), "low", 1, (_OPERATING, _MARKET), implemented=True),
    CapabilityCard("ir_qa", "投资者互动问答", "投资者提问与公司在互动易/上证e互动的回复",
        "回复是公司表述，不等于已核实事实", {"query": "留空"}, "近期问答记录",
        ("cninfo_irm", "sse_e_interaction"), "low", 1, (_OPERATING, _EVENT), implemented=True),
    CapabilityCard("financials_detail", "财报细项", "核心三表之外的细项科目",
        "不用于重复核心三表", {"ticker": "A股代码", "item": "科目名称"}, "细项科目与报告期",
        ("sina", "tushare"), "low", 1, (_OPERATING,)),
    CapabilityCard("valuation_history", "估值历史", "历史估值区间与当前分位",
        "不是公允价值结论", {"ticker": "A股代码"}, "估值历史序列",
        ("tencent", "tushare"), "low", 1, (_OPERATING, _MARKET)),
    CapabilityCard("northbound_flow", "北向与资金流", "北向持股及主力资金流向",
        "不用于预测短期涨跌", {"ticker": "A股代码"}, "资金流向序列",
        ("eastmoney",), "low", 1, (_MARKET,)),
    CapabilityCard("longhubang", "龙虎榜", "上榜日期、席位与买卖金额",
        "不用于识别特定投资者意图", {"ticker": "A股代码"}, "龙虎榜记录",
        ("eastmoney",), "low", 1, (_MARKET, _EVENT)),
    CapabilityCard("holder_change", "增减持与回购", "股东增减持、回购计划与进度",
        "不用于推断内部人动机", {"ticker": "A股代码"}, "增减持与回购记录",
        ("eastmoney", "cninfo"), "low", 1, (_OPERATING, _EVENT)),
    CapabilityCard("consensus_eps", "一致预期", "机构盈利预测与评级分布",
        "样本有限，不等于完整市场共识", {"ticker": "A股代码"}, "机构预测样本",
        ("ths", "eastmoney"), "low", 1, (_OPERATING,)),
    CapabilityCard("industry_peers", "同行对比", "同行公司报价与估值对比",
        "候选同行不保证业务可比", {"ticker": "A股代码"}, "同行报价样本",
        ("eastmoney", "tencent"), "medium", 1, (_OPERATING, _MARKET)),
    CapabilityCard("wind_enrich", "Wind 增强数据", "指数、宏观序列与风险指标",
        "不用于替代公司财报", {"ticker": "A股代码", "item": "所需指标"}, "Wind 指标序列",
        ("wind",), "high", 1, _ALL_ROLES, requires=("wind_cli",)),
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
