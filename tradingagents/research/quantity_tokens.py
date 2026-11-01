"""Quantity grammars rejected outside host-owned numeric references."""
import re
import unicodedata

_CN_NUM = r"[零〇一二两兩三四五六七八九十百千万萬亿億兆壹贰貳叁肆伍陆陸柒捌玖拾佰仟点點半]+"
_CN_QUANTITY = re.compile(
    rf"(?:百分之|千分之|万分之|萬分之){_CN_NUM}|{_CN_NUM}(?:成|元|圆|圓|块|塊|股|吨|噸|辆|輛|倍|个百分点|個百分點|个基点|個基點|万|萬|亿|億)|{_CN_NUM}分之{_CN_NUM}|一半|对半|對半"
)
_EN_NUMBER = r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|trillion|half|quarter)"
_EN_QUANTITY = re.compile(
    rf"\b{_EN_NUMBER}(?:[\s-]+{_EN_NUMBER})*[\s-]*(?:percent|per\s+cent|basis\s+points?|dollars?|yuan|renminbi|cny|rmb|usd|euros?|pounds?|multiples?|times|shares?|tonnes?|tons?|vehicles?|quarters?)\b|\b(?:dollars?|yuan|cny|rmb|usd)\s+{_EN_NUMBER}\b",
    re.I,
)



def _scan_literal(text, path):
    normalized = unicodedata.normalize("NFKC", text)
    # Reject format controls rather than silently rewriting canonical text.
    if any(unicodedata.category(char) in {"Cf", "Cs"} for char in normalized):
        raise ValueError("numeric_literal_unbound", path)
    if (any(char.isnumeric() for char in normalized)
            or _CN_QUANTITY.search(normalized) or _EN_QUANTITY.search(normalized)):
        # isnumeric also covers Chinese numeral chars; exempt ordinary idioms
        # by applying it only to non-CJK numeric characters.
        non_cjk_numeric = any(char.isnumeric() and not ('\u3400' <= char <= '\u9fff')
                              for char in normalized)
        if non_cjk_numeric or _CN_QUANTITY.search(normalized) or _EN_QUANTITY.search(normalized):
            raise ValueError("numeric_literal_unbound", path)
    if "{{" in normalized or "}}" in normalized:
        raise ValueError("numeric_anchor_unknown", path)
