"""Client for the similar-photo service (the sidecar in similarity/)."""
from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientTimeout

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .library import PhotoLibrary

# A photo that isn't analysed yet is analysed during the request (a few seconds on a Pi)
_TIMEOUT = ClientTimeout(total=120)


class SimilarityError(Exception):
    """The service could not answer."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SimilarityClient:
    def __init__(self, hass: HomeAssistant, url: str, token: str | None) -> None:
        self.hass = hass
        self.url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}

    async def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                f"{self.url}/{endpoint}", params=params, headers=self._headers, timeout=_TIMEOUT
            ) as resp:
                if resp.status == 404:
                    raise SimilarityError("not_found", "The photo is not in the library")
                if resp.status == 422:
                    raise SimilarityError("unreadable", "The photo can't be read")
                if resp.status >= 400:
                    raise SimilarityError("service_error", f"Similar-photo service answered {resp.status}")
                return await resp.json()
        except (ClientError, TimeoutError) as err:
            raise SimilarityError("unavailable", f"Similar-photo service unavailable: {err}") from err

    async def async_status(self) -> dict:
        return await self._get("status")

    async def async_similar(self, lib: PhotoLibrary, path: str, min_score: float, limit: int) -> dict:
        data = await self._get("similar", {"path": path, "min": f"{min_score:.4f}", "limit": str(limit)})
        # Drop files deleted since the service last looked
        paths = [r["path"] for r in data.get("results", [])]
        existing = await self.hass.async_add_executor_job(lambda: {p for p in paths if lib.safe_path(p)})
        data["results"] = [r for r in data["results"] if r["path"] in existing]
        return data
