from __future__ import annotations

import pytest

from tradingagents.dataflows.index_provider import get_index_snapshot_eastmoney


@pytest.mark.unit
def test_eastmoney_index_snapshot_accepts_route_as_of_argument(monkeypatch):
    class FakeProvider:
        def snapshot(self, index_code):
            class Snapshot:
                def render(self):
                    return "snapshot"

            assert index_code == "000300.SH"
            return Snapshot()

    monkeypatch.setattr(
        "tradingagents.dataflows.index_provider.EastMoneyIndexProvider",
        FakeProvider,
    )

    assert get_index_snapshot_eastmoney("000300.SH", "2026-08-13") == "snapshot"
