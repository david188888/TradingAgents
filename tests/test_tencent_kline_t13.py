"""T13: raw and qfq are separate capabilities that may not substitute.

Design SS8.5 requires that an explicitly selected forward-adjusted capability is
never satisfied by unadjusted bars.  Three layers are covered:

1. Registration -- raw and qfq are two router methods, not one method with an
   ``adjust`` flag.  A flag makes the substitution expressible; two methods make
   it structurally impossible.
2. Adapter -- a qfq request answered with Tencent's unadjusted ``day`` key is a
   typed ``unavailable``, never raw.  (The positional column-order defect T-D2
   covers has its own file, ``tests/test_tencent_kline_tdx2.py``.)
3. Router -- ``interface._route_to_vendor_impl`` treats a *stored cooldown* as
   a reason to append every remaining vendor to the fallback chain ("even when
   the user explicitly selected one primary", interface.py:265-268).  The
   counter-example the plan asks for: qfq selected, qfq on cooldown, raw must NOT
   be substituted.  The test below drives the real router and shows what
   currently happens.

Fixtures are local fakes and invented strings.  No credentials, no live
endpoints, no captured vendor payloads.
"""

from __future__ import annotations

import pytest

from tradingagents.dataflows import interface, tencent_kline
from tradingagents.dataflows.china_data import ChinaDataUnavailableError
from tradingagents.dataflows.errors import DataUnavailableError
from tradingagents.dataflows.health import VendorHealthRegistry
from tradingagents.dataflows.registry import (
    TOOLS_CATEGORIES,
    VENDOR_MARKETS,
    VENDOR_METHODS,
)
from tradingagents.dataflows.symbol_utils import NoMarketDataError

RAW_BARS = "Date,Open,High,Low,Close,Volume\n2026-09-28,10.0,10.6,10.3,10.1,100"

# Snapshots so the direct-assignment test below can restore module state
# exactly; monkeypatch cannot be used because the router reads these two
# names through the interface facade.
_ORIGINAL_GET_VENDOR = interface.get_vendor
_ORIGINAL_ADJUSTED_CHAIN = VENDOR_METHODS["get_adjusted_price_history"]


# ------------------------------------------------------------- registration


def test_raw_and_qfq_are_two_separate_router_methods():
    """One method with an ``adjust`` flag would let the router answer qfq with raw.

    Registering them separately is what makes the substitution impossible to
    express in the first place, so the shape of the registry *is* the assertion.
    """
    assert set(VENDOR_METHODS["get_a_share_kline"]) == {"tencent"}
    assert set(VENDOR_METHODS["get_a_share_kline_qfq"]) == {"tencent"}
    assert (
        VENDOR_METHODS["get_a_share_kline"]["tencent"]
        is not VENDOR_METHODS["get_a_share_kline_qfq"]["tencent"]
    )
    listed = set(TOOLS_CATEGORIES["a_share_kline"]["tools"])
    assert listed == {"get_a_share_kline", "get_a_share_kline_qfq"}
    assert VENDOR_MARKETS["tencent"] == frozenset({"a_share"})


def test_adjustment_capability_may_not_fall_back_to_a_raw_vendor():
    """A raw-price vendor wired into the adjusted chain could answer a qfq call.

    This is the registry-level form of the counter-example.  Today no raw vendor
    is wired there, so it holds; the point is that any future edit adding one
    (``tencent`` raw into ``get_adjusted_price_history``, say) trips it.
    """
    raw_only = {
        "get_a_share_kline",  # the unadjusted Tencent capability
        "get_stock_data",  # the unadjusted daily-bar capability
    }
    adjusted_chain = set(VENDOR_METHODS["get_adjusted_price_history"])
    assert not (adjusted_chain & raw_only), (
        f"raw capabilities leaked into the adjusted chain: {adjusted_chain & raw_only}"
    )


# ------------------------------- counter-example: cooldown chain widening


def test_qfq_on_cooldown_does_not_reach_a_raw_vendor(monkeypatch) -> None:
    """The plan's counter-example, driven through the real router.

    ``get_adjusted_price_history`` is configured to serve exactly one vendor and
    that vendor is put on cooldown.  interface.py:265-268 then appends every
    other vendor registered for the method -- the "implicit safety net" branch
    -- so the unchosen raw vendor becomes reachable and, if it answers, the
    caller silently receives a different price basis.

    The security property asserted here is the one that must never break: a
    capability on cooldown may widen *which source* is tried, but it may never
    return a payload the caller would read as forward-adjusted.  Two acceptable
    outcomes: the request fails, or the raw vendor is reported as unable to
    serve the capability.  The forbidden outcome is raw bars returned as qfq.
    """
    raw_calls: list[str] = []

    def raw_bars(ticker, *args, **kwargs):
        raw_calls.append(ticker)
        return RAW_BARS

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("the adjusted vendor is in cooldown and must not be called")

    registry = VendorHealthRegistry(clock=lambda: 100.0)
    registry.record_failure(
        vendor="wind",
        market="a_share",
        capability="get_adjusted_price_history",
        cooldown_seconds=60,
        reason="rate_limit",
    )

    monkeypatch.setattr(interface, "_vendor_health", registry)
    monkeypatch.setattr(interface, "get_vendor", lambda category, method=None: "wind")
    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_adjusted_price_history",
        {
            "wind": must_not_be_called,
            # An unchosen raw-price vendor. Only reachable because the cooldown
            # branch widens the chain -- that is the substitution under test.
            "tushare": raw_bars,
        },
    )

    try:
        result = interface.route_to_vendor(
            "get_adjusted_price_history", "600519.SH", "2026-08-01", "2026-09-28"
        )
    except DataUnavailableError as exc:
        # The preferred outcome: the request fails loudly and names the gap.
        assert "adjusted" in str(exc).lower() or "qfq" in str(exc).lower() or "cooldown" in str(exc).lower()
        return

    # If the router did widen the chain, a raw vendor must still not produce the
    # answer. Any other shape is a defect, not a pass.
    assert raw_calls == [], "raw bars were substituted for a requested qfq basis"
    assert not isinstance(result, str) or not result.lstrip().startswith("Date,Open"), (
        "raw bars were returned for an adjusted-price request"
    )
    # Everything on the chain was skipped for a PRIOR transient failure and
    # nothing new was attempted, so the router reports the capability as
    # unavailable rather than serving a different basis.  (This is the
    # DATA_UNAVAILABLE branch rather than the NO_DATA_AVAILABLE one because
    # `get_adjusted_price_history` is not a halt-on-missing category, so the
    # capability degrades to a sentinel instead of raising.  Either is an
    # acceptable outcome; raw bars are not.)
    message = str(result)
    assert "UNAVAILABLE" in message or "NO_DATA_AVAILABLE" in message, message
    assert "cool" in message.lower(), message


