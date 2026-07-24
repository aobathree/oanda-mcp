"""OANDA v20 MCP server — read-only tools.

Run with:  oanda-mcp   (after `pip install -e .`)
or:        python -m oanda_mcp.server
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .client import OandaClient, OandaError

Granularity = Literal[
    "S5", "S10", "S15", "S30",
    "M1", "M2", "M3", "M4", "M5", "M10", "M15", "M30",
    "H1", "H2", "H3", "H4", "H6", "H8", "H12",
    "D", "W", "M",
]

mcp = FastMCP(
    "oanda",
    instructions=(
        "Read-only access to an OANDA v20 trading account. "
        "Instrument names use OANDA format like 'USD_JPY', 'EUR_USD'. "
        "All data comes from the account's environment (practice or live) "
        "configured via OANDA_ENV."
    ),
)


def _client() -> OandaClient:
    return OandaClient()


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


# Full RFC3339 date-time: date, "T", time, and a UTC offset are all
# required — date-only or offset-less values are rejected.
_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$"
)


def _check_time_range(from_time: str | None, to_time: str | None) -> None:
    """Reject malformed RFC3339 timestamps and inverted from/to ranges
    before an authenticated API request is sent."""

    def parse(name: str, value: str) -> datetime:
        if not _RFC3339_RE.match(value):
            raise ValueError(
                f"{name} must be a full RFC3339 date-time with timezone "
                f"like '2026-07-01T00:00:00Z', got {value!r}"
            )
        try:
            return datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(
                f"{name} is not a valid date-time: {value!r}"
            ) from None

    start = parse("from_time", from_time) if from_time else None
    end = parse("to_time", to_time) if to_time else None
    if start and end and start >= end:
        raise ValueError(
            f"from_time ({from_time}) must be earlier than to_time ({to_time})"
        )


@mcp.tool()
async def get_price(instruments: str) -> str:
    """Get current bid/ask prices for one or more instruments.

    Args:
        instruments: Comma-separated OANDA instrument names, e.g. "USD_JPY"
            or "USD_JPY,EUR_USD,GBP_JPY".
    """
    data = await _client().pricing(instruments)
    out = []
    for p in data.get("prices", []):
        bids = p.get("bids") or [{}]
        asks = p.get("asks") or [{}]
        out.append(
            {
                "instrument": p.get("instrument"),
                "time": p.get("time"),
                "bid": bids[0].get("price"),
                "ask": asks[0].get("price"),
                "tradeable": p.get("tradeable"),
            }
        )
    return _dump(out)


@mcp.tool()
async def get_candles(
    instrument: str,
    granularity: Granularity = "H1",
    count: Annotated[int, Field(ge=1, le=5000)] = 100,
    price: Annotated[str, Field(pattern="^[MBA]{1,3}$")] = "M",
    from_time: str | None = None,
    to_time: str | None = None,
) -> str:
    """Get historical candlestick data for an instrument.

    Args:
        instrument: OANDA instrument name, e.g. "USD_JPY".
        granularity: Candle size: S5,S10,S15,S30,M1,M2,M3,M4,M5,M10,M15,M30,
            H1,H2,H3,H4,H6,H8,H12,D,W,M. Default "H1".
        count: Number of candles (1-5000). Ignored when both from_time
            and to_time are given. Default 100.
        price: "M" (mid), "B" (bid), "A" (ask), or combinations like "MBA".
        from_time: RFC3339 start time, e.g. "2026-07-01T00:00:00Z" (optional).
        to_time: RFC3339 end time (optional, must be after from_time).
    """
    _check_time_range(from_time, to_time)
    data = await _client().candles(
        instrument,
        granularity=granularity,
        count=count,
        price=price,
        from_time=from_time,
        to_time=to_time,
    )
    candles = []
    for c in data.get("candles", []):
        row: dict[str, Any] = {
            "time": c.get("time"),
            "volume": c.get("volume"),
            "complete": c.get("complete"),
        }
        for key, label in (("mid", "mid"), ("bid", "bid"), ("ask", "ask")):
            if key in c:
                row[label] = c[key]  # {o,h,l,c}
        candles.append(row)
    return _dump(
        {
            "instrument": data.get("instrument"),
            "granularity": data.get("granularity"),
            "candles": candles,
        }
    )


@mcp.tool()
async def get_account_summary() -> str:
    """Get the account summary: balance, unrealized P/L, margin usage,
    open trade/position counts, currency, and NAV."""
    data = await _client().account_summary()
    return _dump(data.get("account", data))


@mcp.tool()
async def get_open_positions() -> str:
    """List all currently open positions with units, average price, and
    unrealized P/L per instrument."""
    data = await _client().open_positions()
    return _dump(data.get("positions", []))


@mcp.tool()
async def get_pending_orders() -> str:
    """List all pending (not yet filled) orders on the account."""
    data = await _client().pending_orders()
    return _dump(data.get("orders", []))


@mcp.tool()
async def get_open_trades() -> str:
    """List all open trades with entry price, units, and unrealized P/L."""
    data = await _client().open_trades()
    return _dump(data.get("trades", []))


@mcp.tool()
async def get_recent_transactions(
    count: Annotated[int, Field(ge=1, le=1000)] = 50,
    type_filter: str | None = None,
) -> str:
    """Get the most recent account transactions (fills, orders, funding...).

    Args:
        count: How many recent transactions to return (1-1000, default 50).
        type_filter: Optional comma-separated transaction type filter,
            e.g. "ORDER_FILL" or "MARKET_ORDER,ORDER_FILL". Searches the
            most recent 5000 transactions at most.
    """
    data = await _client().transactions(count=count, type_filter=type_filter)
    return _dump(data)


@mcp.tool()
async def list_instruments(names: str | None = None) -> str:
    """List tradeable instruments available to the account.

    Args:
        names: Optional comma-separated filter, e.g. "USD_JPY,EUR_USD".
            Omit to list everything.
    """
    data = await _client().instruments(names)
    out = [
        {
            "name": i.get("name"),
            "displayName": i.get("displayName"),
            "type": i.get("type"),
            "pipLocation": i.get("pipLocation"),
            "marginRate": i.get("marginRate"),
        }
        for i in data.get("instruments", [])
    ]
    return _dump(out)


def main() -> None:
    try:
        mcp.run()
    except OandaError as e:  # pragma: no cover - startup misconfiguration
        raise SystemExit(str(e)) from e


if __name__ == "__main__":
    main()
