"""PhotoPrism Library: browse your photo folder in Home Assistant, HEIC included."""
from __future__ import annotations

from datetime import timedelta
import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_time_interval
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
    ISSUE_APP_PASSWORD_NEEDED,
    PHOTOPRISM_APP_PASSWORD,
    PHOTOPRISM_NONE,
    PHOTOPRISM_REMOVED_INTEGRATION,
)
from .favorites import async_get_favorites
from .library import PhotoLibrary
from .photoprism import PhotoPrismClient
from .similarity import SimilarityClient
from .video import VideoCache
from .views import ImageView, ThumbView, VideoView

_LOGGER = logging.getLogger(__name__)
_REGISTERED = f"{DOMAIN}_registered"
PLATFORMS = [Platform.SENSOR]
STATIC_URL = "/photoprism_library_static"
VERSION = "1.6.0"
# Videos browsers can't play get H.264 copies in the background: first run a while after start, then every 6 hours
VIDEO_FIRST_RUN = 300
VIDEO_INTERVAL = timedelta(hours=6)


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
    if (
        options.get(CONF_PHOTOPRISM, PHOTOPRISM_NONE) == PHOTOPRISM_APP_PASSWORD
        and options.get(CONF_PHOTOPRISM_URL)
        and options.get(CONF_PHOTOPRISM_TOKEN)
    ):
        return PhotoPrismClient(hass, options[CONF_PHOTOPRISM_URL], options[CONF_PHOTOPRISM_TOKEN])
    return None


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """1.2: the option that reused the PhotoPrism integration's login is gone; such entries delete files only."""
    if entry.version > 1:
        return False  # made by a newer version
    if entry.minor_version < 2:
        data, options = dict(entry.data), dict(entry.options)
        moved = False
        for values in (data, options):
            if values.get(CONF_PHOTOPRISM) == PHOTOPRISM_REMOVED_INTEGRATION:
                values[CONF_PHOTOPRISM] = PHOTOPRISM_NONE
                moved = True
        hass.config_entries.async_update_entry(entry, data=data, options=options, minor_version=2)
        if moved and {**data, **options}.get(CONF_ALLOW_DELETE):
            # Stays until the user picks an app password, turns deleting off or ignores it in Repairs.
            ir.async_create_issue(
                hass,
                DOMAIN,
                ISSUE_APP_PASSWORD_NEEDED,
                is_fixable=False,
                is_persistent=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_APP_PASSWORD_NEEDED,
                learn_more_url="https://github.com/tomek7667/home-assistant-photoprism#deleting-photos",
            )
    return True


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
    if lib.photoprism is not None or not lib.allow_delete:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_APP_PASSWORD_NEEDED)
    url = (options.get(CONF_SIMILARITY_URL) or "").strip()
    lib.similarity = SimilarityClient(hass, url, options.get(CONF_SIMILARITY_TOKEN)) if url else None
    lib.similar_view = (options.get(CONF_SIMILAR_VIEW) or "").strip()
    lib.album_view = (options.get(CONF_ALBUM_VIEW) or "").strip()
    lib.videos = VideoCache(hass, lib)
    hass.data[DOMAIN] = lib
    await async_get_favorites(hass)

    if not hass.data.get(_REGISTERED):  # routes and commands can't be removed; register once
        hass.http.register_view(ImageView(hass))
        hass.http.register_view(ThumbView(hass))
        hass.http.register_view(VideoView(hass))
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

    # H.264 copies of videos that browsers without HEVC can't play
    async def _convert_videos(_now=None) -> None:
        entry.async_create_background_task(hass, lib.videos.async_convert_all(), f"{DOMAIN} video copies")

    entry.async_on_unload(async_call_later(hass, VIDEO_FIRST_RUN, _convert_videos))
    entry.async_on_unload(async_track_time_interval(hass, _convert_videos, VIDEO_INTERVAL))
    entry.async_on_unload(lib.videos.stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    ir.async_delete_issue(hass, DOMAIN, ISSUE_APP_PASSWORD_NEEDED)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data.pop(DOMAIN, None)
    return True
