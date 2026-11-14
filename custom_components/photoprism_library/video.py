"""H.264 copies of videos for browsers that can't play the original.

iPhones record HEVC (H.265). Safari plays it, but Chrome, Edge and Firefox only do with a
hardware decoder they support (not on most Linux PCs): they play the sound over a black picture.
For those browsers the cards ask for /api/photoprism_library/video/<path> instead of the original:

* H.264 originals are sent as they are.
* Anything else is converted once to H.264 (at most 1280 px on the long side, 30 fps) and kept
  in Home Assistant's cache folder (not part of backups). The first viewer gets the copy while it
  is being made; later viewers get the finished file, with seeking. A conversion nobody watches
  any more is stopped (the background pass makes that copy later).
* Videos still waiting for a copy are converted in the background, one at a time at the lowest
  CPU priority, a few minutes after start and then every 6 hours; copies of removed videos are dropped.

A 4K HEVC video converts at roughly a third of real time on a Raspberry Pi 5 (software decoding
dominates), 1080p a little faster than real time.
"""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
import hashlib
import json
import logging
import os
import time
import uuid

from aiohttp import web

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLAYABLE_CODECS = {"h264"}  # every browser decodes these
MAX_SIDE = 1280
SETTINGS = f"h264-{MAX_SIDE}-crf23-30fps-v1"  # part of the cache key: changing it makes new copies
BIG_SIDE = 2000  # above this, skip HEVC deblocking while decoding (~20% faster, invisible after downscaling)
ON_DEMAND_LIMIT = 2  # conversions started by viewers at the same time
ABANDON_AFTER = 10  # s without a viewer before an on-demand conversion is stopped
CHUNK = 256 * 1024
ORPHAN_AGE = 3600  # leave just-written copies alone when pruning
_CACHED = {"Cache-Control": "private, max-age=86400"}


def _ffmpeg_args(src: str, out: str, big: bool) -> list[str]:
    scale = f"scale=w='if(gte(iw,ih),min({MAX_SIDE},iw),-2)':h='if(gte(iw,ih),-2,min({MAX_SIDE},ih))'"
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    if big:
        args += ["-skip_loop_filter", "all"]
    return args + [
        "-i", src,
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", scale, "-fpsmax", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-g", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        # Fragmented MP4 can be played while it is still being written
        "-movflags", "frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", out,
    ]


def _renice(pid: int, value: int) -> None:
    """Set the priority of every thread of a process (Linux nice values are per thread)."""
    try:
        tids = [int(t) for t in os.listdir(f"/proc/{pid}/task")]
    except (OSError, ValueError):
        tids = [pid]
    for tid in tids:
        with contextlib.suppress(OSError):
            os.setpriority(os.PRIO_PROCESS, tid, value)


def _kill(proc: asyncio.subprocess.Process | None) -> None:
    if proc is not None and proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()


def _remove(*paths: str) -> None:
    for path in paths:
        with contextlib.suppress(OSError):
            os.remove(path)


@dataclass
class _Job:
    final: str
    tmp: str  # fragmented MP4 that ffmpeg writes and viewers read while it grows
    background: bool  # started by the background pass (lowest priority)
    keep: bool  # finish even when nobody watches (the background pass waits for it)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    ok: bool = False
    pid: int | None = None
    viewers: int = 0
    task: asyncio.Task | None = None
    abandoned: bool = False


