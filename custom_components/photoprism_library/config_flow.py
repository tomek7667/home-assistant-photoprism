"""Config and options flow for PhotoPrism Library."""
from __future__ import annotations

import os
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_EXTRA_FOLDERS,
    CONF_FOLDER,
    CONF_RANDOM_COUNT,
    CONF_SKIP_SCREENSHOTS,
    DEFAULT_FOLDER,
    DEFAULT_RANDOM_COUNT,
    DEFAULT_SKIP_SCREENSHOTS,
    DOMAIN,
)


def _check_folders(folder: str, extra: str) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not os.path.isabs(folder) or not os.path.isdir(folder):
        errors[CONF_FOLDER] = "folder_not_found"
    for path in [p.strip() for p in (extra or "").replace("\n", ",").split(",") if p.strip()]:
        if not os.path.isabs(path) or not os.path.isdir(path):
            errors[CONF_EXTRA_FOLDERS] = "folder_not_found"
    return errors


class PhotoPrismLibraryConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            folder = user_input[CONF_FOLDER].rstrip("/") or "/"
            extra = user_input.get(CONF_EXTRA_FOLDERS, "")
            errors = await self.hass.async_add_executor_job(_check_folders, folder, extra)
            if not errors:
                return self.async_create_entry(
                    title=os.path.basename(folder) or folder,
                    data={CONF_FOLDER: folder, CONF_EXTRA_FOLDERS: extra},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_FOLDER, default=DEFAULT_FOLDER): str,
                        vol.Optional(CONF_EXTRA_FOLDERS, default=""): str,
                    }
                ),
                user_input or {},
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PhotoPrismLibraryOptionsFlow()


class PhotoPrismLibraryOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_RANDOM_COUNT,
                        default=int(current.get(CONF_RANDOM_COUNT, DEFAULT_RANDOM_COUNT)),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=10, max=5000, step=10, mode=selector.NumberSelectorMode.BOX)
                    ),
                    vol.Required(
                        CONF_SKIP_SCREENSHOTS,
                        default=bool(current.get(CONF_SKIP_SCREENSHOTS, DEFAULT_SKIP_SCREENSHOTS)),
                    ): bool,
                }
            ),
        )
