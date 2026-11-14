"""H.264 copies of videos for browsers that can't play the original.

iPhones record HEVC (H.265). Safari plays it, but Chrome, Edge and Firefox only do with a
hardware decoder they support (not on most Linux PCs): they play the sound over a black picture.
For those browsers the cards ask for /api/photoprism_library/video/<path> instead of the original:

* H.264 originals are sent as they are.
* Anything else is converted once to H.264 (at most 1280 px on the long side, 30 fps) and kept
  in Home Assistant's cache folder (not part of backups). The first viewer gets the copy while it
  is being made; later viewers get the finished file, with seeking.
* Videos still waiting for a copy are converted in the background, one at a time at the lowest
  CPU priority, a few minutes after start and then every 6 hours; copies of removed videos are dropped.

A 4K HEVC video converts at roughly a third of real time on a Raspberry Pi 5 (software decoding
dominates), 1080p a little faster than real time.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field

from aiohttp import web

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLAYABLE_CODECS = {"h264"}  # every browser decodes these
MAX_SIDE = 1280
SETTINGS = f"h264-{MAX_SIDE}-crf23-30fps-v1"  # part of the cache key: changing it makes new copies
BIG_SIDE = 2000  # above this, skip HEVC deblocking while decoding (~20% faster, invisible after downscaling)
ON_DEMAND_LIMIT = 2  # conversions started by viewers at the same time
CHUNK = 256 * 1024
ORPHAN_AGE = 3600  # leave just-written copies alone when pruning


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


@dataclass
class _Job:
    tmp: str
    final: str
    done: asyncio.Event = field(default_factory=asyncio.Event)
    ok: bool = False
    pid: int | None = None


class VideoCache:
    """Probes videos, converts the ones browsers can't play and serves the result."""

    def __init__(self, hass: HomeAssistant, lib) -> None:
        self.hass = hass
        self.lib = lib
        self.dir = hass.config.cache_path(DOMAIN, "video")
        self._probes: dict[tuple[str, int, int], tuple[str | None, int]] = {}
        self._jobs: dict[str, _Job] = {}
        self._on_demand = asyncio.Semaphore(ON_DEMAND_LIMIT)
        self._procs: set[asyncio.subprocess.Process] = set()
        self._converting = False

    # ---- blocking helpers ----------------------------------------------------

    def _identity(self, real: str) -> tuple[str, int, int]:
        st = os.stat(real)
        return real, st.st_mtime_ns, st.st_size

    def _cache_name(self, ident: tuple[str, int, int]) -> str:
        digest = hashlib.sha1(f"{ident[0]}|{ident[1]}|{ident[2]}|{SETTINGS}".encode()).hexdigest()
        return os.path.join(self.dir, f"{digest}.mp4")

    async def _probe(self, ident: tuple[str, int, int]) -> tuple[str | None, int]:
        """(video codec, long side) of a file; (None, 0) if ffprobe can't read it."""
        if (hit := self._probes.get(ident)) is not None:
            return hit
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height", "-of", "json", ident[0],
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), 60)
            stream = (json.loads(out or b"{}").get("streams") or [{}])[0]
            result = (stream.get("codec_name"), max(int(stream.get("width") or 0), int(stream.get("height") or 0)))
        except (OSError, ValueError, asyncio.TimeoutError) as err:
            _LOGGER.debug("ffprobe failed for %s: %s", ident[0], err)
            result = (None, 0)
        self._probes[ident] = result
        return result

    # ---- conversion ----------------------------------------------------------

    def _start(self, real: str, final: str, big: bool, background: bool) -> _Job:
        """Start converting (or join the conversion already running for this copy)."""
        if (job := self._jobs.get(final)) is not None:
            if not background and job.pid:
                # Someone is watching now: a background conversion gets normal priority
                self.hass.async_add_executor_job(_renice, job.pid, 0)
            return job
        job = _Job(tmp=f"{final}.{os.getpid()}.part", final=final)
        self._jobs[final] = job
        # Background tasks are cancelled at shutdown instead of holding it up
        self.hass.async_create_background_task(self._run(job, real, big, background), f"{DOMAIN} convert video")
        return job

    async def _run(self, job: _Job, real: str, big: bool, background: bool) -> None:
        started = time.monotonic()
        proc = None
        try:
            await self.hass.async_add_executor_job(lambda: os.makedirs(self.dir, exist_ok=True))
            cmd = _ffmpeg_args(real, job.tmp, big)
            if background:
                cmd = ["nice", "-n", "19", *cmd]
            async with contextlib.nullcontext() if background else self._on_demand:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
                )
                job.pid = proc.pid
                self._procs.add(proc)
                _, err = await proc.communicate()
            if proc.returncode != 0:
                _LOGGER.warning("Could not convert %s: %s", real, err.decode(errors="replace")[-300:])
                return
            # The streamed file can't be seeked well; a quick copy with the index in front can.
            remux = await asyncio.create_subprocess_exec(
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", job.tmp, "-c", "copy",
                "-movflags", "+faststart", "-f", "mp4", f"{job.final}.tmp",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            self._procs.add(remux)
            _, err = await remux.communicate()
            self._procs.discard(remux)
            if remux.returncode != 0:
                _LOGGER.warning("Could not finish the copy of %s: %s", real, err.decode(errors="replace")[-300:])
                return
            await self.hass.async_add_executor_job(os.replace, f"{job.final}.tmp", job.final)
            job.ok = True
            _LOGGER.debug("Converted %s in %.0f s", real, time.monotonic() - started)
        except OSError as err:  # ffmpeg missing, disk full...
            _LOGGER.warning("Could not convert %s: %s", real, err)
        finally:
            if proc is not None:
                self._procs.discard(proc)
                if proc.returncode is None:  # cancelled (unload, shutdown)
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
            job.done.set()
            self._jobs.pop(job.final, None)
            # Viewers still streaming keep their open file; the name can go.
            for leftover in (job.tmp, f"{job.final}.tmp"):
                with contextlib.suppress(OSError):
                    await self.hass.async_add_executor_job(os.remove, leftover)

    def stop(self) -> None:
        for proc in list(self._procs):
            with contextlib.suppress(ProcessLookupError):
                proc.kill()

    # ---- serving -------------------------------------------------------------

    async def async_response(self, request: web.Request, real: str) -> web.StreamResponse:
        try:
            ident = await self.hass.async_add_executor_job(self._identity, real)
        except OSError as err:
            raise web.HTTPNotFound from err
        codec, side = await self._probe(ident)
        if codec is None or codec in PLAYABLE_CODECS:
            # Playable already (or unreadable: let the browser try the original)
            return web.FileResponse(real, headers={"Content-Type": "video/mp4", "Cache-Control": "private, max-age=86400"})
        final = self._cache_name(ident)
        if await self.hass.async_add_executor_job(os.path.isfile, final):
            return web.FileResponse(final, headers={"Cache-Control": "private, max-age=86400"})
        job = self._start(real, final, side > BIG_SIDE, background=False)
        return await self._stream(request, job)

    async def _stream(self, request: web.Request, job: _Job) -> web.StreamResponse:
        """Send the copy while ffmpeg writes it."""
        # Wait for ffmpeg to create the file (or fail)
        while not await self.hass.async_add_executor_job(os.path.exists, job.tmp):
            if job.done.is_set():
                if job.ok:
                    return web.FileResponse(job.final, headers={"Cache-Control": "private, max-age=86400"})
                raise web.HTTPUnsupportedMediaType(text="The video could not be converted")
            await asyncio.sleep(0.2)
        try:
            handle = await self.hass.async_add_executor_job(open, job.tmp, "rb")
        except OSError as err:  # finished and removed in between
            if job.ok:
                return web.FileResponse(job.final, headers={"Cache-Control": "private, max-age=86400"})
            raise web.HTTPUnsupportedMediaType(text="The video could not be converted") from err
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
        except (ConnectionResetError, ConnectionError):
            pass  # the viewer moved on; the conversion carries on for next time
        finally:
            await self.hass.async_add_executor_job(handle.close)
        return response

    # ---- background ------------------------------------------------------------

    async def async_convert_all(self) -> None:
        """Make copies for every video that needs one, then drop copies nobody needs."""
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
        made = 0
        for real in videos:
            try:
                ident = await self.hass.async_add_executor_job(self._identity, real)
            except OSError:
                continue
            codec, side = await self._probe(ident)
            if codec is None or codec in PLAYABLE_CODECS:
                continue
            final = self._cache_name(ident)
            wanted.add(os.path.basename(final))
            if await self.hass.async_add_executor_job(os.path.isfile, final):
                continue
            job = self._start(real, final, side > BIG_SIDE, background=True)
            await job.done.wait()
            made += job.ok
        removed = await self.hass.async_add_executor_job(self._prune, wanted)
        if made or removed:
            _LOGGER.info("Video copies for browsers without HEVC: %s made, %s removed", made, removed)

    def _prune(self, wanted: set[str]) -> int:
        removed = 0
        if not os.path.isdir(self.dir):
            return 0
        now = time.time()
        for entry in os.scandir(self.dir):
            if entry.name in wanted or not entry.is_file():
                continue
            if any(entry.path.startswith(j.final) for j in list(self._jobs.values())):
                continue
            with contextlib.suppress(OSError):
                if now - entry.stat().st_mtime > ORPHAN_AGE:
                    os.remove(entry.path)
                    removed += 1
        return removed
