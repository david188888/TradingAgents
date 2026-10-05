"""Human-readable local check labels shared by deterministic exports."""

from decimal import Decimal

CHECK_LABELS = {"operating_disclosures": "经营披露依据", "cash_conversion": "现金流桥核对", "valuation_context": "估值补充背景"}
CHECK_STATUS = {"passed": "所需证据已核对", "unavailable": "所需证据不足", "conflict": "数据冲突，待核查"}
OUTCOME_LABELS = {"evidence_sufficient": "证据子问题已回答", "risk_supported": "数据支持所列风险", "future_observation": "保留未来观察", "unresolved": "尚未解决"}


def observation_value(item):
    value = Decimal(item.value)
    unit = item.unit
    if unit == "CNY":
        scale, unit = (Decimal(100000000), "亿元") if abs(value) >= 100000000 else (Decimal(10000), "万元") if abs(value) >= 10000 else (Decimal(1), "元")
        value /= scale
    elif unit == "CNY/share":
        unit = "元/股"
    display = format(value, ".4f").rstrip("0").rstrip(".")
    return (display or "0")+" "+unit
