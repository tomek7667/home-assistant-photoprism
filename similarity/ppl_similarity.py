"""Similar photos for PhotoPrism Library.

Every photo and video (one frame) of a library gets an image embedding (SigLIP 2).
The embeddings live in a SQLite file; a search compares one photo with all others
by cosine similarity, which takes milliseconds even on a Raspberry Pi.

Server (a sidecar container next to Home Assistant), indexing new files at low priority:

    python ppl_similarity.py serve --root /media/zdjecia --db /data/index.db

Index a whole library in one go, e.g. on a machine with a GPU, then copy the db:

    python ppl_similarity.py index --root ~/mnt/zdjecia --db index.db --device cuda \\
        --map /photoprism/source=~/mnt/icloud_photos

Paths are relative to the root, the same as in Home Assistant. ``--map`` rewrites
absolute symlink targets that only exist inside containers.
"""
from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import io
import json
import logging
import os
import queue
import sqlite3
import stat
import subprocess
import threading
import time

import numpy as np
from PIL import Image, ImageOps

_LOGGER = logging.getLogger("ppl_similarity")

MODEL = "ViT-B-16-SigLIP2"
PRETRAINED = "webli"
PHOTO_EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp", ".gif"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
DECODE_SIZE = 512  # photos are shrunk to this before the model's own resize, for speed


