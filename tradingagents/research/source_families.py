"""Finite, code-owned admitted source families shared by native consumers."""

IDENTITY_SOURCES = frozenset({"tushare.stock_basic", "eastmoney.stock_profile", "sina.company_profile"})
FINANCIAL_SOURCES = frozenset({"tushare.financial_statements", "sina.financial_statements"})
PRICE_SOURCES = frozenset({"tushare.adjusted_daily", "tencent.qfq", "tencent.sina_adjusted_daily"})
