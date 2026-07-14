"""Smoke tests: tool registration + client behavior against a mocked API."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("OANDA_API_TOKEN", "test-token")
os.environ.setdefault("OANDA_ACCOUNT_ID", "101-001-1234567-001")
os.environ.setdefault("OANDA_ENV", "practice")

from oanda_mcp import server  # noqa: E402
from oanda_mcp.client import OandaClient  # noqa: E402

EXPECTED_TOOLS = {
    "get_price",
    "get_candles",
    "get_account_summary",
    "get_open_positions",
    "get_pending_orders",
    "get_open_trades",
    "get_recent_transactions",
    "list_instruments",
}


def test_tools_registered() -> None:
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}"
    for t in tools:
        assert t.description, f"tool {t.name} has no description"


def test_client_env_config() -> None:
    c = OandaClient()
    assert c.base_url == "https://api-fxpractice.oanda.com"
    assert c._headers["Authorization"] == "Bearer test-token"
    assert c._headers["User-Agent"].startswith("oanda-mcp/")


def test_get_price_formats_output() -> None:
    fake = {
        "prices": [
            {
                "instrument": "USD_JPY",
                "time": "2026-07-14T02:00:00.000000000Z",
                "bids": [{"price": "157.123", "liquidity": 1000000}],
                "asks": [{"price": "157.140", "liquidity": 1000000}],
                "tradeable": True,
            }
        ]
    }
    with patch.object(OandaClient, "get", new=AsyncMock(return_value=fake)):
        out = asyncio.run(server.get_price(instruments="USD_JPY"))
    rows = json.loads(out)
    assert rows == [
        {
            "instrument": "USD_JPY",
            "time": "2026-07-14T02:00:00.000000000Z",
            "bid": "157.123",
            "ask": "157.140",
            "tradeable": True,
        }
    ]


def test_candles_param_rules() -> None:
    captured: dict = {}

    async def fake_get(self, path, params=None):  # noqa: ANN001
        captured["path"] = path
        captured["params"] = params
        return {"instrument": "USD_JPY", "granularity": "D", "candles": []}

    with patch.object(OandaClient, "get", new=fake_get):
        asyncio.run(
            server.get_candles(
                instrument="USD_JPY",
                granularity="D",
                from_time="2026-07-01T00:00:00Z",
                to_time="2026-07-10T00:00:00Z",
            )
        )
    # count must NOT be sent when both from and to are given
    assert "count" not in captured["params"]
    assert captured["path"] == "/v3/instruments/USD_JPY/candles"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    raise SystemExit(1 if failures else 0)
