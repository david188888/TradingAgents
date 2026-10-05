"""Version-four direct, bounded valuation sources; earlier collectors stay intact."""
import math
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tradingagents.dataflows.native_disclosures import DisclosureSources
from tradingagents.dataflows.native_qualification import NativeSourceUnavailable, api_date
from tradingagents.dataflows.tushare_price_history import settled_sessions
from tradingagents.execution.budget import BudgetExhausted
from tradingagents.research.evidence_freeze import CapabilityStatus, FrozenCapability

CAP_VALUATION = "valuation"
SNAPSHOT_SOURCE = "tencent.valuation_snapshot"
HISTORY_SOURCE = "tushare.valuation_history"


def finite_number(value, *, positive=False):
    if isinstance(value, bool):
        raise NativeSourceUnavailable("valuation_number_invalid")
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise NativeSourceUnavailable("valuation_number_invalid") from None
    if not math.isfinite(number) or (positive and number <= 0):
        raise NativeSourceUnavailable("valuation_number_invalid")
    return number


def qualify_snapshot(text, *, ts_code, last_session):
    symbol = ts_code[-2:].lower() + ts_code[:6]
    matches = re.findall(r'v_' + re.escape(symbol) + r'="([^"]+)"', text)
    if len(matches) != 1:
        raise NativeSourceUnavailable("valuation_security_mismatch")
    fields = matches[0].split("~")
    if len(fields) < 53 or fields[2] != ts_code[:6]:
        raise NativeSourceUnavailable("valuation_security_mismatch")
    try:
        observed = datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    except ValueError:
        raise NativeSourceUnavailable("valuation_timestamp_invalid") from None
    if observed.date().isoformat() != last_session:
        raise NativeSourceUnavailable("valuation_quote_not_last_settled_session")
    # Zero turnover is not a proven settled market observation.
    finite_number(fields[37], positive=True)
    result = {"ts_code": ts_code, "name": fields[1], "as_of": last_session,
        "quote_timestamp": observed.isoformat(), "price": finite_number(fields[3], positive=True),
        "total_market_cap_yi": finite_number(fields[45], positive=True), "currency": "CNY"}
    for field, key in ((39, "pe_ttm"), (46, "pb")):
        number = finite_number(fields[field]) if fields[field] else None
        result[key] = number if number is not None and number > 0 else None
    if result["pe_ttm"] is None and result["pb"] is None:
        raise NativeSourceUnavailable("valuation_multiples_unavailable")
    return result


def qualify_history(rows, *, ts_code, start, end):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise NativeSourceUnavailable("valuation_history_shape_invalid")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or row.get("ts_code") != ts_code:
            raise NativeSourceUnavailable("valuation_security_mismatch")
        day = api_date(row.get("trade_date"))
        if not start <= day <= end or day in seen:
            raise NativeSourceUnavailable("valuation_history_date_invalid")
        seen.add(day)
        item = {"date": day}
        for key in ("pe_ttm", "pb"):
            item[key] = finite_number(row[key]) if row.get(key) is not None else None
        result.append(item)
    if end not in seen:
        raise NativeSourceUnavailable("valuation_history_latest_session_missing")
    return sorted(result, key=lambda item: item["date"])