class VideoCache:
    """Probes videos, converts the ones browsers can't play and serves the result."""

    def __init__(self, hass: HomeAssistant, lib) -> None:
        self.hass = hass
        self.lib = lib
        # Config.cache_path (not part of backups) exists since Home Assistant 2026.3
        cache_path = getattr(hass.config, "cache_path", None)
        self.dir = cache_path(DOMAIN, "video") if cache_path else hass.config.path(".cache", DOMAIN, "video")
        self._probes: dict[tuple[str, int, int], tuple[str, int]] = {}
        self._jobs: dict[str, _Job] = {}
        self._on_demand = asyncio.Semaphore(ON_DEMAND_LIMIT)
        self._converting = False
        self._stopped = False

    # ---- files ---------------------------------------------------------------

    @staticmethod
    def _identity(path: str) -> tuple[str, int, int]:
        """The real file (library entries are often symlinks) with its mtime and size."""
        real = os.path.realpath(path)
        st = os.stat(real)
        return real, st.st_mtime_ns, st.st_size

    def _cache_name(self, ident: tuple[str, int, int]) -> str:
        digest = hashlib.sha1(f"{ident[0]}|{ident[1]}|{ident[2]}|{SETTINGS}".encode()).hexdigest()
        return os.path.join(self.dir, f"{digest}.mp4")

    async def _probe(self, ident: tuple[str, int, int]) -> tuple[str | None, int]:
        """(video codec, long side) of a file; (None, 0) if ffprobe can't read it right now."""
        if (hit := self._probes.get(ident)) is not None:
            return hit
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height", "-of", "json", ident[0],
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), 60)
            stream = (json.loads(out or b"{}").get("streams") or [{}])[0]
            codec = stream.get("codec_name")
            side = max(int(stream.get("width") or 0), int(stream.get("height") or 0))
        except (OSError, ValueError, asyncio.TimeoutError) as err:
            _LOGGER.debug("ffprobe failed for %s: %s", ident[0], err)
            return None, 0
        finally:
            _kill(proc)
        if not codec:
            return None, 0
        self._probes[ident] = (codec, side)  # failures are not remembered: tried again next time
        return codec, side

    # ---- conversion ----------------------------------------------------------

    def _start(self, real: str, final: str, big: bool, background: bool) -> _Job | None:
        """Start converting, or join the conversion already running for this copy."""
        if self._stopped:
            return None
        job = self._jobs.get(final)
        if job is not None and not job.abandoned:
            if background:
                job.keep = True
            elif job.background and job.pid:
                # Someone is watching now: the background conversion gets normal priority
                self.hass.async_add_executor_job(_renice, job.pid, 0)
            return job
        # Unique temporary names: an abandoned or old conversion of the same copy may still be cleaning up
        job = _Job(
            final=final, tmp=f"{final}.{uuid.uuid4().hex}.part", background=background, keep=background
        )
        self._jobs[final] = job
        # Background tasks are cancelled at shutdown instead of holding it up
        job.task = self.hass.async_create_background_task(self._run(job, real, big), f"{DOMAIN} convert video")
        return job

    async def _run(self, job: _Job, real: str, big: bool) -> None:
        started = time.monotonic()
        proc = remux = None
        remuxed = f"{job.tmp}.mp4"
        try:
            await self.hass.async_add_executor_job(lambda: os.makedirs(self.dir, exist_ok=True))
            cmd = _ffmpeg_args(real, job.tmp, big)
            if job.background:
                cmd = ["nice", "-n", "19", *cmd]
            async with contextlib.nullcontext() if job.background else self._on_demand:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
                )
                job.pid = proc.pid
                _, err = await proc.communicate()
            if proc.returncode != 0:
                if proc.returncode > 0:  # negative: killed on purpose
                    _LOGGER.warning("Could not convert %s: %s", real, err.decode(errors="replace")[-300:])
                return
            # The streamed file can't be seeked well; a quick copy with the index in front can.
            remux = await asyncio.create_subprocess_exec(
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", job.tmp, "-c", "copy",
                "-movflags", "+faststart", "-f", "mp4", remuxed,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            _, err = await remux.communicate()
            if remux.returncode != 0:
                _LOGGER.warning("Could not finish the copy of %s: %s", real, err.decode(errors="replace")[-300:])
                return
            await self.hass.async_add_executor_job(os.replace, remuxed, job.final)
            job.ok = True
            _LOGGER.debug("Converted %s in %.0f s", real, time.monotonic() - started)
        except OSError as err:  # ffmpeg missing, disk full...
            _LOGGER.warning("Could not convert %s: %s", real, err)
        finally:
            _kill(proc)  # still running when cancelled (unload, shutdown, nobody watching)
            _kill(remux)
            job.done.set()
            if self._jobs.get(job.final) is job:
                self._jobs.pop(job.final)
            # Viewers still streaming keep their open file; the names can go. Pruning catches
            # anything left behind if this fails (e.g. during shutdown).
            with contextlib.suppress(Exception):
                await self.hass.async_add_executor_job(_remove, job.tmp, remuxed)

    def _viewer_left(self, job: _Job) -> None:
        job.viewers -= 1
        if job.viewers > 0 or job.done.is_set():
            return
        if job.keep:  # the background pass needs it: back to the lowest priority
            if job.pid:
                self.hass.async_add_executor_job(_renice, job.pid, 19)
            return

        def _abandon() -> None:  # a short grace period: browsers re-request, people swipe back
            if job.viewers == 0 and not job.keep and not job.done.is_set() and job.task is not None:
                job.abandoned = True
                job.task.cancel()

        self.hass.loop.call_later(ABANDON_AFTER, _abandon)

    def stop(self) -> None:
        """Stop every conversion, running or waiting (config entry unloaded)."""
        self._stopped = True
        for job in list(self._jobs.values()):
            if job.task is not None:
                job.task.cancel()

    # ---- serving -------------------------------------------------------------

    async def async_response(self, request: web.Request, path: str) -> web.StreamResponse:
        try:
            ident = await self.hass.async_add_executor_job(self._identity, path)
        except OSError as err:
            raise web.HTTPNotFound from err
        codec, side = await self._probe(ident)
        if codec is None or codec in PLAYABLE_CODECS:
            # Playable already (or unreadable right now: let the browser try the original)
            return web.FileResponse(ident[0], headers={"Content-Type": "video/mp4", **_CACHED})
        final = self._cache_name(ident)
        if await self.hass.async_add_executor_job(os.path.isfile, final):
            return web.FileResponse(final, headers=_CACHED)
        job = self._start(ident[0], final, side > BIG_SIDE, background=False)
        if job is None:
            raise web.HTTPServiceUnavailable
        job.viewers += 1
        try:
            return await self._stream(request, job)
        finally:
            self._viewer_left(job)

    async def _stream(self, request: web.Request, job: _Job) -> web.StreamResponse:
        """Send the copy while ffmpeg writes it."""
        handle = None
        while handle is None:
            if job.done.is_set() and not await self.hass.async_add_executor_job(os.path.exists, job.tmp):
                if job.ok:
                    return web.FileResponse(job.final, headers=_CACHED)
                raise web.HTTPUnsupportedMediaType(text="The video could not be converted")
            try:
                handle = await self.hass.async_add_executor_job(open, job.tmp, "rb")
            except OSError:  # not created yet (waiting for a free slot or for ffmpeg to start)
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(job.done.wait(), 0.3)
        response = web.StreamResponse(headers={"Content-Type": "video/mp4", "Cache-Control": "no-store"})
        try:
            await response.prepare(request)
            while True:
                chunk = await self.hass.async_add_executor_job(handle.read, CHUNK)
                if chunk:
                    await response.write(chunk)
                    continue
                if job.done.is_set():
                    break  # ffmpeg is done and everything it wrote has been sent
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(job.done.wait(), 0.3)
            await response.write_eof()
        except ConnectionError:
            pass  # the viewer moved on
        finally:
            await self.hass.async_add_executor_job(handle.close)
        return response

    # ---- background ------------------------------------------------------------

    async def async_convert_all(self) -> None:
        """Drop copies nobody needs, then make copies for every video that needs one."""
        if self._converting:  # the previous run is still going
            return
        self._converting = True
        try:
            await self._convert_all()
        finally:
            self._converting = False

    async def _convert_all(self) -> None:
        videos = await self.hass.async_add_executor_job(self.lib.video_files)
        wanted: set[str] = set()
        todo: list[tuple[str, str, int]] = []
        for path in videos:
            try:
                ident = await self.hass.async_add_executor_job(self._identity, path)
            except OSError:
                continue
            codec, side = await self._probe(ident)
            final = self._cache_name(ident)
            if codec is None:  # unreadable right now: keep any copy it has
                wanted.add(os.path.basename(final))
                continue
            if codec in PLAYABLE_CODECS:
                continue
            wanted.add(os.path.basename(final))
            todo.append((ident[0], final, side))
        removed = await self.hass.async_add_executor_job(self._prune, wanted)
        made = 0
        for real, final, side in todo:
            if await self.hass.async_add_executor_job(os.path.isfile, final):
                continue
            job = self._start(real, final, side > BIG_SIDE, background=True)
            if job is None:  # stopped
                return
            await job.done.wait()
            made += job.ok
        if made or removed:
            _LOGGER.info("Video copies for browsers without HEVC: %s made, %s removed", made, removed)

    def _prune(self, wanted: set[str]) -> int:
        """Remove copies of videos that are gone or changed, and leftovers of interrupted conversions."""
        if not os.path.isdir(self.dir):
            return 0
        busy = [job.final for job in list(self._jobs.values())]
        removed = 0
        now = time.time()
        for entry in os.scandir(self.dir):
            if entry.name in wanted or not entry.is_file() or any(entry.path.startswith(b) for b in busy):
                continue
            with contextlib.suppress(OSError):
                if now - entry.stat().st_mtime > ORPHAN_AGE:
                    os.remove(entry.path)
                    removed += 1
        return removed
