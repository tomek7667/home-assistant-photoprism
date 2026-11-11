"""Minimal PhotoPrism API client: find photos by file name, archive and delete them."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)


def _stem(name: str) -> str:
    """Originals-relative path without extension, lower case."""
    head, _, tail = name.strip("/").rpartition("/")
    base = (tail.rsplit(".", 1)[0] if "." in tail else tail).lower()
    if base.endswith("_hevc"):  # iCloud names Live Photo videos IMG_1234_HEVC.MOV
        base = base[:-5]
    return (f"{head}/{base}" if head else base).lower()


class PhotoPrismError(Exception):
    """PhotoPrism request failed."""


class PhotoPrismClient:
    """Talks to PhotoPrism with an app password or a username and password."""

    def __init__(
        self,
        hass: HomeAssistant,
        url: str,
        *,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        verify_ssl: bool = True,
    ) -> None:
        self._hass = hass
        self._url = url.rstrip("/")
        self._app_token = token
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._session_token: str | None = None

    async def _token(self, renew: bool = False) -> str:
        if self._app_token:
            return self._app_token
        if self._session_token and not renew:
            return self._session_token
        if not (self._username and self._password):
            raise PhotoPrismError("No PhotoPrism credentials")
        data = await self._request(
            "POST", "/api/v1/session", json={"username": self._username, "password": self._password}, auth=False
        )
        token = data.get("access_token") or data.get("id")
        if not token:
            raise PhotoPrismError("PhotoPrism login returned no token")
        self._session_token = token
        return token

    async def _request(self, method: str, path: str, *, auth: bool = True, retry: bool = True, **kwargs: Any) -> Any:
        headers = {}
        if auth:
            token = await self._token()
            headers = {"Authorization": f"Bearer {token}", "X-Auth-Token": token, "X-Session-ID": token}
        session = async_get_clientsession(self._hass, verify_ssl=self._verify_ssl)
        try:
            async with session.request(
                method, f"{self._url}{path}", headers=headers, timeout=aiohttp.ClientTimeout(total=30), **kwargs
            ) as resp:
                if resp.status == 401 and auth and retry and not self._app_token:
                    await self._token(renew=True)
                    return await self._request(method, path, auth=auth, retry=False, **kwargs)
                text = await resp.text()
                if resp.status >= 400:
                    raise PhotoPrismError(f"{method} {path}: HTTP {resp.status} {text[:200]}")
                if not text:
                    return {}
                try:
                    return await resp.json(content_type=None)
                except ValueError:
                    return {}
        except aiohttp.ClientError as err:
            raise PhotoPrismError(f"{method} {path}: {err}") from err

    async def async_find_uids(self, file_names: list[str]) -> set[str]:
        """UIDs of photos that contain any of these originals-relative file names."""
        uids: set[str] = set()
        wanted = {_stem(n) for n in file_names}
        # Normal searches skip photos in review, private or archived; look there too.
        # The searches don't depend on each other, so they run side by side.
        scopes = ({}, {"review": "true"}, {"private": "true"}, {"archived": "true"})
        results = await asyncio.gather(
            *(
                self._request(
                    "GET", "/api/v1/photos",
                    params={"count": 20, "offset": 0, "merged": "true", "filename": name, **scope},
                )
                for name in file_names
                for scope in scopes
            )
        )
        for photos in results:
            for photo in photos or []:
                # A photo's files (HEIC, Live Photo MOV, RAW...) share the stem; Name has no extension.
                stems = {_stem(str(f.get("Name", ""))) for f in photo.get("Files") or []}
                stems.add(f"{photo.get('Path', '')}/{photo.get('Name', '')}".strip("/").lower())
                if stems & wanted and (uid := photo.get("UID")):
                    uids.add(uid)
        return uids

    async def async_delete(self, uids: set[str]) -> None:
        """Archive, then permanently delete (PhotoPrism removes its files and thumbnails too)."""
        if not uids:
            return
        body = {"photos": sorted(uids)}
        await self._request("POST", "/api/v1/batch/photos/archive", json=body)
        await self._request("POST", "/api/v1/batch/photos/delete", json=body)
