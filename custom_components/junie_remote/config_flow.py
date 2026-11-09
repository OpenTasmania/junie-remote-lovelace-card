# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Config flow and options flow for JetBrains Junie Remote."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .client import JunieRemoteClient, parse_auth_cookies
from .const import (
    BASE_URL,
    CONF_LOCAL_STORAGE_PATH,
    CONF_S3_ACCESS_KEY,
    CONF_S3_BUCKET,
    CONF_S3_ENDPOINT,
    CONF_S3_PUBLIC_URL_BASE,
    CONF_S3_REGION,
    CONF_S3_SECRET_KEY,
    CONF_STORAGE_TYPE,
    DEFAULT_LOCAL_STORAGE_PATH,
    DEFAULT_STORAGE_TYPE,
    DOMAIN,
    STORAGE_TYPE_LOCAL,
    STORAGE_TYPE_S3,
)
from .ha_compat import (
    ConfigEntry,
    ConfigFlow,
    FlowResult,
    OptionsFlow,
    callback,
    vol,
)
from .models import JunieAuthError, JunieRemoteError
from .storage import is_public_path, known_public_roots

_LOGGER = logging.getLogger(__name__)


def _local_path_is_public(hass: Any, path: str) -> bool:
    """Return True when a local transcript path resolves inside a public web root."""
    config = getattr(hass, "config", None)
    if config is None or not hasattr(config, "path"):
        return False
    config_dir = Path(config.path())
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = config_dir / candidate
    return is_public_path(candidate, known_public_roots(config_dir))


class JunieRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for JetBrains Junie Remote."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self._config_data: dict[str, Any] = {}
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Step 1: Show authentication method menu."""
        abort = await self._async_abort_if_unique_id_configured()
        if abort is not None:
            return abort
        return self.async_show_menu(
            step_id="user",
            menu_options=["manual", "jba_oauth"],
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual cookie input step."""
        abort = await self._async_abort_if_unique_id_configured()
        if abort is not None:
            return abort

        errors: dict[str, str] = {}

        if user_input is not None:
            auth_input = str(user_input.get("auth_input", "")).strip()
            base_url = str(user_input.get("base_url", BASE_URL)).strip() or BASE_URL

            cookies, _ = parse_auth_cookies(auth_input)
            if not cookies:
                errors["base"] = "invalid_auth"
            else:
                client = JunieRemoteClient(auth_input=auth_input, base_url=base_url)
                try:
                    await client.list_tunnels()
                except JunieAuthError:
                    errors["base"] = "invalid_auth"
                except (JunieRemoteError, Exception) as err:
                    _LOGGER.warning("Connection test failed in config flow: %s", err)
                    errors["base"] = "cannot_connect"
                finally:
                    await client.close()

            if not errors:
                self._config_data = {
                    "auth_input": auth_input,
                    "base_url": base_url,
                }
                return await self.async_step_storage()

        data_schema = vol.Schema({
            vol.Required("auth_input"): str,
            vol.Optional("base_url", default=BASE_URL): str,
        })

        return self.async_show_form(
            step_id="manual",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_jba_oauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle JBA OAuth / assisted web flow step."""
        abort = await self._async_abort_if_unique_id_configured()
        if abort is not None:
            return abort

        errors: dict[str, str] = {}

        if user_input is not None:
            auth_input = str(user_input.get("auth_input", "")).strip()
            base_url = str(user_input.get("base_url", BASE_URL)).strip() or BASE_URL

            if not auth_input:
                errors["base"] = "invalid_auth"
            else:
                cookies, _ = parse_auth_cookies(auth_input)
                if not cookies:
                    errors["base"] = "invalid_auth"
                else:
                    client = JunieRemoteClient(auth_input=auth_input, base_url=base_url)
                    try:
                        await client.list_tunnels()
                    except JunieAuthError:
                        errors["base"] = "invalid_auth"
                    except (JunieRemoteError, Exception) as err:
                        _LOGGER.warning("Connection test failed in JBA flow: %s", err)
                        errors["base"] = "cannot_connect"
                    finally:
                        await client.close()

                    if not errors:
                        self._config_data = {
                            "auth_input": auth_input,
                            "base_url": base_url,
                        }
                        return await self.async_step_storage()

        data_schema = vol.Schema({
            vol.Required("auth_input"): str,
            vol.Optional("base_url", default=BASE_URL): str,
        })

        return self.async_show_form(
            step_id="jba_oauth",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "login_url": "https://account.jetbrains.com/login",
            },
        )

    async def _async_abort_if_unique_id_configured(self) -> FlowResult | None:
        """Abort if the integration is already configured."""
        if self.hass and hasattr(self.hass, "config_entries"):
            entries_dict = getattr(self.hass.config_entries, "entries", {})
            for entry in entries_dict.values():
                if entry.domain == DOMAIN:
                    return self.async_abort(reason="already_configured")
        return None

    async def async_step_storage(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Step 2: Storage configuration."""
        abort = await self._async_abort_if_unique_id_configured()
        if abort is not None:
            return abort

        errors: dict[str, str] = {}

        if user_input is not None:
            storage_type = user_input.get(CONF_STORAGE_TYPE, DEFAULT_STORAGE_TYPE)
            if storage_type == STORAGE_TYPE_S3:
                bucket = str(user_input.get(CONF_S3_BUCKET, "")).strip()
                if not bucket:
                    errors[CONF_S3_BUCKET] = "missing_s3_bucket"
                    errors["base"] = "missing_s3_bucket"

            if storage_type != STORAGE_TYPE_S3:
                local_path = str(
                    user_input.get(CONF_LOCAL_STORAGE_PATH) or DEFAULT_LOCAL_STORAGE_PATH
                )
                if await asyncio.to_thread(_local_path_is_public, self.hass, local_path):
                    errors[CONF_LOCAL_STORAGE_PATH] = "public_local_path"
                    errors["base"] = "public_local_path"

            if not errors:
                if hasattr(self, "async_set_unique_id"):
                    await self.async_set_unique_id(DOMAIN)
                final_data = {**self._config_data, **user_input}
                return self.async_create_entry(
                    title="JetBrains Junie Remote",
                    data=final_data,
                )

        data_schema = vol.Schema({
            vol.Required(
                CONF_STORAGE_TYPE, default=DEFAULT_STORAGE_TYPE
            ): vol.In([STORAGE_TYPE_LOCAL, STORAGE_TYPE_S3]),
            vol.Optional(
                CONF_LOCAL_STORAGE_PATH, default=DEFAULT_LOCAL_STORAGE_PATH
            ): str,
            vol.Optional(CONF_S3_ENDPOINT, default=""): str,
            vol.Optional(CONF_S3_BUCKET, default=""): str,
            vol.Optional(CONF_S3_REGION, default="us-east-1"): str,
            vol.Optional(CONF_S3_ACCESS_KEY, default=""): str,
            vol.Optional(CONF_S3_SECRET_KEY, default=""): str,
            vol.Optional(CONF_S3_PUBLIC_URL_BASE, default=""): str,
        })

        return self.async_show_form(
            step_id="storage",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle initiation of re-authentication flow."""
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle re-authentication confirmation."""
        errors: dict[str, str] = {}
        reauth_entry = self._reauth_entry or self._get_reauth_entry()

        if user_input is not None:
            auth_input = str(user_input.get("auth_input", "")).strip()
            base_url = (
                reauth_entry.data.get("base_url")
                if reauth_entry
                else BASE_URL
            ) or BASE_URL

            cookies, _ = parse_auth_cookies(auth_input)
            if not cookies:
                errors["base"] = "invalid_auth"
            else:
                client = JunieRemoteClient(auth_input=auth_input, base_url=base_url)
                try:
                    await client.list_tunnels()
                except JunieAuthError:
                    errors["base"] = "invalid_auth"
                except (JunieRemoteError, Exception) as err:
                    _LOGGER.warning("Reauth connection test failed: %s", err)
                    errors["base"] = "cannot_connect"
                finally:
                    await client.close()

            if not errors:
                if reauth_entry and self.hass:
                    self.hass.config_entries.async_update_entry(
                        reauth_entry,
                        data={**reauth_entry.data, "auth_input": auth_input},
                    )
                    await self.hass.config_entries.async_reload(reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Required("auth_input"): str,
            }),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return JunieRemoteOptionsFlow(config_entry)


class JunieRemoteOptionsFlow(OptionsFlow):
    """Handle options flow for JetBrains Junie Remote."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        current_auth = (
            self._entry.options.get("auth_input")
            or self._entry.data.get("auth_input")
            or ""
        )
        current_base_url = (
            self._entry.options.get("base_url")
            or self._entry.data.get("base_url")
            or BASE_URL
        )
        current_storage_type = (
            self._entry.options.get(CONF_STORAGE_TYPE)
            or self._entry.data.get(CONF_STORAGE_TYPE)
            or DEFAULT_STORAGE_TYPE
        )
        current_local_path = (
            self._entry.options.get(CONF_LOCAL_STORAGE_PATH)
            or self._entry.data.get(CONF_LOCAL_STORAGE_PATH)
            or DEFAULT_LOCAL_STORAGE_PATH
        )
        if await asyncio.to_thread(
            _local_path_is_public, getattr(self, "hass", None), str(current_local_path)
        ):
            current_local_path = DEFAULT_LOCAL_STORAGE_PATH
        current_s3_endpoint = (
            self._entry.options.get(CONF_S3_ENDPOINT)
            or self._entry.data.get(CONF_S3_ENDPOINT)
            or ""
        )
        current_s3_bucket = (
            self._entry.options.get(CONF_S3_BUCKET)
            or self._entry.data.get(CONF_S3_BUCKET)
            or ""
        )
        current_s3_region = (
            self._entry.options.get(CONF_S3_REGION)
            or self._entry.data.get(CONF_S3_REGION)
            or "us-east-1"
        )
        current_s3_access = (
            self._entry.options.get(CONF_S3_ACCESS_KEY)
            or self._entry.data.get(CONF_S3_ACCESS_KEY)
            or ""
        )
        current_s3_secret = (
            self._entry.options.get(CONF_S3_SECRET_KEY)
            or self._entry.data.get(CONF_S3_SECRET_KEY)
            or ""
        )
        current_s3_public = (
            self._entry.options.get(CONF_S3_PUBLIC_URL_BASE)
            or self._entry.data.get(CONF_S3_PUBLIC_URL_BASE)
            or ""
        )

        if user_input is not None:
            new_auth = str(user_input.get("auth_input", "")).strip()
            if new_auth and new_auth != current_auth:
                cookies, _ = parse_auth_cookies(new_auth)
                if not cookies:
                    errors["base"] = "invalid_auth"
                else:
                    client = JunieRemoteClient(
                        auth_input=new_auth, base_url=current_base_url
                    )
                    try:
                        await client.list_tunnels()
                    except JunieAuthError:
                        errors["base"] = "invalid_auth"
                    except (JunieRemoteError, Exception):
                        errors["base"] = "cannot_connect"
                    finally:
                        await client.close()

            storage_type = user_input.get(CONF_STORAGE_TYPE, current_storage_type)
            if storage_type == STORAGE_TYPE_S3:
                bucket = str(user_input.get(CONF_S3_BUCKET, "")).strip()
                if not bucket:
                    errors[CONF_S3_BUCKET] = "missing_s3_bucket"
                    errors["base"] = "missing_s3_bucket"
            else:
                local_path = str(
                    user_input.get(CONF_LOCAL_STORAGE_PATH) or DEFAULT_LOCAL_STORAGE_PATH
                )
                if await asyncio.to_thread(
                    _local_path_is_public, self.hass, local_path
                ):
                    errors[CONF_LOCAL_STORAGE_PATH] = "public_local_path"
                    errors["base"] = "public_local_path"

            if not errors:
                return self.async_create_entry(title="", data=user_input)

        data_schema = vol.Schema({
            vol.Optional("auth_input", default=current_auth): str,
            vol.Required(
                CONF_STORAGE_TYPE, default=current_storage_type
            ): vol.In([STORAGE_TYPE_LOCAL, STORAGE_TYPE_S3]),
            vol.Optional(
                CONF_LOCAL_STORAGE_PATH, default=current_local_path
            ): str,
            vol.Optional(CONF_S3_ENDPOINT, default=current_s3_endpoint): str,
            vol.Optional(CONF_S3_BUCKET, default=current_s3_bucket): str,
            vol.Optional(CONF_S3_REGION, default=current_s3_region): str,
            vol.Optional(CONF_S3_ACCESS_KEY, default=current_s3_access): str,
            vol.Optional(CONF_S3_SECRET_KEY, default=current_s3_secret): str,
            vol.Optional(
                CONF_S3_PUBLIC_URL_BASE, default=current_s3_public
            ): str,
        })

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors,
        )
