"""PhotoPrism Library: browse your photo folder in Home Assistant, HEIC included."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.start import async_at_started

from . import slideshow, websocket
from .const import (
    CONF_ALBUM_VIEW,
    CONF_ALLOW_DELETE,
    CONF_EXTRA_FOLDERS,
    CONF_FOLDER,
    CONF_PHOTOPRISM,
    CONF_PHOTOPRISM_TOKEN,
    CONF_PHOTOPRISM_URL,
    CONF_RANDOM_COUNT,
    CONF_SIMILAR_VIEW,
    CONF_SIMILARITY_TOKEN,
    CONF_SIMILARITY_URL,
    CONF_SKIP_SCREENSHOTS,
    DEFAULT_RANDOM_COUNT,
    DEFAULT_SKIP_SCREENSHOTS,
    DOMAIN,
    PHOTOPRISM_APP_PASSWORD,
    PHOTOPRISM_INTEGRATION,
    PHOTOPRISM_INTEGRATION_DOMAIN,
    PHOTOPRISM_NONE,
)
from .favorites import async_get_favorites
from .library import PhotoLibrary
from .photoprism import PhotoPrismClient
from .similarity import SimilarityClient
from .views import ImageView, ThumbView

_LOGGER = logging.getLogger(__name__)
_REGISTERED = f"{DOMAIN}_registered"
PLATFORMS = [Platform.SENSOR]
STATIC_URL = "/photoprism_library_static"
VERSION = "1.5.0"


def _register_heif_opener() -> None:
    import pillow_heif  # noqa: PLC0415 - heavy import, done in the executor

    # Lets Pillow open HEIC/HEIF anywhere in Home Assistant.
    pillow_heif.register_heif_opener()
    # media_source imports this platform lazily inside the event loop; load it here
    # so that later import is a cache hit and doesn't block.
    from . import media_source  # noqa: F401, PLC0415


def split_folders(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [v.strip() for v in value if v.strip()]
    return [v.strip() for v in value.replace("\n", ",").split(",") if v.strip()]


def _photoprism_client(hass: HomeAssistant, options: dict) -> PhotoPrismClient | None:
    mode = options.get(CONF_PHOTOPRISM, PHOTOPRISM_NONE)
    if mode == PHOTOPRISM_APP_PASSWORD and options.get(CONF_PHOTOPRISM_URL) and options.get(CONF_PHOTOPRISM_TOKEN):
        return PhotoPrismClient(hass, options[CONF_PHOTOPRISM_URL], token=options[CONF_PHOTOPRISM_TOKEN])
    if mode == PHOTOPRISM_INTEGRATION:
        for entry in hass.config_entries.async_entries(PHOTOPRISM_INTEGRATION_DOMAIN):
            data = entry.data
            if data.get("url"):
                return PhotoPrismClient(
                    hass,
                    data["url"],
                    token=data.get("token") or data.get("api_key"),
                    username=data.get("username"),
                    password=data.get("password"),
                    verify_ssl=data.get("verify_ssl", True),
                )
        _LOGGER.warning("PhotoPrism integration not found; deleting will only remove files")
    return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.async_add_import_executor_job(_register_heif_opener)
    options = {**entry.data, **entry.options}
    lib = PhotoLibrary(
        hass,
        folder=options[CONF_FOLDER],
        extra_folders=split_folders(options.get(CONF_EXTRA_FOLDERS)),
        random_count=int(options.get(CONF_RANDOM_COUNT, DEFAULT_RANDOM_COUNT)),
        skip_screenshots=bool(options.get(CONF_SKIP_SCREENSHOTS, DEFAULT_SKIP_SCREENSHOTS)),
    )
    lib.allow_delete = bool(options.get(CONF_ALLOW_DELETE, False))
    lib.photoprism = _photoprism_client(hass, options) if lib.allow_delete else None
    url = (options.get(CONF_SIMILARITY_URL) or "").strip()
    lib.similarity = SimilarityClient(hass, url, options.get(CONF_SIMILARITY_TOKEN)) if url else None
    lib.similar_view = (options.get(CONF_SIMILAR_VIEW) or "").strip()
    lib.album_view = (options.get(CONF_ALBUM_VIEW) or "").strip()
    hass.data[DOMAIN] = lib
    await async_get_favorites(hass)

    if not hass.data.get(_REGISTERED):  # routes and commands can't be removed; register once
        hass.http.register_view(ImageView(hass))
        hass.http.register_view(ThumbView(hass))
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "www"), False)]
        )
        # Adds the delete button to photo previews and the slideshow card. The file's
        # mtime in the URL makes browsers fetch a changed script instead of a cached one.
        script = Path(__file__).parent / "www" / "photoprism-library.js"
        mtime = await hass.async_add_executor_job(lambda: int(script.stat().st_mtime))
        add_extra_js_url(hass, f"{STATIC_URL}/{script.name}?v={VERSION}-{mtime}")
        websocket.async_register(hass)
        hass.data[_REGISTERED] = True

    entry.async_on_unload(entry.add_update_listener(_async_reload))

    # Slideshow albums hold URLs signed before the restart, which are invalid now.
    async def _refresh_slideshows(_hass: HomeAssistant) -> None:
        await slideshow.async_refresh(hass)

    entry.async_on_unload(async_at_started(hass, _refresh_slideshows))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data.pop(DOMAIN, None)
    return True
