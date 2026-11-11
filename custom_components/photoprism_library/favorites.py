"""Favourite photos, kept in Home Assistant: one list shared by everyone."""
from __future__ import annotations

from collections.abc import Callable, Iterable
import time

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_STORAGE_VERSION = 1
_STORAGE_KEY = f"{DOMAIN}.favorites"
_DATA_KEY = f"{DOMAIN}_favorites"


async def async_get_favorites(hass: HomeAssistant) -> Favorites:
    """Return the favourites, loaded once and kept across reloads of the entry."""
    if (favorites := hass.data.get(_DATA_KEY)) is None:
        favorites = Favorites(hass)
        await favorites.async_load()
        hass.data[_DATA_KEY] = favorites
    return favorites


class Favorites:
    """Library-relative paths of favourite photos and videos, with the time each was added."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict] = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._added: dict[str, float] = {}
        self._listeners: set[Callable[[], None]] = set()

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._added = {
            str(item["path"]): float(item.get("added", 0))
            for item in data.get("items", [])
            if item.get("path")
        }

    def items(self) -> list[dict]:
        """Favourites, the most recently added first."""
        return [
            {"path": path, "added": added}
            for path, added in sorted(self._added.items(), key=lambda kv: kv[1], reverse=True)
        ]

    def __contains__(self, path: str) -> bool:
        return path in self._added

    @callback
    def async_set(self, paths: Iterable[str], favorite: bool) -> int:
        """Add or remove paths; returns how many changed."""
        now = time.time()
        changed = 0
        for offset, path in enumerate(paths):
            if favorite and path not in self._added:
                # Keep the given order for paths added together
                self._added[path] = now - offset * 1e-6
                changed += 1
            elif not favorite and self._added.pop(path, None) is not None:
                changed += 1
        if changed:
            self._changed()
        return changed

    @callback
    def async_forget(self, paths: Iterable[str]) -> None:
        """Drop deleted files (compared case-insensitively, like the library does)."""
        gone = {p.lower() for p in paths}
        stale = [p for p in self._added if p.lower() in gone]
        for path in stale:
            del self._added[path]
        if stale:
            self._changed()

    @callback
    def async_subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    @callback
    def _changed(self) -> None:
        self._store.async_delay_save(lambda: {"items": self.items()}, 1)
        for listener in list(self._listeners):
            listener()
