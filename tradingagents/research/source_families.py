"""Finite, code-owned admitted source families shared by native consumers."""

IDENTITY_SOURCES = frozenset({"tushare.stock_basic", "eastmoney.stock_profile", "sina.company_profile"})
FINANCIAL_SOURCES = frozenset({"tushare.financial_statements", "sina.financial_statements"})
# financial-detail-fields-v1 keeps the six-field baseline sources untouched and
# stores one additional evidence record per statement table.
FINANCIAL_DETAIL_SOURCES = frozenset({"tushare.financial_detail", "sina.financial_detail"})
PRICE_SOURCES = frozenset({"tushare.adjusted_daily", "tencent.qfq", "tencent.sina_adjusted_daily"})
BODY_SOURCES = frozenset({"cninfo.document_excerpt"})
OPERATING_SOURCES = frozenset({"cninfo.operating_detail"})
