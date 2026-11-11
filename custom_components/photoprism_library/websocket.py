"""WebSocket API: favourites, signed thumbnail URLs, and deleting a photo everywhere.

Every logged-in user may use all of it; deleting also has to be enabled in the options.
"""
from __future__ import annotations

from datetime import timedelta
import logging
import os
from typing import Any
from urllib.parse import quote

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant, callback

from . import slideshow
from .const import DOMAIN, EVENT_DELETED, IMAGE_URL, THUMB_URL
from .favorites import async_get_favorites
from .library import DeletePlan, PhotoLibrary
from .photoprism import PhotoPrismError
from .similarity import SimilarityError

# Signed URLs handed to the cards; they are re-signed before this runs out
_SIGN_FOR = timedelta(hours=6)
_MAX_PATHS = 2000

_LOGGER = logging.getLogger(__name__)


def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_config)
    websocket_api.async_register_command(hass, ws_delete_plan)
    websocket_api.async_register_command(hass, ws_delete)
    websocket_api.async_register_command(hass, ws_favorites_subscribe)
    websocket_api.async_register_command(hass, ws_favorites_set)
    websocket_api.async_register_command(hass, ws_sign)
    websocket_api.async_register_command(hass, ws_similar)


def _library(hass: HomeAssistant, connection, msg) -> PhotoLibrary | None:
    lib: PhotoLibrary | None = hass.data.get(DOMAIN)
    if lib is None or not lib.allow_delete:
        connection.send_error(msg["id"], "not_allowed", "Deleting photos is turned off in the PhotoPrism Library options")
        return None
    return lib


async def _plan(hass: HomeAssistant, lib: PhotoLibrary, connection, msg) -> DeletePlan | None:
    try:
        return await hass.async_add_executor_job(lib.plan_delete, msg["path"])
    except (FileNotFoundError, NotADirectoryError):
        connection.send_error(msg["id"], "not_found", f"Photo not found: {msg['path']}")
        return None


@websocket_api.websocket_command({vol.Required("type"): "photoprism_library/config"})
@websocket_api.async_response
async def ws_config(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    lib: PhotoLibrary | None = hass.data.get(DOMAIN)
    connection.send_result(
        msg["id"],
        {
            "allow_delete": bool(lib and lib.allow_delete),
            "photoprism": bool(lib and lib.photoprism),
            "similar": bool(lib and lib.similarity),
            "similar_view": (lib.similar_view if lib and lib.similarity else ""),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): "photoprism_library/delete_plan", vol.Required("path"): str})
@websocket_api.async_response
async def ws_delete_plan(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    if (lib := _library(hass, connection, msg)) is None or (plan := await _plan(hass, lib, connection, msg)) is None:
        return
    connection.send_result(
        msg["id"],
        {"files": sorted({os.path.basename(n) for n in plan.library_names} | {os.path.basename(f) for f in plan.files}),
         "photoprism": lib.photoprism is not None},
    )


@websocket_api.websocket_command({vol.Required("type"): "photoprism_library/delete", vol.Required("path"): str})
@websocket_api.async_response
async def ws_delete(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    if (lib := _library(hass, connection, msg)) is None or (plan := await _plan(hass, lib, connection, msg)) is None:
        return
    uids: set[str] = set()
    if lib.photoprism is not None:
        # PhotoPrism first: if it fails, nothing is touched on disk.
        try:
            uids = await lib.photoprism.async_find_uids(plan.library_names)
            await lib.photoprism.async_delete(uids)
        except PhotoPrismError as err:
            connection.send_error(msg["id"], "photoprism_failed", str(err))
            return
    try:
        removed = await hass.async_add_executor_job(lib.execute_delete, plan)
    except OSError as err:
        connection.send_error(msg["id"], "delete_failed", str(err))
        return
    lib.forget(plan)
    (await async_get_favorites(hass)).async_forget([plan.rel, *plan.library_names])
    _LOGGER.warning(
        "Deleted photo %s by %s: files %s, PhotoPrism %s",
        plan.rel, connection.user.name, sorted({os.path.basename(f) for f in removed}) or "-", sorted(uids) or "-",
    )
    hass.bus.async_fire(EVENT_DELETED, {"path": plan.rel, "files": removed, "photoprism_uids": sorted(uids)})
    connection.send_result(
        msg["id"], {"removed": sorted({os.path.basename(f) for f in removed}), "photoprism": sorted(uids)}
    )
    # Move slideshows off the deleted photo and reload their lists (in the background).
    hass.async_create_task(slideshow.async_refresh(hass, set(plan.library_names)))


@websocket_api.websocket_command({vol.Required("type"): "photoprism_library/favorites/subscribe"})
@websocket_api.async_response
async def ws_favorites_subscribe(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Send the favourites now and after every change (most recently added first)."""
    favorites = await async_get_favorites(hass)

    @callback
    def push() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"items": favorites.items()}))

    connection.subscriptions[msg["id"]] = favorites.async_subscribe(push)
    connection.send_result(msg["id"])
    push()


@websocket_api.websocket_command(
    {
        vol.Required("type"): "photoprism_library/favorites/set",
        vol.Required("paths"): vol.All([str], vol.Length(min=1, max=_MAX_PATHS)),
        vol.Required("favorite"): bool,
    }
)
@websocket_api.async_response
async def ws_favorites_set(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    lib: PhotoLibrary | None = hass.data.get(DOMAIN)
    paths = [p.strip("/") for p in msg["paths"]]
    if msg["favorite"]:
        if lib is None:
            connection.send_error(msg["id"], "not_ready", "PhotoPrism Library is not set up")
            return
        # Only files that exist in the library can be added
        exists = await hass.async_add_executor_job(lambda: [p for p in paths if lib.safe_path(p)])
        if missing := sorted(set(paths) - set(exists)):
            connection.send_error(msg["id"], "not_found", f"Not in the library: {', '.join(missing[:5])}")
            return
    changed = (await async_get_favorites(hass)).async_set(paths, msg["favorite"])
    connection.send_result(msg["id"], {"changed": changed})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "photoprism_library/sign",
        vol.Required("paths"): vol.All([str], vol.Length(max=_MAX_PATHS)),
        vol.Optional("full", default=False): bool,
    }
)
@callback
def ws_sign(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Signed thumbnail (or full-size) URLs for many photos in one call."""
    base = IMAGE_URL if msg["full"] else THUMB_URL
    urls = {
        path: async_sign_path(
            hass, f"{base}{quote(path.strip('/'))}", _SIGN_FOR, refresh_token_id=connection.refresh_token_id
        )
        for path in msg["paths"]
    }
    connection.send_result(msg["id"], {"urls": urls, "expires_in": int(_SIGN_FOR.total_seconds())})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "photoprism_library/similar",
        vol.Required("path"): str,
        vol.Optional("min", default=0.8): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
        vol.Optional("limit", default=300): vol.All(int, vol.Range(min=1, max=2000)),
    }
)
@websocket_api.async_response
async def ws_similar(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Photos that look like this one, most similar first, with their similarity (0-1)."""
    lib: PhotoLibrary | None = hass.data.get(DOMAIN)
    if lib is None or lib.similarity is None:
        connection.send_error(msg["id"], "not_configured", "The similar-photo service is not set up in the options")
        return
    try:
        data = await lib.similarity.async_similar(lib, msg["path"].strip("/"), msg["min"], msg["limit"])
    except SimilarityError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    connection.send_result(msg["id"], {"results": data["results"], "total": data.get("total", len(data["results"]))})