class ValuationSources(DisclosureSources):
    def __init__(self, request, run_id, session, fetch):
        # Validate v4-only overrides separately, never broaden old collectors.
        from copy import deepcopy
        from types import SimpleNamespace
        config = deepcopy(request.effective_config)
        overrides = config.get("evidence_source_vendors", {})
        self.valuation_vendors = overrides.pop("valuation", ["tencent", "tushare"])
        if (not isinstance(self.valuation_vendors, list)
                or any(not isinstance(v, str) or v not in {"tencent", "tushare"} for v in self.valuation_vendors)
                or len(set(self.valuation_vendors)) != len(self.valuation_vendors)):
            raise ValueError("invalid_native_source_configuration")
        super().__init__(SimpleNamespace(**{**vars(request), "effective_config": config}), run_id, session, fetch)
        excluded = config.get("evidence_source_exclusions", [])
        self.valuation_vendors = [v for v in self.valuation_vendors if v not in excluded]
        self.last_session = None

    def _calendar(self, inputs, ts_code, start):
        rows = super()._calendar(inputs, ts_code, start)
        if rows is not None:
            self.last_session = settled_sessions(rows, start=start, cutoff=inputs.cutoff,
                captured_at=datetime.now(ZoneInfo("UTC")))[-1]
        return rows

    def _valuation(self, inputs, ts_code, identity):
        sources, gaps = [], []
        if identity is None or self.last_session is None:
            gaps.append("valuation_identity_or_calendar_missing")
        elif inputs.cutoff != datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat():
            gaps.append("valuation_historical_vintage_unverified")
        else:
            if "tencent" in self.valuation_vendors:
                def query():
                    symbol = ts_code[-2:].lower()+ts_code[:6]
                    response = self.session.get("https://qt.gtimg.cn/q="+symbol,
                        headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
                    if response.status_code != 200:
                        raise NativeSourceUnavailable("valuation_http_unavailable")
                    return qualify_snapshot(response.content.decode("gb18030"),
                        ts_code=ts_code, last_session=self.last_session)
                try:
                    snapshot = self._attempt(CAP_VALUATION, "tencent", "valuation.snapshot.v4", query)
                except BudgetExhausted:
                    snapshot = None
                    gaps.append("valuation_budget_exhausted")
                if snapshot is not None:
                    self.evidence(inputs, CAP_VALUATION, SNAPSHOT_SOURCE, snapshot,
                        published=snapshot["as_of"], public_url="https://qt.gtimg.cn/q="+ts_code[-2:].lower()+ts_code[:6])
                    sources.append(SNAPSHOT_SOURCE)
            if "tushare" in self.valuation_vendors:
                start = (date.fromisoformat(inputs.cutoff)-timedelta(days=1095)).isoformat()
                def history_query():
                    rows = self.tushare("daily_basic", "ts_code,trade_date,pe_ttm,pb", ts_code=ts_code,
                        start_date=start.replace("-", ""), end_date=self.last_session.replace("-", ""))
                    return {"ts_code": ts_code, "as_of": self.last_session, "currency": "CNY",
                        "capture_scope": "current_cutoff_retrospective_history",
                        "rows": qualify_history(rows, ts_code=ts_code, start=start, end=self.last_session)}
                try:
                    history = self._attempt(CAP_VALUATION, "tushare", "valuation.history.v4", history_query)
                except BudgetExhausted:
                    history = None
                    gaps.append("valuation_budget_exhausted")
                if history is not None:
                    self.evidence(inputs, CAP_VALUATION, HISTORY_SOURCE, history, published=self.last_session)
                    sources.append(HISTORY_SOURCE)
            if SNAPSHOT_SOURCE not in sources:
                gaps.append("valuation_snapshot_unavailable")
            if HISTORY_SOURCE not in sources:
                gaps.append("valuation_history_unavailable")
        inputs.capabilities.append(FrozenCapability(capability=CAP_VALUATION, required=False,
            status=CapabilityStatus.PARTIAL if sources and gaps else CapabilityStatus.QUALIFIED if sources else CapabilityStatus.UNAVAILABLE,
            sources=tuple(sources), reason="qualified_valuation_fields" if sources else "no_qualified_valuation_fields",
            degradations=tuple(gaps), detail={"attempts": self.attempts.get(CAP_VALUATION, [])}))

    def _prices(self, inputs, ts_code, identity):
        # V4 prioritizes valuation before optional document supplements.
        from tradingagents.dataflows.native_sources import NativeSources
        NativeSources._prices(self, inputs, ts_code, identity)
        try:
            self._valuation(inputs, ts_code, identity)
        except BudgetExhausted:
            inputs.capabilities.append(FrozenCapability(capability=CAP_VALUATION, required=False,
                status=CapabilityStatus.UNAVAILABLE, reason="valuation_budget_exhausted",
                degradations=("valuation_budget_exhausted",)))
        self._documents(inputs, ts_code, identity)
