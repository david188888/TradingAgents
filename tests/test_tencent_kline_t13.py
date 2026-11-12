import pytest

from tradingagents.dataflows import tencent_kline
from tradingagents.dataflows.china_data import ChinaDataUnavailableError


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
