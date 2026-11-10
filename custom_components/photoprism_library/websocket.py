"""WebSocket API: delete a photo everywhere (admins only, when enabled in the options)."""
from __future__ import annotations

import logging
import os
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from . import slideshow
from .const import DOMAIN, EVENT_DELETED
from .library import DeletePlan, PhotoLibrary
from .photoprism import PhotoPrismError

_LOGGER = logging.getLogger(__name__)


def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_config)
    websocket_api.async_register_command(hass, ws_delete_plan)
    websocket_api.async_register_command(hass, ws_delete)


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
            "allow_delete": bool(lib and lib.allow_delete and connection.user.is_admin),
            "photoprism": bool(lib and lib.photoprism),
        },
    )


@websocket_api.require_admin
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


@websocket_api.require_admin
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
