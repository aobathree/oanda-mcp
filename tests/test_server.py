"""Smoke tests: tool registration + client behavior against a mocked API."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("OANDA_API_TOKEN", "test-token")
os.environ.setdefault("OANDA_ACCOUNT_ID", "101-001-1234567-001")
os.environ.setdefault("OANDA_ENV", "practice")

from oanda_mcp import server  # noqa: E402
from oanda_mcp.client import OandaClient, OandaError, _load_dotenv  # noqa: E402

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

    async def fake_get(self, path, params=None):
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
    async def fake_get(self, path, params=None):
        return {"lastTransactionID": "0"}

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
            assert out == {"transactions": [], "lastTransactionID": "0"}


def test_transactions_idrange() -> None:
    calls: list[tuple] = []

    async def fake_get(self, path, params=None):
        calls.append((path, params))
        if path.endswith("/summary"):
            return {"lastTransactionID": "5"}
        return {
            "transactions": [{"id": str(i)} for i in range(params["from"], params["to"] + 1)]
        }

    with patch.object(OandaClient, "get", new=fake_get):
        out = asyncio.run(OandaClient().transactions(count=2))
    assert calls[0][0].endswith("/summary")
    path, params = calls[1]
    assert path.endswith("/transactions/idrange")
    # the newest `count` transactions are exactly the last `count` IDs,
    # independent of the account's age — no date window involved
    assert params == {"from": 4, "to": 5}
    assert [t["id"] for t in out["transactions"]] == ["4", "5"]
    assert out["lastTransactionID"] == "5"


def test_transactions_type_filter_scans_back() -> None:
    calls: list[tuple] = []

    async def fake_get(self, path, params=None):
        calls.append((path, params))
        if path.endswith("/summary"):
            return {"lastTransactionID": "1500"}
        if params["from"] == 501:  # newest chunk holds no matching type
            return {"transactions": []}
        return {"transactions": [{"id": "10", "type": "ORDER_FILL"}]}

    with patch.object(OandaClient, "get", new=fake_get):
        out = asyncio.run(OandaClient().transactions(count=1, type_filter="ORDER_FILL"))
    assert calls[1][1] == {"from": 501, "to": 1500, "type": "ORDER_FILL"}
    assert calls[2][1] == {"from": 1, "to": 500, "type": "ORDER_FILL"}
    assert [t["id"] for t in out["transactions"]] == ["10"]


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
        # only full RFC3339 date-times with a timezone are accepted
        bad_times = (
            "not-a-time",
            "2026-07-01",  # date only
            "2026-07-01T00:00:00",  # no timezone
            "2026-07-01T00:00:00+0900",  # malformed offset
        )
        for bad in bad_times:
            try:
                asyncio.run(server.get_candles(instrument="USD_JPY", from_time=bad))
                raise AssertionError(f"{bad!r} did not raise ValueError")
            except ValueError:
                pass
        for good in ("2026-07-01T00:00:00Z", "2026-07-01T09:30:00.123+09:00"):
            asyncio.run(server.get_candles(instrument="USD_JPY", from_time=good))


def _mock_transport(handler):
    real_client = httpx.AsyncClient

    def make(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    return patch.object(httpx, "AsyncClient", make)


def test_http_error_handling() -> None:
    c = OandaClient()

    def err_400(request):
        return httpx.Response(400, json={"errorMessage": "Invalid value specified"})

    with _mock_transport(err_400):
        try:
            asyncio.run(c.get("/v3/test"))
            raise AssertionError("HTTP 400 did not raise OandaError")
        except OandaError as e:
            assert "400" in str(e) and "Invalid value specified" in str(e)

    def non_json(request):
        return httpx.Response(200, text="<html>proxy login page</html>")

    with _mock_transport(non_json):
        try:
            asyncio.run(c.get("/v3/test"))
            raise AssertionError("non-JSON body did not raise OandaError")
        except OandaError as e:
            assert "non-JSON" in str(e)

    def boom(request):
        raise httpx.ConnectTimeout("timed out")

    with _mock_transport(boom):
        try:
            asyncio.run(c.get("/v3/test"))
            raise AssertionError("timeout did not raise OandaError")
        except OandaError as e:
            assert "ConnectTimeout" in str(e)


def test_missing_credentials_raise() -> None:
    with tempfile.TemporaryDirectory() as td:
        empty = Path(td)
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(Path, "home", return_value=empty),
            patch.object(Path, "cwd", return_value=empty),
        ):
            try:
                OandaClient()
                raise AssertionError("missing credentials did not raise OandaError")
            except OandaError as e:
                assert "OANDA_API_TOKEN" in str(e)


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