def ext_of(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def photo_stem(name: str) -> str:
    """IMG_1234.HEIC, IMG_1234.MOV and IMG_1234_HEVC.MOV belong to the same photo."""
    stem = os.path.splitext(name)[0].lower()
    return stem[:-5] if stem.endswith("_hevc") else stem


# ---- library -------------------------------------------------------------------


@dataclass(frozen=True)
class File:
    rel: str
    real: str
    kind: str  # "image" or "video"
    size: int
    mtime: float


class Library:
    """Walks a library like Home Assistant does: symlinks followed, Live Photo videos skipped."""

    def __init__(self, root: str, maps: list[tuple[str, str]]) -> None:
        self.root = os.path.abspath(os.path.expanduser(root))
        self.maps = [(src.rstrip("/"), os.path.expanduser(dst).rstrip("/")) for src, dst in maps]

    def _map(self, path: str) -> str:
        for src, dst in self.maps:
            if path == src or path.startswith(src + "/"):
                return dst + path[len(src):]
        return path

    def resolve(self, path: str) -> str:
        """Follow symlinks at the end of path, rewriting mapped absolute targets."""
        for _ in range(40):
            if not os.path.islink(path):
                return path
            target = os.readlink(path)
            if not os.path.isabs(target):
                target = os.path.join(os.path.dirname(path), target)
            path = self._map(os.path.normpath(target))
        return path

    def file(self, rel: str) -> File | None:
        """One library file by its relative path, resolved component by component."""
        rel = rel.strip("/")
        if not rel or any(part in ("", ".", "..") for part in rel.split("/")):
            return None
        path = self.resolve(self.root)
        for part in rel.split("/"):
            path = self.resolve(os.path.join(path, part))
        try:
            st = os.stat(path)
        except OSError:
            return None
        ext = ext_of(rel)
        kind = "image" if ext in PHOTO_EXTS else "video" if ext in VIDEO_EXTS else None
        if kind is None or not stat.S_ISREG(st.st_mode):
            return None
        return File(rel, path, kind, st.st_size, st.st_mtime)

    def walk(self) -> Iterator[File]:
        stack = [("", self.resolve(self.root))]
        seen_dirs: set[str] = set()
        seen_files: set[str] = set()
        while stack:
            rel_dir, real_dir = stack.pop()
            if real_dir in seen_dirs:
                continue
            seen_dirs.add(real_dir)
            try:
                entries = list(os.scandir(real_dir))
            except OSError as err:
                _LOGGER.warning("Cannot list %s: %s", rel_dir or "/", err)
                continue
            files = []
            for entry in entries:
                if entry.name.startswith((".", "@", "#")):
                    continue
                rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                target = self.resolve(entry.path)
                try:
                    st = os.stat(target)
                except OSError:
                    continue
                if stat.S_ISDIR(st.st_mode):
                    stack.append((rel, target))
                elif stat.S_ISREG(st.st_mode):
                    files.append((entry.name, rel, target, st))
            photo_stems = {photo_stem(n) for n, *_ in files if ext_of(n) in PHOTO_EXTS}
            for name, rel, target, st in sorted(files):
                ext = ext_of(name)
                if ext in PHOTO_EXTS:
                    kind = "image"
                elif ext in VIDEO_EXTS and photo_stem(name) not in photo_stems:
                    kind = "video"
                else:
                    continue
                if target in seen_files:
                    continue
                seen_files.add(target)
                yield File(rel, target, kind, st.st_size, st.st_mtime)


def load_image(file: File) -> Image.Image:
    """An upright RGB image of a photo, or a frame of a video (1 s in)."""
    if file.kind == "video":
        for seek in ("1", "0"):
            result = subprocess.run(  # noqa: S603 - fixed arguments
                ["ffmpeg", "-v", "error", "-ss", seek, "-i", file.real, "-frames:v", "1",
                 "-vf", f"scale='min({DECODE_SIZE},iw)':-2", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
                capture_output=True, timeout=120, check=False,
            )
            if result.returncode == 0 and result.stdout:
                return Image.open(io.BytesIO(result.stdout)).convert("RGB")
        raise ValueError(f"no frame: {result.stderr.decode(errors='replace')[:200]}")
    with Image.open(file.real) as img:
        if img.format == "JPEG":
            img.draft("RGB", (DECODE_SIZE, DECODE_SIZE))
        img = ImageOps.exif_transpose(img)
        img.thumbnail((DECODE_SIZE, DECODE_SIZE))
        return img.convert("RGB")


# ---- model -----------------------------------------------------------------------


class Embedder:
    def __init__(self, device: str, threads: int) -> None:
        import open_clip  # noqa: PLC0415 - heavy
        import torch  # noqa: PLC0415

        if device == "cpu":
            torch.set_num_threads(threads)
        self.torch = torch
        self.device = device
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            MODEL, pretrained=PRETRAINED, device=device
        )
        self.model.eval()
        self.lock = threading.Lock()
        self.model_id = f"{MODEL}/{PRETRAINED}/{open_clip.__version__}"

    def embed(self, images: list[Image.Image]) -> np.ndarray:
        """Unit-length float32 embeddings, one row per image."""
        torch = self.torch
        batch = torch.stack([self.preprocess(img) for img in images]).to(self.device)
        with self.lock, torch.no_grad():
            if self.device == "cuda":
                with torch.autocast("cuda", dtype=torch.float16):
                    features = self.model.encode_image(batch)
            else:
                features = self.model.encode_image(batch)
            features = torch.nn.functional.normalize(features.float(), dim=-1)
        return features.cpu().numpy().astype(np.float32)


# ---- index -------------------------------------------------------------------------


class Index:
    """Embeddings in SQLite, mirrored in memory as one matrix for fast search."""

    def __init__(self, path: str, model_id: str | None) -> None:
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS items (path TEXT PRIMARY KEY, kind TEXT, size INTEGER, "
            "mtime REAL, emb BLOB, error TEXT, updated REAL)"
        )
        self.conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.lock = threading.RLock()
        stored = self.conn.execute("SELECT value FROM meta WHERE key='model'").fetchone()
        stored_model = stored[0] if stored else None
        # The model name (not the library version) decides whether embeddings compare
        if model_id and stored_model and stored_model.split("/")[:2] != model_id.split("/")[:2]:
            _LOGGER.warning("Model changed from %s to %s; indexing everything again", stored_model, model_id)
            self.conn.execute("DELETE FROM items")
        if model_id:
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES ('model', ?)", (model_id,))
        self.conn.commit()
        self._load()

    def _load(self) -> None:
        rows = self.conn.execute("SELECT path, emb FROM items WHERE emb IS NOT NULL").fetchall()
        self.paths: list[str | None] = [r[0] for r in rows]
        self.pos = {p: i for i, p in enumerate(self.paths)}
        dim = len(rows[0][1]) // 4 if rows else 768
        self.matrix = np.zeros((max(len(rows), 1024), dim), dtype=np.float32)
        for i, (_, emb) in enumerate(rows):
            self.matrix[i] = np.frombuffer(emb, dtype=np.float32)
        self.count = len(rows)

    def known(self) -> dict[str, tuple[int, float, bool]]:
        """path -> (size, mtime, done) for everything tried, embedded or failed."""
        with self.lock:
            rows = self.conn.execute("SELECT path, size, mtime, emb IS NOT NULL OR error IS NOT NULL FROM items")
            return {p: (s, m, bool(d)) for p, s, m, d in rows}

    def put(self, file: File, emb: np.ndarray | None, error: str | None = None, commit: bool = True) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO items VALUES (?, ?, ?, ?, ?, ?, ?)",
                (file.rel, file.kind, file.size, file.mtime,
                 emb.astype(np.float32).tobytes() if emb is not None else None, error, time.time()),
            )
            if commit:
                self.conn.commit()
            if emb is None:
                self._drop(file.rel)
                return
            if self.count == 0 and self.matrix.shape[1] != emb.shape[0]:
                self.matrix = np.zeros((len(self.matrix), emb.shape[0]), dtype=np.float32)
            row = self.pos.get(file.rel)
            if row is None:
                row = self.count
                if row >= len(self.matrix):
                    grown = np.zeros((len(self.matrix) * 2, self.matrix.shape[1]), dtype=np.float32)
                    grown[: len(self.matrix)] = self.matrix
                    self.matrix = grown
                self.paths.append(file.rel)
                self.pos[file.rel] = row
                self.count += 1
            self.matrix[row] = emb

    def commit(self) -> None:
        with self.lock:
            self.conn.commit()

    def _drop(self, path: str) -> None:
        if (row := self.pos.pop(path, None)) is not None:
            self.paths[row] = None
            self.matrix[row] = 0

    def remove(self, paths: list[str]) -> None:
        with self.lock:
            self.conn.executemany("DELETE FROM items WHERE path = ?", [(p,) for p in paths])
            self.conn.commit()
            for path in paths:
                self._drop(path)

    def vector(self, path: str) -> np.ndarray | None:
        with self.lock:
            row = self.pos.get(path)
            return None if row is None else self.matrix[row].copy()

    def search(self, query: np.ndarray, min_score: float, limit: int, exclude: str) -> tuple[list[dict], int]:
        with self.lock:
            scores = self.matrix[: self.count] @ query
            paths = list(self.paths[: self.count])
        hits = np.flatnonzero(scores >= min_score)
        hits = hits[np.argsort(-scores[hits])]
        results = [
            {"path": paths[i], "score": round(float(scores[i]), 4)}
            for i in hits
            if paths[i] is not None and paths[i] != exclude
        ]
        return results[:limit], len(results)

    def stats(self) -> dict:
        with self.lock:
            embedded, failed = self.conn.execute(
                "SELECT SUM(emb IS NOT NULL), SUM(error IS NOT NULL) FROM items"
            ).fetchone()
        return {"indexed": embedded or 0, "failed": failed or 0}


