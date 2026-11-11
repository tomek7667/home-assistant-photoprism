"""Media source: browse the photo library, with HEIC photos shown as JPEG."""
from __future__ import annotations

from datetime import date
import os
from urllib.parse import quote

from homeassistant.components.media_player import BrowseError, MediaClass
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant

from .const import DOMAIN, FAVORITES, IMAGE_URL, MIME, ON_THIS_DAY, RANDOM, THUMB_URL, VIDEO_EXTS
from .favorites import async_get_favorites
from .library import PhotoLibrary, ext_of

_LABELS = {
    "en": {
        "name": "PhotoPrism Library",
        "on_this_day": "On this day ({day} {month})",
        "random": "Random",
        "favorites": "Favorites",
        "months": ["January", "February", "March", "April", "May", "June", "July",
                   "August", "September", "October", "November", "December"],
    },
    "pl": {
        "name": "Zdjęcia",
        "on_this_day": "Tego dnia ({day} {month})",
        "random": "Losowe",
        "favorites": "Ulubione",
        "months": ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca",
                   "sierpnia", "września", "października", "listopada", "grudnia"],
    },
}


async def async_get_media_source(hass: HomeAssistant) -> MediaSource:
    return PhotoLibrarySource(hass)


class PhotoLibrarySource(MediaSource):
    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass
        self.name = self._labels["name"]

    @property
    def _labels(self) -> dict:
        lang = (self.hass.config.language or "en").split("-")[0]
        return _LABELS.get(lang, _LABELS["en"])

    @property
    def _lib(self) -> PhotoLibrary:
        if (lib := self.hass.data.get(DOMAIN)) is None:
            raise BrowseError("PhotoPrism Library is not set up")
        return lib

    def _on_this_day_title(self) -> str:
        labels, today = self._labels, date.today()
        return labels["on_this_day"].format(day=today.day, month=labels["months"][today.month - 1])

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        rel = (item.identifier or "").strip("/")
        if not rel or rel.startswith("@"):
            raise Unresolvable("Not a file")
        lib = self._lib
        mime = "image/jpeg" if lib.needs_conversion(rel) else MIME.get(ext_of(rel), "application/octet-stream")
        # Unquoted like Home Assistant's own local media; the resolver signs and quotes it.
        return PlayMedia(f"{IMAGE_URL}{rel}", mime)

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        lib = self._lib
        rel = (item.identifier or "").strip("/")
        if rel == ON_THIS_DAY:
            photos = await lib.async_on_this_day()
            return self._folder(ON_THIS_DAY, self._on_this_day_title(), [self._file(p) for p in photos])
        if rel == RANDOM:
            photos = await lib.async_random()
            return self._folder(RANDOM, self._labels["random"], [self._file(p) for p in photos])
        if rel == FAVORITES:
            paths = [item["path"] for item in (await async_get_favorites(self.hass)).items()]
            # Most recently added first; files removed outside Home Assistant are skipped
            paths = await self.hass.async_add_executor_job(lambda: [p for p in paths if lib.safe_path(p)])
            children = [self._file(p, "video" if ext_of(p) in VIDEO_EXTS else "image") for p in paths]
            return self._folder(FAVORITES, self._labels["favorites"], children)
        try:
            dirs, files = await self.hass.async_add_executor_job(lib.list_dir, rel)
        except (FileNotFoundError, NotADirectoryError, PermissionError) as err:
            raise BrowseError(f"Unknown folder: {rel}") from err
        base = f"{rel}/" if rel else ""
        children: list[BrowseMediaSource] = []
        if not rel:
            children.append(self._folder(ON_THIS_DAY, self._on_this_day_title(), None))
            children.append(self._folder(RANDOM, self._labels["random"], None))
            children.append(self._folder(FAVORITES, self._labels["favorites"], None))
        children += [self._folder(f"{base}{d}", d, None) for d in dirs]
        children += [self._file(f"{base}{name}", kind) for name, kind in files]
        return self._folder(rel, os.path.basename(rel) or self.name, children)

    @staticmethod
    def _folder(ident: str, title: str, children: list | None) -> BrowseMediaSource:
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=ident,
            media_class=MediaClass.DIRECTORY,
            media_content_type="directory",
            title=title,
            can_play=False,
            can_expand=True,
            children=children,
            children_media_class=MediaClass.IMAGE,
        )

    def _file(self, rel: str, kind: str = "image") -> BrowseMediaSource:
        name = os.path.basename(rel)
        ext = ext_of(name)
        if kind == "video":
            return BrowseMediaSource(
                domain=DOMAIN,
                identifier=rel,
                media_class=MediaClass.VIDEO,
                media_content_type=MIME.get(ext, "video/quicktime"),
                title=name,
                can_play=True,
                can_expand=False,
                thumbnail=f"{THUMB_URL}{quote(rel)}",
            )
        mime = "image/jpeg" if self._lib.needs_conversion(rel) else MIME.get(ext, "image/jpeg")
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=rel,
            media_class=MediaClass.IMAGE,
            media_content_type=mime,
            # No extension in the title: slideshow cards skip names ending in .heic,
            # but these photos are delivered as JPEG.
            title=os.path.splitext(name)[0],
            can_play=True,
            can_expand=False,
            thumbnail=f"{THUMB_URL}{quote(rel)}",
        )
