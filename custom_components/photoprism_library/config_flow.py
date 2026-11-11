"""Config and options flow for PhotoPrism Library."""
from __future__ import annotations

import os
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
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
    DEFAULT_FOLDER,
    DEFAULT_RANDOM_COUNT,
    DEFAULT_SKIP_SCREENSHOTS,
    DOMAIN,
    PHOTOPRISM_APP_PASSWORD,
    PHOTOPRISM_INTEGRATION,
    PHOTOPRISM_INTEGRATION_DOMAIN,
    PHOTOPRISM_NONE,
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
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            mode = user_input.get(CONF_PHOTOPRISM, PHOTOPRISM_NONE)
            if user_input.get(CONF_ALLOW_DELETE) and mode == PHOTOPRISM_INTEGRATION:
                if not self.hass.config_entries.async_entries(PHOTOPRISM_INTEGRATION_DOMAIN):
                    errors[CONF_PHOTOPRISM] = "photoprism_integration_missing"
            if user_input.get(CONF_ALLOW_DELETE) and mode == PHOTOPRISM_APP_PASSWORD:
                if not user_input.get(CONF_PHOTOPRISM_URL) or not (
                    user_input.get(CONF_PHOTOPRISM_TOKEN) or current.get(CONF_PHOTOPRISM_TOKEN)
                ):
                    errors[CONF_PHOTOPRISM_TOKEN] = "photoprism_app_password_missing"
            if not errors:
                if not user_input.get(CONF_PHOTOPRISM_TOKEN) and current.get(CONF_PHOTOPRISM_TOKEN):
                    user_input[CONF_PHOTOPRISM_TOKEN] = current[CONF_PHOTOPRISM_TOKEN]  # keep the saved one
                if not user_input.get(CONF_SIMILARITY_TOKEN) and current.get(CONF_SIMILARITY_TOKEN):
                    user_input[CONF_SIMILARITY_TOKEN] = current[CONF_SIMILARITY_TOKEN]
                return self.async_create_entry(data=user_input)
            current = {**current, **user_input}
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
                    vol.Required(CONF_ALLOW_DELETE, default=bool(current.get(CONF_ALLOW_DELETE, False))): bool,
                    vol.Required(
                        CONF_PHOTOPRISM, default=current.get(CONF_PHOTOPRISM, PHOTOPRISM_NONE)
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[PHOTOPRISM_NONE, PHOTOPRISM_INTEGRATION, PHOTOPRISM_APP_PASSWORD],
                            translation_key=CONF_PHOTOPRISM,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Optional(
                        CONF_PHOTOPRISM_URL, description={"suggested_value": current.get(CONF_PHOTOPRISM_URL, "")}
                    ): str,
                    # Never pre-filled; leave empty to keep the saved app password.
                    vol.Optional(CONF_PHOTOPRISM_TOKEN): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(
                        CONF_SIMILARITY_URL, description={"suggested_value": current.get(CONF_SIMILARITY_URL, "")}
                    ): str,
                    vol.Optional(CONF_SIMILARITY_TOKEN): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(
                        CONF_SIMILAR_VIEW, description={"suggested_value": current.get(CONF_SIMILAR_VIEW, "")}
                    ): str,
                }
            ),
            errors=errors,
        )
