"""Client for the Tranzy open-data API (https://api.tranzy.ai/v1/opendata/docs)."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import API_BASE


class TranzyError(Exception):
    """The API could not be reached or answered with an error."""


class TranzyAuthError(TranzyError):
    """The key is wrong, not active yet, or not allowed for the agency."""


class TranzyApi:
    def __init__(self, session: aiohttp.ClientSession, api_key: str, agency_id: str | None = None) -> None:
        self._session = session
        self._key = api_key
        self._agency = agency_id

    async def _get(self, path: str, timeout: float = 30) -> Any:
        headers = {"X-API-KEY": self._key, "Accept": "application/json"}
        if self._agency is not None:
            headers["X-Agency-Id"] = str(self._agency)
        try:
            async with self._session.get(
                f"{API_BASE}/{path}", headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                if resp.status in (401, 403):
                    raise TranzyAuthError(f"{path}: HTTP {resp.status}")
                if resp.status != 200:
                    raise TranzyError(f"{path}: HTTP {resp.status}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise TranzyError(f"{path}: {err}") from err

    async def agencies(self) -> list[dict]:
        return await self._get("agency")

    async def vehicles(self) -> list[dict]:
        return await self._get("vehicles")

    async def static(self) -> dict[str, list[dict]]:
        """Everything TransitIndex.build needs, fetched one by one (5 req/s limit)."""
        out: dict[str, list[dict]] = {}
        for name in ("routes", "trips", "stops", "stop_times", "shapes"):
            out[name] = await self._get(name, timeout=120)
        return out
