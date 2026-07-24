"""Smoke tests: tool registration + client behavior against a mocked API."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("OANDA_API_TOKEN", "test-token")
os.environ.setdefault("OANDA_ACCOUNT_ID", "101-001-1234567-001")
os.environ.setdefault("OANDA_ENV", "practice")

from oanda_mcp import server  # noqa: E402
from oanda_mcp.client import OandaClient, _load_dotenv  # noqa: E402

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


def test_schema_constraints() -> None:
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    candles = tools["get_candles"].inputSchema["properties"]
    assert candles["count"]["minimum"] == 1
    assert candles["count"]["maximum"] == 5000
    assert "M3" in candles["granularity"]["enum"]
    assert candles["price"]["pattern"] == "^[MBA]{1,3}$"
    txn = tools["get_recent_transactions"].inputSchema["properties"]
    assert txn["count"]["minimum"] == 1
    assert txn["count"]["maximum"] == 1000


def test_transactions_count_bounds() -> None:
    async def fake_get(self, path, params=None):  # noqa: ANN001
        return {"pages": [], "count": 0}

    with patch.object(OandaClient, "get", new=fake_get):
        c = OandaClient()
        for bad in (-1, 0, 1001):
            try:
                asyncio.run(c.transactions(count=bad))
                raise AssertionError(f"count={bad} did not raise ValueError")
            except ValueError:
                pass
        for ok in (1, 50, 1000):  # boundary values must be accepted
            out = asyncio.run(c.transactions(count=ok))
            assert out == {"transactions": [], "count": 0}


def test_transactions_params_and_slice() -> None:
    calls: list[tuple] = []

    async def fake_get(self, path, params=None):  # noqa: ANN001
        calls.append((path, params))
        if len(calls) == 1:
            page = "https://api-fxpractice.oanda.com/v3/accounts/x/transactions/idrange?from=1&to=5"
            return {"pages": [page], "count": 5}
        return {"transactions": [{"id": str(i)} for i in range(1, 6)]}

    with patch.object(OandaClient, "get", new=fake_get):
        out = asyncio.run(OandaClient().transactions(count=2))
    first_params = calls[0][1]
    assert first_params["pageSize"] == 2
    # explicit range so accounts older than 365 days keep working
    assert "from" in first_params and "to" in first_params
    assert first_params["from"] < first_params["to"]
    # the last N of the most recent page are returned
    assert [t["id"] for t in out["transactions"]] == ["4", "5"]
    assert out["count"] == 5


def test_candles_time_validation() -> None:
    with patch.object(OandaClient, "get", new=AsyncMock(return_value={"candles": []})):
        try:
            asyncio.run(
                server.get_candles(
                    instrument="USD_JPY",
                    from_time="2026-07-10T00:00:00Z",
                    to_time="2026-07-01T00:00:00Z",
                )
            )
            raise AssertionError("inverted from/to did not raise ValueError")
        except ValueError:
            pass
        try:
            asyncio.run(server.get_candles(instrument="USD_JPY", from_time="not-a-time"))
            raise AssertionError("malformed timestamp did not raise ValueError")
        except ValueError:
            pass


def test_dotenv_restricts_keys_and_prefers_home() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        home = root / "home"
        (home / ".oanda").mkdir(parents=True)
        (home / ".oanda" / ".env").write_text("OANDA_ACCOUNT_ID=from-home\n", encoding="utf-8")
        work = root / "project" / "sub"
        work.mkdir(parents=True)
        (work / ".env").write_text(
            "HTTPS_PROXY=http://evil.example\nOANDA_ACCOUNT_ID=from-work\n",
            encoding="utf-8",
        )
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(Path, "home", return_value=home),
            patch.object(Path, "cwd", return_value=work),
        ):
            _load_dotenv()
            # ~/.oanda/.env wins over the working directory's .env
            assert os.environ.get("OANDA_ACCOUNT_ID") == "from-home"
            # non-OANDA keys are never imported
            assert "HTTPS_PROXY" not in os.environ


def test_dotenv_skips_env_without_oanda_keys() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        home = root / "home"
        home.mkdir()
        parent = root / "project"
        work = parent / "sub"
        work.mkdir(parents=True)
        (work / ".env").write_text("FOO=bar\nHTTPS_PROXY=http://evil.example\n", encoding="utf-8")
        (parent / ".env").write_text("OANDA_ACCOUNT_ID=from-parent\n", encoding="utf-8")
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(Path, "home", return_value=home),
            patch.object(Path, "cwd", return_value=work),
        ):
            _load_dotenv()
            assert os.environ.get("OANDA_ACCOUNT_ID") == "from-parent"
            assert "FOO" not in os.environ
            assert "HTTPS_PROXY" not in os.environ


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
