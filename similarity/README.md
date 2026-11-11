# Similar-photo service

Gives every photo and video (one frame) of a PhotoPrism Library folder an image embedding
([SigLIP 2](https://huggingface.co/timm/ViT-B-16-SigLIP2) ViT-B/16) and finds similar photos
by cosine similarity. The `photoprism_library` integration asks it when you press 🔍.

- `GET /similar?path=<library path>&min=0.8&limit=300`: similar photos, most similar first
- `GET /status`: how much of the library is indexed
- `POST /rescan`: look for new photos now

The index is a SQLite file (`DB`, default `/data/index.db`). Settings are environment variables:
`ROOT` (library folder, same path as in Home Assistant), `THREADS` (CPU threads, default 2),
`SCAN_MINUTES` (default 10), `NICE` (indexing priority, default 15), `HOST`/`PORT`
(default `127.0.0.1:8765`), `TOKEN` (optional bearer token), `MAP` (`/from=/to` rewrites of absolute
symlink targets, `;`-separated) and `DEVICE` (`cpu` or `cuda`).

See the main README for setup.
