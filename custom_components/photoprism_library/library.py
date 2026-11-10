"""Filesystem access, HEIC conversion, the photo index and caches."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
import io
import os
import random
import re
import time

from PIL import Image, ImageOps

from homeassistant.core import HomeAssistant

from .const import (
    CONVERT_EXTS,
    FULL_QUALITY,
    FULL_SIZE,
    INDEX_TTL,
    PHOTO_EXTS,
    SCREENSHOT_EXTS,
    THUMB_QUALITY,
    THUMB_SIZE,
    VIDEO_EXTS,
)

# YYYY/MM/DD folders, e.g. 2020/01/31/IMG_1234.HEIC
_PATH_DATE = re.compile(r"(?:^|/)((?:19|20)\d{2})/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])(?:/|$)")
# Dates in file names: PhotoPrism 20230512_143000_ABCD1234.jpg, IMG_20230512_..., PXL_20230512..., 2023-05-12 ...
_NAME_DATE = re.compile(r"(?<!\d)((?:19|20)\d{2})[-_]?(0[1-9]|1[0-2])[-_]?(0[1-9]|[12]\d|3[01])(?!\d)")


def ext_of(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def photo_date(rel: str) -> tuple[int, int, int] | None:
    """Best-effort capture date (year, month, day) from the folder layout or the file name."""
    folder, name = os.path.split(rel)
    for pattern, text in ((_PATH_DATE, f"{folder}/"), (_NAME_DATE, name)):
        if match := pattern.search(text):
            year, month, day = (int(g) for g in match.groups())
            try:
                date(year, month, day)
            except ValueError:
                continue
            return year, month, day
    return None


@dataclass(frozen=True)
class Photo:
    rel: str
    taken: tuple[int, int, int] | None


class PhotoLibrary:
    """One photo folder: path checks, listings, index, JPEG rendering and caches."""

    def __init__(
        self,
        hass: HomeAssistant,
        folder: str,
        extra_folders: list[str],
        random_count: int,
        skip_screenshots: bool,
    ) -> None:
        self.hass = hass
        self.root = os.path.abspath(folder)
        # Files may be symlinks into other folders (PhotoPrism originals often are);
        # only these real locations are ever served.
        self._real_roots = tuple(
            os.path.realpath(p) for p in [self.root, *extra_folders] if p
        )
        self.random_count = random_count
        self.skip_screenshots = skip_screenshots
        self._thumbs: _LRU = _LRU(1500)
        self._fulls: _LRU = _LRU(20)
        self._decode = asyncio.Semaphore(2)  # keep small hosts responsive while converting
        self._index: list[Photo] = []
        self._index_time = 0.0
        self._index_lock = asyncio.Lock()

    # ---- paths -------------------------------------------------------------

    def safe_path(self, rel: str) -> str | None:
        """Map a library-relative path to a file system path, refusing anything outside the allowed folders."""
        rel = rel.strip("/")
        if rel and any(part in ("", ".", "..") for part in rel.split("/")):
            return None
        path = os.path.join(self.root, rel) if rel else self.root
        real = os.path.realpath(path)
        if not any(real == r or real.startswith(r + os.sep) for r in self._real_roots):
            return None
        return path if os.path.exists(real) else None

    @staticmethod
    def needs_conversion(rel: str) -> bool:
        return ext_of(rel) in CONVERT_EXTS

    def _slideshow_ok(self, name: str) -> bool:
        ext = ext_of(name)
        if ext not in PHOTO_EXTS:
            return False
        return not (self.skip_screenshots and ext in SCREENSHOT_EXTS)

    # ---- blocking helpers (run in the executor) ----------------------------

    def list_dir(self, rel: str) -> tuple[list[str], list[tuple[str, str]]]:
        """Return (sub-folders, [(file, "image"|"video")]) of a folder.

        A video with the same name as a photo in the same folder is the motion part
        of a Live Photo; it is left out so every Live Photo shows up once.
        """
        path = self.safe_path(rel)
        if path is None or not os.path.isdir(path):
            raise FileNotFoundError(rel)
        dirs: list[str] = []
        files: list[str] = []
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.name.startswith((".", "@", "#")):
                    continue
                try:
                    if entry.is_dir():
                        dirs.append(entry.name)
                    elif entry.is_file():
                        files.append(entry.name)
                except OSError:
                    continue
        photo_stems = {os.path.splitext(f)[0].lower() for f in files if ext_of(f) in PHOTO_EXTS}
        listed: list[tuple[str, str]] = []
        for name in sorted(files):
            ext = ext_of(name)
            if ext in PHOTO_EXTS:
                listed.append((name, "image"))
            elif ext in VIDEO_EXTS and os.path.splitext(name)[0].lower() not in photo_stems:
                listed.append((name, "video"))
        return sorted(dirs), listed

    def _scan(self) -> list[Photo]:
        """Walk the whole library (following symlinked folders) and date every photo."""
        photos: list[Photo] = []
        seen: set[str] = set()
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=True):
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "@", "#"))]
            real_dir = os.path.realpath(dirpath)
            if not any(real_dir == r or real_dir.startswith(r + os.sep) for r in self._real_roots):
                dirnames[:] = []
                continue
            rel_dir = os.path.relpath(dirpath, self.root)
            for name in filenames:
                if name.startswith(".") or not self._slideshow_ok(name):
                    continue
                real = os.path.realpath(os.path.join(dirpath, name))
                if real in seen:
                    continue
                seen.add(real)
                rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                photos.append(Photo(rel, photo_date(rel)))
        return photos

    @staticmethod
    def render_jpeg(path: str, max_side: int, quality: int) -> bytes:
        """Decode a photo (HEIC through pillow-heif) to an upright, downscaled JPEG."""
        with Image.open(path) as img:
            if img.format == "JPEG":
                img.draft("RGB", (max_side, max_side))
            img = ImageOps.exif_transpose(img)
            img.thumbnail((max_side, max_side))
            if img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=quality)
            return buf.getvalue()

    # ---- async API ---------------------------------------------------------

    async def async_jpeg(self, path: str, thumb: bool) -> bytes:
        cache = self._thumbs if thumb else self._fulls
        mtime = await self.hass.async_add_executor_job(os.path.getmtime, path)
        key = (path, mtime)
        if (data := cache.get_item(key)) is not None:
            return data
        size, quality = (THUMB_SIZE, THUMB_QUALITY) if thumb else (FULL_SIZE, FULL_QUALITY)
        async with self._decode:
            data = await self.hass.async_add_executor_job(self.render_jpeg, path, size, quality)
        cache.put(key, data)
        return data

    async def async_index(self) -> list[Photo]:
        async with self._index_lock:
            if not self._index or time.monotonic() - self._index_time > INDEX_TTL:
                self._index = await self.hass.async_add_executor_job(self._scan)
                self._index_time = time.monotonic()
        return self._index

    async def async_random(self) -> list[str]:
        index = await self.async_index()
        return [p.rel for p in random.sample(index, min(self.random_count, len(index)))]

    async def async_on_this_day(self, today: date | None = None) -> list[str]:
        """Photos taken on today's month and day in earlier years, newest year first."""
        today = today or date.today()
        index = await self.async_index()
        hits = [
            p for p in index
            if p.taken and p.taken[1] == today.month and p.taken[2] == today.day and p.taken[0] < today.year
        ]
        hits.sort(key=lambda p: (-p.taken[0], p.rel))
        return [p.rel for p in hits]


class _LRU(OrderedDict):
    def __init__(self, size: int) -> None:
        super().__init__()
        self._size = size

    def get_item(self, key):
        if key in self:
            self.move_to_end(key)
            return self[key]
        return None

    def put(self, key, value) -> None:
        self[key] = value
        self.move_to_end(key)
        while len(self) > self._size:
            self.popitem(last=False)
