"""Integration tests: read-only GETs against the real OANDA practice API.

Opt-in layer (mirrors the official Alpaca MCP server's test strategy):
runs only when real practice credentials are available (env vars or .env);
otherwise everything is skipped and the script exits 0. Tests never run
against OANDA_ENV=live, and only call GET endpoints — nothing is mutated.

    python tests\\test_integration.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from oanda_mcp.client import OandaClient, OandaError  # noqa: E402

_PLACEHOLDER_TOKENS = ("your-", "test-token")
_PLACEHOLDER_ACCOUNT = "101-001-1234567"


def _client_or_none() -> OandaClient | None:
    """Return a client for the practice API, or None if tests must be skipped."""
    try:
        c = OandaClient()
    except (OandaError, ValueError):
        return None
    if c.environment != "practice":
        return None  # never run integration tests against a live account
    if c.token.startswith(_PLACEHOLDER_TOKENS):
        return None
    if c.account_id.startswith(_PLACEHOLDER_ACCOUNT):
        return None
    return c


def test_account_summary(c: OandaClient) -> None:
    data = asyncio.run(c.account_summary())
    acct = data["account"]
    assert "balance" in acct, f"no balance in {sorted(acct)}"
    assert "currency" in acct


def test_pricing(c: OandaClient) -> None:
    data = asyncio.run(c.pricing("USD_JPY"))
    prices = data["prices"]
    assert prices, "no prices returned"
    assert prices[0]["instrument"] == "USD_JPY"
    assert prices[0]["bids"] and prices[0]["asks"]


def test_candles(c: OandaClient) -> None:
    data = asyncio.run(c.candles("USD_JPY", granularity="D", count=5))
    candles = data["candles"]
    assert 1 <= len(candles) <= 5, f"unexpected candle count {len(candles)}"
    assert {"o", "h", "l", "c"} <= set(candles[0]["mid"])


def test_instruments(c: OandaClient) -> None:
    data = asyncio.run(c.instruments("USD_JPY"))
    names = {i["name"] for i in data["instruments"]}
    assert "USD_JPY" in names


if __name__ == "__main__":
    client = _client_or_none()
    if client is None:
        print(
            "SKIP: no real practice credentials found "
            "(set OANDA_API_TOKEN / OANDA_ACCOUNT_ID in .env with OANDA_ENV=practice)"
        )
        raise SystemExit(0)
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(client)
                print(f"PASS {name}")
            except Exception as e:  # noqa: BLE001 - report API errors as failures
                failures += 1
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    raise SystemExit(1 if failures else 0)