# ---- indexing ------------------------------------------------------------------------


def pending(library: Library, index: Index) -> tuple[list[File], list[str], int]:
    """Files that are new or changed, paths that are gone, and the library size."""
    known = index.known()
    todo, seen = [], set()
    for file in library.walk():
        seen.add(file.rel)
        old = known.get(file.rel)
        if old is None or not old[2] or old[0] != file.size or abs(old[1] - file.mtime) > 1:
            todo.append(file)
    gone = [p for p in known if p not in seen]
    return todo, gone, len(seen)


def embed_files(embedder: Embedder, index: Index, files: list[File], workers: int, batch: int,
                progress=None) -> None:
    """Decode with a thread pool, embed in batches; failures are stored and not retried."""
    done = 0
    with ThreadPoolExecutor(workers) as pool:
        for start in range(0, len(files), batch):
            chunk = files[start : start + batch]
            loaded = list(pool.map(_try_load, chunk))
            images = [(f, img) for f, (img, _) in zip(chunk, loaded) if img is not None]
            for f, (img, err) in zip(chunk, loaded):
                if img is None:
                    index.put(f, None, err, commit=False)
            if images:
                vectors = embedder.embed([img for _, img in images])
                for (f, _), vec in zip(images, vectors):
                    index.put(f, vec, commit=False)
            index.commit()
            done += len(chunk)
            if progress:
                progress(done, len(files))


def _try_load(file: File) -> tuple[Image.Image | None, str | None]:
    try:
        return load_image(file), None
    except Exception as err:  # noqa: BLE001 - one bad file mustn't stop the rest
        return None, f"{type(err).__name__}: {err}"[:300]


def cmd_index(args) -> None:
    library = Library(args.root, parse_maps(args.map))
    embedder = Embedder(args.device, args.threads)
    index = Index(args.db, embedder.model_id)
    started = time.monotonic()
    todo, gone, total = pending(library, index)
    index.remove(gone)
    _LOGGER.info("Library: %d files, %d to index, %d gone", total, len(todo), len(gone))

    def progress(done: int, count: int) -> None:
        if done % 500 < args.batch or done == count:
            rate = done / max(time.monotonic() - started, 1e-6)
            _LOGGER.info("%d / %d  (%.1f files/s, %.0f min left)", done, count, rate, (count - done) / max(rate, 1e-6) / 60)

    embed_files(embedder, index, todo, args.workers, args.batch, progress)
    _LOGGER.info("Done: %s", index.stats())


# ---- server ---------------------------------------------------------------------------


