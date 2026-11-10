"""Keep Album Slideshow albums that use this media source in sync."""
from __future__ import annotations

from urllib.parse import unquote

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_SLIDESHOW = "album_slideshow"
_SOURCE_PREFIX = f"media-source://{DOMAIN}"


async def async_refresh(hass: HomeAssistant, gone: set[str] | None = None) -> None:
    """Reload slideshow albums built on this media source.

    Album Slideshow stores signed image URLs, and Home Assistant signs URLs with a
    secret that changes on every restart, so the album is reloaded after start.
    With ``gone`` (deleted library paths), cameras showing one of them skip ahead first.
    """
    if not hass.services.has_service(_SLIDESHOW, "refresh_album"):
        return
    gone = {g.lower() for g in gone or ()}
    ent_reg = er.async_get(hass)
    for entry in hass.config_entries.async_loaded_entries(_SLIDESHOW):
        if not str(entry.data.get("media_content_id", "")).startswith(_SOURCE_PREFIX):
            continue
        if gone:
            for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
                if ent.domain != "camera" or (state := hass.states.get(ent.entity_id)) is None:
                    continue
                url = unquote(str(state.attributes.get("current_url", ""))).lower()
                if any(name in url for name in gone):
                    await hass.services.async_call(_SLIDESHOW, "next_slide", {"entry_id": entry.entry_id})
        await hass.services.async_call(_SLIDESHOW, "refresh_album", {"entry_id": entry.entry_id})
