"""Thin async client for the OANDA v20 REST API.

Configuration (environment variables, or a .env file — see _load_dotenv):
    OANDA_API_TOKEN   : personal access token (required)
    OANDA_ACCOUNT_ID  : default account ID, e.g. "101-001-1234567-001" (required)
    OANDA_ENV         : "practice" (default) or "live"
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from . import __version__

_HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}


def _load_dotenv() -> None:
    """Load a .env file into os.environ (without overriding existing vars).

    Searched in order; the first file found wins:
      1. $OANDA_DOTENV (explicit path, if set)
      2. .env in the current working directory and its parents
      3. .env at the project root (three levels up from this file,
         for a source checkout like D:/oanda-mcp)
      4. ~/.oanda/.env — the recommended location, outside any project
         directory so coding agents and other tools working in the
         project tree cannot read the credentials as a workspace file
    """
    candidates: list[Path] = []
    explicit = os.environ.get("OANDA_DOTENV")
    if explicit:
        candidates.append(Path(explicit))
    cwd = Path.cwd()
    candidates.extend(p / ".env" for p in [cwd, *cwd.parents])
    candidates.append(Path(__file__).resolve().parents[2] / ".env")
    candidates.append(Path.home() / ".oanda" / ".env")

    for path in candidates:
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        raw = path.read_bytes()
        # Tolerate Windows editors/PowerShell: UTF-8 BOM and UTF-16 files.
        if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
            text = raw.decode("utf-16")
        else:
            text = raw.decode("utf-8-sig", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
        return  # only the first .env found is loaded


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
        _load_dotenv()
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
            "User-Agent": f"oanda-mcp/{__version__}",
        }

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform a GET request against the v20 API and return parsed JSON."""
        # Drop params whose value is None so httpx does not send them.
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True
            ) as client:
                resp = await client.get(url, headers=self._headers, params=clean)
        except httpx.HTTPError as e:
            raise OandaError(
                f"HTTP request to OANDA failed ({type(e).__name__}): {e} [url={url}]"
            ) from e
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("errorMessage", resp.text)
            except Exception:  # noqa: BLE001
                detail = resp.text
            raise OandaError(f"OANDA API error {resp.status_code}: {detail}")
        try:
            return resp.json()
        except Exception as e:  # non-JSON body (redirect page, proxy, empty)
            snippet = resp.text[:200].strip() or "(empty body)"
            raise OandaError(
                f"OANDA returned a non-JSON response "
                f"(status {resp.status_code}, url={resp.url}): {snippet}"
            ) from e

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