class Service:
    def __init__(self, args) -> None:
        self.args = args
        self.library = Library(args.root, parse_maps(args.map))
        self.embedder = Embedder(args.device, args.threads)
        self.index = Index(args.db, self.embedder.model_id)
        self.urgent: queue.Queue[str] = queue.Queue()
        self.total = None
        self.pending = 0
        self.last_scan = None
        self.scanning = False
        self.rescan = threading.Event()

    def worker(self) -> None:
        """Scan every few minutes and index new files, at low priority."""
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), self.args.nice)
        except OSError:
            pass
        while True:
            self.scanning = True
            try:
                todo, gone, self.total = pending(self.library, self.index)
                self.index.remove(gone)
                self.pending = len(todo)
                self.last_scan = time.time()
                if todo or gone:
                    _LOGGER.info("%d new or changed files, %d gone", len(todo), len(gone))
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Scan failed")
                todo = []
            self.scanning = False
            for start in range(0, len(todo), self.args.batch):
                chunk = todo[start : start + self.args.batch]
                embed_files(self.embedder, self.index, chunk, 1, self.args.batch)
                self.pending = max(0, len(todo) - start - len(chunk))
                if self.rescan.is_set():
                    break
            self.rescan.wait(self.args.scan_minutes * 60)
            self.rescan.clear()

    def similar(self, rel: str, min_score: float, limit: int) -> dict:
        query = self.index.vector(rel)
        if query is None:
            # Not indexed yet: do this one now, ahead of the queue
            file = self.library.file(rel)
            if file is None:
                raise FileNotFoundError(rel)
            image, err = _try_load(file)
            if image is None:
                raise ValueError(err)
            query = self.embedder.embed([image])[0]
            self.index.put(file, query)
        results, total = self.index.search(query, min_score, limit, rel)
        return {"query": rel, "results": results, "total": total}

    def status(self) -> dict:
        stats = self.index.stats()
        return {
            **stats,
            "total": self.total,
            "pending": self.pending,
            "scanning": self.scanning,
            "last_scan": self.last_scan,
            "model": self.embedder.model_id,
            "device": self.args.device,
        }


def cmd_serve(args) -> None:
    from aiohttp import web  # noqa: PLC0415

    service = Service(args)
    threading.Thread(target=service.worker, name="indexer", daemon=True).start()

    @web.middleware
    async def auth(request, handler):
        if args.token and request.headers.get("Authorization") != f"Bearer {args.token}":
            raise web.HTTPUnauthorized
        return await handler(request)

    async def status(request):
        return web.json_response(service.status())

    async def similar(request):
        rel = request.query.get("path", "")
        try:
            min_score = float(request.query.get("min", "0.8"))
            limit = max(1, min(int(request.query.get("limit", "300")), 5000))
        except ValueError as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        try:
            result = await asyncio.get_running_loop().run_in_executor(None, service.similar, rel, min_score, limit)
        except FileNotFoundError as err:
            raise web.HTTPNotFound(text=json.dumps({"error": "not_found", "path": str(err)}),
                                   content_type="application/json") from err
        except ValueError as err:
            raise web.HTTPUnprocessableEntity(text=json.dumps({"error": "unreadable", "detail": str(err)}),
                                              content_type="application/json") from err
        return web.json_response(result)

    async def rescan(request):
        service.rescan.set()
        return web.json_response({"ok": True})

    app = web.Application(middlewares=[auth])
    app.add_routes([web.get("/status", status), web.get("/similar", similar), web.post("/rescan", rescan)])
    _LOGGER.info("Listening on %s:%d", args.host, args.port)
    web.run_app(app, host=args.host, port=args.port, print=None)


# ---- cli -----------------------------------------------------------------------------------


def parse_maps(values: list[str] | None) -> list[tuple[str, str]]:
    maps = []
    for value in values or []:
        for item in value.split(";"):
            if "=" in item:
                src, dst = item.split("=", 1)
                maps.append((src.strip(), dst.strip()))
    return maps


def main() -> None:
    env = os.environ.get
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("serve", "index"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=env("ROOT", "/media/zdjecia"))
        p.add_argument("--db", default=env("DB", "/data/index.db"))
        p.add_argument("--map", action="append", default=[env("MAP")] if env("MAP") else [])
        p.add_argument("--device", default=env("DEVICE", "cpu"))
        p.add_argument("--threads", type=int, default=int(env("THREADS", "2")))
        p.add_argument("--batch", type=int, default=int(env("BATCH", "64" if name == "index" else "4")))
        p.add_argument("--workers", type=int, default=int(env("WORKERS", "12")))
    serve = sub.choices["serve"]
    serve.add_argument("--host", default=env("HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(env("PORT", "8765")))
    serve.add_argument("--token", default=env("TOKEN"))
    serve.add_argument("--scan-minutes", type=float, default=float(env("SCAN_MINUTES", "10")))
    serve.add_argument("--nice", type=int, default=int(env("NICE", "15")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        from pillow_heif import register_heif_opener  # noqa: PLC0415

        register_heif_opener()
    except ImportError:
        _LOGGER.warning("pillow-heif is missing; HEIC photos can't be read")
    {"serve": cmd_serve, "index": cmd_index}[args.cmd](args)


if __name__ == "__main__":
    main()
