"""HTTP views: full-size images (HEIC converted to JPEG) and thumbnails."""
from __future__ import annotations

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PHOTO_EXTS
from .library import PhotoLibrary, ext_of

_CACHE_HEADERS = {"Cache-Control": "private, max-age=86400"}


class _PhotoView(HomeAssistantView):
    # Logged-in users only; signed URLs from the media source (authSig) work as well.
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def _resolve(self, path: str) -> tuple[PhotoLibrary, str]:
        lib: PhotoLibrary | None = self.hass.data.get(DOMAIN)
        if lib is None:
            raise web.HTTPServiceUnavailable
        real = await self.hass.async_add_executor_job(lib.safe_path, path)
        if real is None:
            raise web.HTTPNotFound
        return lib, real


class ImageView(_PhotoView):
    url = "/api/photoprism_library/image/{path:.+}"
    name = "api:photoprism_library:image"

    async def get(self, request: web.Request, path: str) -> web.StreamResponse:
        lib, real = await self._resolve(path)
        if lib.needs_conversion(path):
            try:
                data = await lib.async_jpeg(real, thumb=False)
            except Exception as err:  # noqa: BLE001 - corrupt or unsupported file
                raise web.HTTPUnsupportedMediaType(text=str(err)) from err
            return web.Response(body=data, content_type="image/jpeg", headers=_CACHE_HEADERS)
        return web.FileResponse(real, headers=_CACHE_HEADERS)


class ThumbView(_PhotoView):
    url = "/api/photoprism_library/thumb/{path:.+}"
    name = "api:photoprism_library:thumb"

    async def get(self, request: web.Request, path: str) -> web.StreamResponse:
        lib, real = await self._resolve(path)
        if ext_of(path) not in PHOTO_EXTS:
            raise web.HTTPNotFound
        try:
            data = await lib.async_jpeg(real, thumb=True)
        except Exception as err:  # noqa: BLE001
            raise web.HTTPUnsupportedMediaType(text=str(err)) from err
        return web.Response(body=data, content_type="image/jpeg", headers=_CACHE_HEADERS)
