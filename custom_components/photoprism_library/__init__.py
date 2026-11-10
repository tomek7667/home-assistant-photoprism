"""PhotoPrism Library: browse your photo folder in Home Assistant, HEIC included."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_EXTRA_FOLDERS,
    CONF_FOLDER,
    CONF_RANDOM_COUNT,
    CONF_SKIP_SCREENSHOTS,
    DEFAULT_RANDOM_COUNT,
    DEFAULT_SKIP_SCREENSHOTS,
    DOMAIN,
)
from .library import PhotoLibrary
from .views import ImageView, ThumbView

_VIEWS_REGISTERED = f"{DOMAIN}_views"


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.async_add_import_executor_job(_register_heif_opener)
    options = {**entry.data, **entry.options}
    hass.data[DOMAIN] = PhotoLibrary(
        hass,
        folder=options[CONF_FOLDER],
        extra_folders=split_folders(options.get(CONF_EXTRA_FOLDERS)),
        random_count=int(options.get(CONF_RANDOM_COUNT, DEFAULT_RANDOM_COUNT)),
        skip_screenshots=bool(options.get(CONF_SKIP_SCREENSHOTS, DEFAULT_SKIP_SCREENSHOTS)),
    )
    if not hass.data.get(_VIEWS_REGISTERED):  # aiohttp routes can't be removed; register once
        hass.http.register_view(ImageView(hass))
        hass.http.register_view(ThumbView(hass))
        hass.data[_VIEWS_REGISTERED] = True
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.pop(DOMAIN, None)
    return True