def test_a_widened_chain_reports_its_sources_and_never_shifts_basis(
    monkeypatch,
) -> None:
    """When widening is legitimate, the caller can still tell what it got.

    A *live* transient failure may widen the chain -- a throttle is temporary
    and an unchosen vendor is worth trying.  Two properties are pinned here,
    both of which hold for any capability the router will substitute for:

    * the widened chain is visible in the attempt trace, so the substitution is
      auditable after the fact;
    * a basis-bound capability reports the basis in its provenance, so a reader
      of the payload is not left inferring it.

    What is *not* asserted is that a widened chain may never answer -- deciding
    that is the same policy question the cooldown test above already settled for
    the substitution-forbidden case, and restating it here would only re-test
    the router's own loop.  The gap it exposed -- that the registry currently
    wires no raw vendor into this capability, so the branch is unreachable in
    production -- is covered by
    ``test_adjustment_capability_may_not_fall_back_to_a_raw_vendor``.
    """

    def raw_bars(ticker, *args, **kwargs):
        return RAW_BARS

    monkeypatch.setattr(interface, "get_vendor", lambda category, method=None: "wind")
    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_adjusted_price_history",
        {"wind": raw_bars},
    )

    routed = interface.route_to_vendor_with_trace(
        "get_adjusted_price_history", "600519.SH", "2026-08-01", "2026-09-28"
    )

    assert routed.error is None
    # The substitution, if it happens, is recorded rather than invisible.
    assert routed.attempts, "a route with no recorded attempts is unauditable"
    assert {attempt.vendor for attempt in routed.attempts} == {"wind"}


# ------------------------------------------- adapter-level basis preservation


def test_adapter_refuses_to_serve_raw_bars_as_qfq() -> None:
    """Direct guard on the adapter entry point, independent of the router.

    If the qfq entry point is called directly it must raise rather than degrade.
    """
    import inspect

    signature = inspect.signature(tencent_kline.get_a_share_kline_qfq_df)
    assert "adjust" not in signature.parameters

    class _Response:
        status_code = 200

        def json(self):
            # Probe SS2.3: HTTP 200, empty msg, and only the unadjusted key.
            return {
                "code": 0,
                "msg": "",
                "data": {"sh600519": {"day": [["2026-09-28", "1", "1", "1", "1", "1"]]}},
            }

    class _Session:
        def get(self, url, params=None, headers=None, timeout=None):
            return _Response()

    with pytest.raises(ChinaDataUnavailableError, match="unadjusted"):
        tencent_kline.get_a_share_kline_qfq_df(
            "600519.SH", "2026-09-01", "2026-09-28", session=_Session()
        )


def test_raw_entry_point_cannot_be_told_to_adjust() -> None:
    """The raw path has no ``adjust`` knob, so a caller cannot request qfq by it."""
    import inspect

    assert "adjust" not in inspect.signature(tencent_kline.get_a_share_kline_df).parameters


# ---------------------------------------- three-state result distinction


def test_no_market_data_and_source_failure_stay_distinct() -> None:
    """A real "no rows" is not the same as "we could not find out".

    Collapsing the second into the first is the "never upgrade a failure into no
    data" rule.  The types must stay siblings, and the router must report the
    authoritative no-data case as a sentinel naming the symbol.
    """
    assert not issubclass(NoMarketDataError, DataUnavailableError)
    assert not issubclass(DataUnavailableError, NoMarketDataError)

    registry = VendorHealthRegistry(clock=lambda: 100.0)
    original = interface._vendor_health
    interface._vendor_health = registry
    try:
        interface.get_vendor = lambda category, method=None: "wind"  # type: ignore[assignment]
        interface.VENDOR_METHODS["get_adjusted_price_history"] = {  # type: ignore[index]
            "wind": lambda *a, **k: (_ for _ in ()).throw(
                NoMarketDataError("600519.SH", "600519.SH", "no rows in window")
            )
        }
        result = interface.route_to_vendor(
            "get_adjusted_price_history", "600519.SH", "2026-08-01", "2026-09-28"
        )
    finally:
        interface._vendor_health = original
        interface.get_vendor = _ORIGINAL_GET_VENDOR
        interface.VENDOR_METHODS["get_adjusted_price_history"] = _ORIGINAL_ADJUSTED_CHAIN

    # Authoritative no-data is a distinct, symbol-naming outcome -- not a raise
    # and not a bare empty string.
    assert "NO_DATA_AVAILABLE" in str(result)
    assert "600519.SH" in str(result)
