"""Keyless EastMoney fallback for registered A-share index capabilities."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.observability.provenance import capture_vendor_raw

from .coverage import CoveredText, SourceCoverageV1
from .eastmoney import em_get
from .errors import VendorError

EASTMONEY_INDEX_SNAPSHOT_URL = "https://push2.eastmoney.com/api/qt/stock/get"
EASTMONEY_INDEX_HISTORY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


class IndexDataUnavailableError(VendorError):
    """The public index endpoint returned no usable record."""


@dataclass(frozen=True)
class IndexIdentity:
    canonical_code: str
    display_name: str
    eastmoney_secid: str


_INDEXES_BY_CODE = {
    "000001.SH": IndexIdentity("000001.SH", "上证指数", "1.000001"),
    "000016.SH": IndexIdentity("000016.SH", "上证50", "1.000016"),
    "000300.SH": IndexIdentity("000300.SH", "沪深300", "1.000300"),
    "000905.SH": IndexIdentity("000905.SH", "中证500", "1.000905"),
    "399001.SZ": IndexIdentity("399001.SZ", "深证成指", "0.399001"),
}
_INDEX_ALIASES = {
    "SSE_COMPOSITE": "000001.SH",
    "SSE50": "000016.SH",
    "CSI300": "000300.SH",
    "CSI500": "000905.SH",
    "SZSE_COMPONENT": "399001.SZ",
}


def normalize_index_code(index_code: str) -> IndexIdentity:
    """Resolve only explicit registered codes or stable aliases."""
    normalized = str(index_code or "").strip().upper()
    canonical = _INDEX_ALIASES.get(normalized, normalized)
    try:
        return _INDEXES_BY_CODE[canonical]
    except KeyError as exc:
        raise ValueError(
            "unsupported or ambiguous index code; use a registered explicit code "
            "such as 000300.SH or alias CSI300"
        ) from exc


@dataclass(frozen=True)
class IndexSnapshot:
    identity: IndexIdentity
    as_of: str
    last_price: Decimal
    previous_close: Decimal | None
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    volume: Decimal | None
    turnover: Decimal | None
    source_id: str = "eastmoney.index_snapshot"

    def render(self) -> CoveredText:
        coverage = SourceCoverageV1(
            capability="index_snapshot",
            source_id=self.source_id,
            item_count=1,
            completeness="unknown",
            sources=(self.source_id,),
            degradations=("public_endpoint_schema_not_cross_source_verified",),
            as_of=self.as_of,
        )
        columns = (
            "IndexCode,Name,AsOf,LastPrice,PreviousClose,Open,High,Low,Volume,Turnover\n"
            f"{self.identity.canonical_code},{self.identity.display_name},{self.as_of},"
            f"{self.last_price},{_csv_value(self.previous_close)},{_csv_value(self.open_price)},"
            f"{_csv_value(self.high_price)},{_csv_value(self.low_price)},"
            f"{_csv_value(self.volume)},{_csv_value(self.turnover)}"
        )
        text = "\n".join(
            (
                f"# China A-share index snapshot: {self.identity.display_name}",
                "# Source: EastMoney public index snapshot endpoint",
                "# Coverage: point-in-time record; completeness is unknown until cross-source validation.",
                "# Price unit: index points; volume/turnover units are provider-reported and not rescaled.",
                "",
                columns,
            )
        )
        return CoveredText(text, coverage)


@dataclass(frozen=True)
class IndexHistory:
    identity: IndexIdentity
    requested_start: str
    requested_end: str
    rows: tuple[tuple[str, Decimal, Decimal, Decimal, Decimal, Decimal | None, Decimal | None], ...]
    source_id: str = "eastmoney.index_history"

    def render(self) -> CoveredText:
        actual_start = self.rows[0][0]
        actual_end = self.rows[-1][0]
        coverage = SourceCoverageV1(
            capability="index_history",
            source_id=self.source_id,
            requested_start=self.requested_start,
            requested_end=self.requested_end,
            actual_start=actual_start,
            actual_end=actual_end,
            item_count=len(self.rows),
            completeness="unknown",
            sources=(self.source_id,),
            degradations=("trading_calendar_coverage_not_proven",),
            as_of=self.requested_end,
        )
        csv_rows = ["Date,Open,Close,High,Low,Volume,Turnover"]
        csv_rows.extend(
            ",".join(
                (
                    row[0],
                    str(row[1]),
                    str(row[2]),
                    str(row[3]),
                    str(row[4]),
                    _csv_value(row[5]),
                    _csv_value(row[6]),
                )
            )
            for row in self.rows
        )
        text = "\n".join(
            (
                f"# China A-share index history: {self.identity.display_name}",
                "# Source: EastMoney public daily index endpoint",
                "# Price basis: raw index points; no adjustment is implied.",
                "# Coverage: requested calendar coverage is unknown; inspect returned trading dates.",
                "",
                *csv_rows,
            )
        )
        return CoveredText(text, coverage)


class EastMoneyIndexProvider:
    """Public index adapter with injectable fetchers for offline tests."""

    name = "eastmoney"

    def __init__(
        self,
        *,
        fetch_json: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
        fetch_history_json: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ) -> None:
        self._fetch_json = fetch_json or self._fetch_from_eastmoney
        self._fetch_history_json = fetch_history_json or self._fetch_history_from_eastmoney

    def snapshot(self, index_code: str) -> IndexSnapshot:
        identity = normalize_index_code(index_code)
        payload = self._fetch_json(
            {
                "secid": identity.eastmoney_secid,
                "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60",
            }
        )
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(data, Mapping):
            raise IndexDataUnavailableError("EastMoney returned no readable index snapshot data")
        snapshot = IndexSnapshot(
            identity=identity,
            as_of=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
            last_price=_scaled_price(data.get("f43"), required=True, field_name="last price"),
            previous_close=_scaled_price(data.get("f60"), field_name="previous close"),
            open_price=_scaled_price(data.get("f46"), field_name="open price"),
            high_price=_scaled_price(data.get("f44"), field_name="high price"),
            low_price=_scaled_price(data.get("f45"), field_name="low price"),
            volume=_decimal(data.get("f47"), field_name="volume"),
            turnover=_decimal(data.get("f48"), field_name="turnover"),
        )
        _capture_vendor_raw(payload, identity=identity, dataset="index_snapshot")
        return snapshot

    def history(self, index_code: str, start_date: str, end_date: str) -> IndexHistory:
        identity = normalize_index_code(index_code)
        _validate_date_window(start_date, end_date)
        payload = self._fetch_history_json(
            {
                "secid": identity.eastmoney_secid,
                "klt": "101",
                "fqt": "0",
                "beg": start_date.replace("-", ""),
                "end": end_date.replace("-", ""),
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            }
        )
        data = payload.get("data") if isinstance(payload, Mapping) else None
        lines = data.get("klines") if isinstance(data, Mapping) else None
        if not isinstance(lines, list) or not lines:
            raise IndexDataUnavailableError("EastMoney returned no index history rows")
        rows = tuple(_parse_history_row(line) for line in lines if isinstance(line, str))
        if not rows:
            raise IndexDataUnavailableError("EastMoney returned unreadable index history rows")
        _capture_vendor_raw(payload, identity=identity, dataset="index_history")
        return IndexHistory(identity, start_date, end_date, rows)

    @staticmethod
    def _fetch_from_eastmoney(params: Mapping[str, Any]) -> Mapping[str, Any]:
        return em_get(EASTMONEY_INDEX_SNAPSHOT_URL, params=params)

    @staticmethod
    def _fetch_history_from_eastmoney(params: Mapping[str, Any]) -> Mapping[str, Any]:
        return em_get(EASTMONEY_INDEX_HISTORY_URL, params=params)


def get_index_snapshot_eastmoney(
    index_code: str,
    as_of: str | None = None,
) -> CoveredText:
    """Return the latest public snapshot; ``as_of`` is retained for route compatibility."""
    return EastMoneyIndexProvider().snapshot(index_code).render()


def get_index_history_eastmoney(index_code: str, start_date: str, end_date: str) -> CoveredText:
    return EastMoneyIndexProvider().history(index_code, start_date, end_date).render()


def _scaled_price(value: Any, *, field_name: str, required: bool = False) -> Decimal | None:
    amount = _decimal(value, field_name=field_name)
    if amount is None:
        if required:
            raise IndexDataUnavailableError(f"EastMoney returned no usable {field_name}")
        return None
    return amount / Decimal("100")


def _decimal(value: Any, *, field_name: str) -> Decimal | None:
    if value is None or value == "-":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise IndexDataUnavailableError(f"EastMoney returned invalid {field_name}") from exc


def _csv_value(value: Decimal | None) -> str:
    return "" if value is None else str(value)


def _validate_date_window(start_date: str, end_date: str) -> None:
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("index history dates must use YYYY-MM-DD") from exc
    if start.isoformat() != start_date or end.isoformat() != end_date:
        raise ValueError("index history dates must use YYYY-MM-DD")
    if start > end:
        raise ValueError("index history start_date cannot be after end_date")


def _parse_history_row(
    line: str,
) -> tuple[str, Decimal, Decimal, Decimal, Decimal, Decimal | None, Decimal | None]:
    values = [value.strip() for value in line.split(",")]
    if len(values) < 7:
        raise IndexDataUnavailableError("EastMoney returned a malformed index history row")
    date.fromisoformat(values[0])
    open_price = _decimal(values[1], field_name="open price")
    close_price = _decimal(values[2], field_name="close price")
    high_price = _decimal(values[3], field_name="high price")
    low_price = _decimal(values[4], field_name="low price")
    if None in {open_price, close_price, high_price, low_price}:
        raise IndexDataUnavailableError("EastMoney returned missing required index OHLC values")
    return (
        values[0],
        open_price,
        close_price,
        high_price,
        low_price,
        _decimal(values[5], field_name="volume"),
        _decimal(values[6], field_name="turnover"),
    )


def _capture_vendor_raw(
    payload: Mapping[str, Any], *, identity: IndexIdentity, dataset: str
) -> None:
    capture_vendor_raw(
        payload,
        metadata={
            "provider": "eastmoney",
            "dataset": dataset,
            "index_code": identity.canonical_code,
            "source_id": f"eastmoney.{dataset}",
        },
    )
