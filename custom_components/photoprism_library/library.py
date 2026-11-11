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
import subprocess
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


def photo_stem(name: str) -> str:
    """Name without extension, lower case, with iCloud's "_HEVC" Live Photo suffix removed.

    IMG_1234.HEIC, IMG_1234.MOV and IMG_1234_HEVC.MOV all belong to the same photo.
    """
    stem = os.path.splitext(name)[0].lower()
    return stem[:-5] if stem.endswith("_hevc") else stem


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


@dataclass(frozen=True)
class DeletePlan:
    rel: str
    library_names: list[str]  # library-relative names of the photo's files (for PhotoPrism)
    links: list[str]  # symlinks in the library folder
    files: list[str]  # real files


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
        self.allow_delete = False
        self.photoprism = None  # PhotoPrismClient when deleting should also remove the photo there
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
        photo_stems = {photo_stem(f) for f in files if ext_of(f) in PHOTO_EXTS}
        listed: list[tuple[str, str]] = []
        for name in sorted(files):
            ext = ext_of(name)
            if ext in PHOTO_EXTS:
                listed.append((name, "image"))
            elif ext in VIDEO_EXTS and photo_stem(name) not in photo_stems:
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

    def _inside(self, real: str) -> bool:
        return any(real == r or real.startswith(r + os.sep) for r in self._real_roots)

    def plan_delete(self, rel: str) -> DeletePlan:
        """Everything that belongs to one photo: the file, its Live Photo video, edits, RAW, sidecars.

        Files sharing the photo's name (any extension) count as the same photo, both in the
        library folder and in the real folder the file lives in. Links are removed together
        with their targets. Directories are never touched.
        """
        rel = rel.strip("/")
        path = self.safe_path(rel)
        if path is None or not os.path.isfile(path) or ext_of(rel) not in PHOTO_EXTS | VIDEO_EXTS:
            raise FileNotFoundError(rel)
        stem = photo_stem(os.path.basename(rel))
        lib_dir = os.path.dirname(path)
        rel_dir = os.path.dirname(rel)
        library_names: list[str] = []
        links: list[str] = []
        files: list[str] = []

        def same_photo(name: str) -> bool:
            return photo_stem(name) == stem

        for name in sorted(os.listdir(lib_dir)):
            entry = os.path.join(lib_dir, name)
            if not same_photo(name) or os.path.isdir(entry):
                continue
            library_names.append(f"{rel_dir}/{name}" if rel_dir else name)
            if os.path.islink(entry):
                links.append(entry)
            real = os.path.realpath(entry)
            if os.path.isfile(real) and self._inside(real):
                files.append(real)
        real_dir = os.path.dirname(os.path.realpath(path))
        if self._inside(real_dir):
            for name in sorted(os.listdir(real_dir)):
                real = os.path.join(real_dir, name)
                if same_photo(name) and os.path.isfile(real) and not os.path.islink(real):
                    files.append(os.path.realpath(real))
        return DeletePlan(rel, library_names, sorted(set(links)), sorted(set(files)))

    def execute_delete(self, plan: DeletePlan) -> list[str]:
        """Remove the planned links and files (already-missing ones are skipped)."""
        removed: list[str] = []
        for target in [*plan.links, *plan.files]:
            if os.path.lexists(target) and not os.path.isdir(target):
                os.remove(target)
                removed.append(target)
        return removed

    def forget(self, plan: DeletePlan) -> None:
        """Drop deleted photos from the index and caches."""
        gone = {n.lower() for n in plan.library_names}
        self._index = [p for p in self._index if p.rel.lower() not in gone]
        for cache in (self._thumbs, self._fulls):
            for key in [k for k in cache if os.path.realpath(k[0]) in plan.files or k[0] in plan.links]:
                cache.pop(key, None)

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

    @staticmethod
    def render_video_thumb(path: str, max_side: int, quality: int) -> bytes:
        """A frame of a video as JPEG (1 s in, or the first frame of a shorter clip)."""
        scale = f"scale='min({max_side},iw)':'min({max_side},ih)':force_original_aspect_ratio=decrease"
        qscale = str(max(2, min(31, round((100 - quality) / 3))))
        for seek in ("1", "0"):
            result = subprocess.run(  # noqa: S603 - fixed arguments, path checked by safe_path
                ["ffmpeg", "-v", "error", "-ss", seek, "-i", path, "-frames:v", "1", "-vf", scale,
                 "-q:v", qscale, "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
                capture_output=True,
                timeout=60,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        raise ValueError(f"ffmpeg could not read a frame: {result.stderr.decode(errors='replace')[:200]}")

    # ---- async API ---------------------------------------------------------

    async def async_jpeg(self, path: str, thumb: bool) -> bytes:
        cache = self._thumbs if thumb else self._fulls
        mtime = await self.hass.async_add_executor_job(os.path.getmtime, path)
        key = (path, mtime)
        if (data := cache.get_item(key)) is not None:
            return data
        size, quality = (THUMB_SIZE, THUMB_QUALITY) if thumb else (FULL_SIZE, FULL_QUALITY)
        render = self.render_video_thumb if ext_of(path) in VIDEO_EXTS else self.render_jpeg
        async with self._decode:
            data = await self.hass.async_add_executor_job(render, path, size, quality)
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
