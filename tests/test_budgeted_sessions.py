"""Card adapters accept the run's BudgetedSession instead of opening their own HTTP."""

from types import SimpleNamespace

import pytest
import requests

from tradingagents.dataflows import china_capital_flow, china_specialty_em
from tradingagents.dataflows.a_share_official import get_a_share_sse_e_interaction
from tradingagents.dataflows.china_specialty_em import (
    get_a_share_eps_forecast,
    get_a_share_shareholder_counts_em,
)
from tradingagents.dataflows.eastmoney import EastMoneyHTTPClient


class _Stop(Exception):
    pass


def test_shareholder_counts_wrap_the_budgeted_session_in_the_paced_client(monkeypatch):
    captured = {}

    def fake_strict(report_name, **kwargs):
        captured.update(report_name=report_name, **kwargs)
        raise _Stop

    monkeypatch.setattr(china_specialty_em, "em_datacenter_strict", fake_strict)
    session = requests.Session()
    with pytest.raises(_Stop):
        get_a_share_shareholder_counts_em("002130.SZ", session=session)
    assert captured["report_name"] == "RPT_HOLDERNUMLATEST"
    assert isinstance(captured["client"], EastMoneyHTTPClient)
    assert captured["client"]._session is session

    with pytest.raises(_Stop):
        get_a_share_shareholder_counts_em("002130.SZ")
    assert captured["client"] is None


def test_consensus_eps_uses_the_supplied_session(monkeypatch):
    session = SimpleNamespace(get=lambda *args, **kwargs: (_ for _ in ()).throw(_Stop("seen")))
    with pytest.raises(_Stop):
        get_a_share_eps_forecast("002130.SZ", session=session)


def test_northbound_flow_hands_the_session_to_the_provider(monkeypatch):
    captured = {}

    class _Provider:
        def __init__(self, session=None):
            captured["session"] = session

        def northbound_flow(self, start_date, end_date):
            return SimpleNamespace(render=lambda: "rendered northbound")

    monkeypatch.setattr(china_capital_flow, "ChinaCapitalFlowProvider", _Provider)
    marker = object()
    assert china_capital_flow.get_a_share_northbound_flow(session=marker) == "rendered northbound"
    assert captured["session"] is marker


def test_sse_e_interaction_passes_the_session_to_the_official_request(monkeypatch):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return SimpleNamespace(content='<div class="m_feed_note">暂无问答</div>'.encode())

    monkeypatch.setattr("tradingagents.dataflows.a_share_official._http_request", fake_request)
    marker = object()
    text = get_a_share_sse_e_interaction(kind="answered", page=1, page_size=10, session=marker)
    assert captured["session"] is marker
    assert "上证e互动" in text
