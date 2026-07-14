"""Thin async client for the OANDA v20 REST API.

Environment variables:
    OANDA_API_TOKEN   : personal access token (required)
    OANDA_ACCOUNT_ID  : default account ID, e.g. "101-001-1234567-001" (required)
    OANDA_ENV         : "practice" (default) or "live"
"""

from __future__ import annotations

import os
from typing import Any

import httpx

_HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}


class OandaError(RuntimeError):
    """Raised when the OANDA API returns an error response."""


class OandaClient:
    def __init__(
        self,
        token: str | None = None,
        account_id: str | None = None,
        environment: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.token = token or os.environ.get("OANDA_API_TOKEN", "")
        self.account_id = account_id or os.environ.get("OANDA_ACCOUNT_ID", "")
        env = (environment or os.environ.get("OANDA_ENV", "practice")).lower()
        if env not in _HOSTS:
            raise ValueError(f"OANDA_ENV must be 'practice' or 'live', got {env!r}")
        self.environment = env
        self.base_url = _HOSTS[env]
        self.timeout = timeout

        if not self.token:
            raise OandaError(
                "OANDA_API_TOKEN is not set. Get a personal access token from "
                "your OANDA account (Manage API Access) and export it."
            )
        if not self.account_id:
            raise OandaError(
                "OANDA_ACCOUNT_ID is not set. Find it in the OANDA platform "
                "(format like 101-001-1234567-001) and export it."
            )

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept-Datetime-Format": "RFC3339",
            "Content-Type": "application/json",
        }

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform a GET request against the v20 API and return parsed JSON."""
        # Drop params whose value is None so httpx does not send them.
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=self._headers, params=clean)
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("errorMessage", resp.text)
            except Exception:  # noqa: BLE001
                detail = resp.text
            raise OandaError(f"OANDA API error {resp.status_code}: {detail}")
        return resp.json()

    # ---- convenience wrappers (all read-only GET endpoints) ----

    async def account_summary(self) -> dict[str, Any]:
        return await self.get(f"/v3/accounts/{self.account_id}/summary")

    async def instruments(self, names: str | None = None) -> dict[str, Any]:
        return await self.get(
            f"/v3/accounts/{self.account_id}/instruments",
            {"instruments": names},
        )

    async def pricing(self, instruments: str) -> dict[str, Any]:
        return await self.get(
            f"/v3/accounts/{self.account_id}/pricing",
            {"instruments": instruments},
        )

    async def candles(
        self,
        instrument: str,
        granularity: str = "H1",
        count: int | None = 100,
        price: str = "M",
        from_time: str | None = None,
        to_time: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "granularity": granularity,
            "price": price,
            "from": from_time,
            "to": to_time,
        }
        # v20 rejects count combined with both from and to.
        if not (from_time and to_time):
            params["count"] = count
        return await self.get(f"/v3/instruments/{instrument}/candles", params)

    async def open_positions(self) -> dict[str, Any]:
        return await self.get(f"/v3/accounts/{self.account_id}/openPositions")

    async def pending_orders(self) -> dict[str, Any]:
        return await self.get(f"/v3/accounts/{self.account_id}/pendingOrders")

    async def open_trades(self) -> dict[str, Any]:
        return await self.get(f"/v3/accounts/{self.account_id}/openTrades")

    async def transactions(
        self,
        count: int = 50,
        type_filter: str | None = None,
    ) -> dict[str, Any]:
        # sinceid-based pagination is overkill for an MCP tool; use the
        # idrange endpoint via pages returned by /transactions.
        params: dict[str, Any] = {"pageSize": min(count, 1000)}
        if type_filter:
            params["type"] = type_filter
        first = await self.get(f"/v3/accounts/{self.account_id}/transactions", params)
        pages = first.get("pages") or []
        if not pages:
            return {"transactions": [], "count": first.get("count", 0)}
        # Fetch the last page (most recent transactions).
        last_page_url = pages[-1]
        path = last_page_url.split(self.base_url)[-1]
        data = await self.get(path)
        txns = data.get("transactions", [])[-count:]
        return {"transactions": txns, "count": first.get("count", 0)}
