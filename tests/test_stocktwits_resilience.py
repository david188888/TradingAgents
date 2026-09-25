"""StockTwits fetch: transport-error resilience (#1024) and crypto symbol
mapping (#1113).

StockTwits lists crypto under ``<BASE>.X`` (Yahoo's ``BTC-USD`` 404s), and any
transport error must degrade to a placeholder rather than raise.
"""

from __future__ import annotations

import http.client
import io
import json
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from tradingagents.dataflows import stocktwits


def _raise(exc):
    class _Resp:
        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *a):
            return False

        def read(self_inner):
            raise exc
    return _Resp()


@pytest.mark.unit
class TestStockTwitsResilience:
    @pytest.mark.parametrize(
        "exc",
        [
            http.client.IncompleteRead(b""),
            HTTPError("url", 503, "down", {}, None),
            TimeoutError("slow"),
        ],
    )
    def test_transport_errors_return_placeholder(self, exc):
        with patch.object(stocktwits, "urlopen", return_value=_raise(exc)):
            out = stocktwits.fetch_stocktwits_messages("NVDA")
        assert "unavailable" in out.lower()
        assert out.startswith("<stocktwits unavailable")

    def test_html_entities_are_decoded_in_message_body(self):
        payload = {
            "messages": [
                {
                    "created_at": "2026-09-25T12:00:00Z",
                    "user": {"username": "alice"},
                    "entities": {"sentiment": {"basic": "Bullish"}},
                    "body": "R&amp;D &lt;growth&gt; &quot;looks good&quot; &#39;",
                }
            ]
        }
        response = io.BytesIO(json.dumps(payload).encode("utf-8"))

        with patch.object(stocktwits, "urlopen", return_value=response):
            out = stocktwits.fetch_stocktwits_messages("NVDA")

        assert 'R&D <growth> "looks good"' in out
        assert "&#39;" not in out


@pytest.mark.unit
class TestStockTwitsCryptoSymbols:
    @pytest.mark.parametrize(
        ("ticker", "expected"),
        [
            ("BTC-USD", "BTC.X"),
            ("eth-usd", "ETH.X"),
            ("SOL-USD", "SOL.X"),
            ("BTCUSD", "BTC.X"),      # undashed broker form
            ("BTC-USDT", "BTC.X"),    # stablecoin quote
            ("AMD", "AMD"),
            ("BRK-B", "BRK-B"),       # dashed class share: untouched
            ("GOLD", "GOLD"),         # real equity (aliases elsewhere): untouched here
            ("XYZ-USD", "XYZ-USD"),   # unknown base: not treated as crypto
        ],
    )
    def test_symbol_mapping(self, ticker, expected):
        assert stocktwits._stocktwits_symbol(ticker) == expected

    def test_crypto_pair_requests_dot_x_endpoint(self):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            raise TimeoutError("stop after capturing the URL")

        with patch.object(stocktwits, "urlopen", side_effect=fake_urlopen):
            stocktwits.fetch_stocktwits_messages("BTC-USD")
        assert "/symbol/BTC.X.json" in seen["url"]
