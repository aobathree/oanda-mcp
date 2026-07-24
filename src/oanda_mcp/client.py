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

# How far back a type-filtered transaction search may scan, in chunks of
# 1000 IDs (the idrange endpoint's per-request maximum).
_MAX_IDRANGE_CHUNKS = 5


def _load_dotenv() -> None:
    """Load OANDA_* keys from a .env file into os.environ.

    Only keys with the OANDA_ prefix are imported, and existing environment
    variables are never overridden — so a .env file sitting in an untrusted
    working directory cannot inject proxy/TLS settings (HTTPS_PROXY,
    SSL_CERT_FILE, ...) into the authenticated HTTP requests.

    Searched in order; the first file containing at least one OANDA_ key
    wins, files without any OANDA_ key are skipped:
      1. $OANDA_DOTENV (explicit path, if set)
      2. ~/.oanda/.env — the recommended location, outside any project
         directory so coding agents and other tools working in the
         project tree cannot read the credentials as a workspace file
      3. .env in the current working directory and its parents
      4. .env at the project root (three levels up from this file,
         for a source checkout like D:/oanda-mcp)
    """
    candidates: list[Path] = []
    explicit = os.environ.get("OANDA_DOTENV")
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path.home() / ".oanda" / ".env")
    cwd = Path.cwd()
    candidates.extend(p / ".env" for p in [cwd, *cwd.parents])
    candidates.append(Path(__file__).resolve().parents[2] / ".env")

    for path in candidates:
        try:
            if not path.is_file():
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        # Tolerate Windows editors/PowerShell: UTF-8 BOM and UTF-16 files.
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16")
        else:
            text = raw.decode("utf-8-sig", errors="replace")
        found: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key.startswith("OANDA_"):
                continue
            found[key] = value.strip().strip("'\"")
        if not found:
            continue  # unrelated .env (some other project) — keep searching
        for key, value in found.items():
            if key not in os.environ:
                os.environ[key] = value
        return  # only the first .env with OANDA_ keys is loaded


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
            except Exception:
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
        """Return the most recent ``count`` transactions.

        Transaction IDs are sequential integers, so the newest ``count``
        transactions are exactly the ID range ``last-count+1 .. last``.
        Unlike a time-based query (which is capped at 365 days per request
        and would miss older activity on dormant accounts), this works
        regardless of the account's age or trading frequency.

        With ``type_filter``, matching transactions may be sparse, so the
        scan walks backwards in chunks of 1000 IDs until ``count`` matches
        are found — bounded to the most recent
        ``_MAX_IDRANGE_CHUNKS * 1000`` transactions.
        """
        if not 1 <= count <= 1000:
            raise ValueError(f"count must be between 1 and 1000, got {count}")
        summary = await self.get(f"/v3/accounts/{self.account_id}/summary")
        last_raw = summary.get("lastTransactionID") or summary.get("account", {}).get(
            "lastTransactionID"
        )
        try:
            last = int(last_raw)
        except (TypeError, ValueError):
            last = 0
        if last < 1:  # no transactions on this account yet
            return {"transactions": [], "lastTransactionID": last_raw}

        path = f"/v3/accounts/{self.account_id}/transactions/idrange"
        collected: list[dict[str, Any]] = []
        to_id = last
        for _ in range(_MAX_IDRANGE_CHUNKS):
            span = 1000 if type_filter else count
            from_id = max(1, to_id - span + 1)
            params: dict[str, Any] = {"from": from_id, "to": to_id}
            if type_filter:
                params["type"] = type_filter
            data = await self.get(path, params)
            collected = data.get("transactions", []) + collected
            if not type_filter or len(collected) >= count or from_id == 1:
                break
            to_id = from_id - 1
        return {"transactions": collected[-count:], "lastTransactionID": last_raw}
