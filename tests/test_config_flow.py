# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Unit tests for JetBrains Junie Remote config flow and options flow."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.junie_remote.config_flow import (
    JunieRemoteConfigFlow,
    JunieRemoteOptionsFlow,
)
from custom_components.junie_remote.const import (
    CONF_LOCAL_STORAGE_PATH,
    CONF_S3_ACCESS_KEY,
    CONF_S3_BUCKET,
    CONF_S3_ENDPOINT,
    CONF_S3_PUBLIC_URL_BASE,
    CONF_S3_REGION,
    CONF_S3_SECRET_KEY,
    CONF_STORAGE_TYPE,
    DEFAULT_LOCAL_STORAGE_PATH,
    DOMAIN,
    STORAGE_TYPE_LOCAL,
    STORAGE_TYPE_S3,
)
from custom_components.junie_remote.ha_compat import MockConfigEntry, MockHomeAssistant
from custom_components.junie_remote.models import JunieAuthError, JunieRemoteError

# Alias for backward compatibility
ConfigEntry = MockConfigEntry

VALID_STORAGE_STATE = json.dumps({
    "cookies": [
        {"name": "SESSION", "value": "valid_sess_123", "domain": "junie.jetbrains.com"},
        {"name": "XSRF-TOKEN", "value": "valid_xsrf_token", "domain": "junie.jetbrains.com"},
    ]
})

VALID_COOKIE_HEADER = "SESSION=sess_raw_789; XSRF-TOKEN=raw_xsrf_456"


@pytest.fixture
def hass() -> MockHomeAssistant:
    """Fixture providing a mock HomeAssistant core instance."""
    return MockHomeAssistant()


# --- Config Flow Step 1 (User) Menu Tests ---


async def test_step_user_shows_menu(hass: MockHomeAssistant) -> None:
    """Verify initial user step shows authentication method menu."""
    flow = JunieRemoteConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user(user_input=None)
    assert result["type"] == "menu"
    assert result["step_id"] == "user"
    assert "manual" in result["menu_options"]
    assert "jba_oauth" in result["menu_options"]


async def test_step_user_aborts_if_already_configured(hass: MockHomeAssistant) -> None:
    """Verify user step aborts if integration is already configured."""
    entry = ConfigEntry(
        entry_id="existing_entry",
        domain=DOMAIN,
        title="JetBrains Junie Remote",
        data={"auth_input": VALID_COOKIE_HEADER},
    )
    hass.config_entries.entries[entry.entry_id] = entry

    flow = JunieRemoteConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user(user_input=None)
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


async def test_translations_match_strings(hass: MockHomeAssistant) -> None:
    """Verify that translations/en.json matches strings.json."""
    import json
    from pathlib import Path

    base_path = Path(__file__).parent.parent / "custom_components" / "junie_remote"
    strings_path = base_path / "strings.json"
    translations_path = base_path / "translations" / "en.json"

    assert translations_path.exists(), "translations/en.json must exist"

    with open(strings_path, "r") as f:
        strings = json.load(f)
    with open(translations_path, "r") as f:
        translations = json.load(f)

    assert strings == translations, "strings.json and translations/en.json must match"


# --- Config Flow Manual Step Tests ---


async def test_step_manual_shows_form(hass: MockHomeAssistant) -> None:
    """Verify manual step shows cookie input form."""
    flow = JunieRemoteConfigFlow()
    flow.hass = hass

    result = await flow.async_step_manual(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "manual"
    assert result["errors"] == {}
    assert "auth_input" in result["data_schema"].schema
    assert "base_url" in result["data_schema"].schema


async def test_step_manual_empty_cookies_error(hass: MockHomeAssistant) -> None:
    """Verify validation error when auth_input provides no valid cookies."""
    flow = JunieRemoteConfigFlow()
    flow.hass = hass

    result = await flow.async_step_manual(user_input={"auth_input": "invalid-no-cookie-pairs"})
    assert result["type"] == "form"
    assert result["step_id"] == "manual"
    assert result["errors"]["base"] == "invalid_auth"


async def test_step_manual_auth_error(hass: MockHomeAssistant) -> None:
    """Verify JunieAuthError leads to invalid_auth error."""
    flow = JunieRemoteConfigFlow()
    flow.hass = hass

    with patch(
        "custom_components.junie_remote.config_flow.JunieRemoteClient.list_tunnels",
        side_effect=JunieAuthError("HTTP 401 Unauthorized"),
    ):
        result = await flow.async_step_manual(user_input={"auth_input": VALID_STORAGE_STATE})
        assert result["type"] == "form"
        assert result["step_id"] == "manual"
        assert result["errors"]["base"] == "invalid_auth"


async def test_step_manual_cannot_connect_error(hass: MockHomeAssistant) -> None:
    """Verify JunieRemoteError or connection failure leads to cannot_connect error."""
    flow = JunieRemoteConfigFlow()
    flow.hass = hass

    with patch(
        "custom_components.junie_remote.config_flow.JunieRemoteClient.list_tunnels",
        side_effect=JunieRemoteError("Network unreachable"),
    ):
        result = await flow.async_step_manual(user_input={"auth_input": VALID_COOKIE_HEADER})
        assert result["type"] == "form"
        assert result["step_id"] == "manual"
        assert result["errors"]["base"] == "cannot_connect"


async def test_step_manual_success_proceeds_to_storage(hass: MockHomeAssistant) -> None:
    """Verify valid credentials transition directly to Step 2 (storage)."""
    flow = JunieRemoteConfigFlow()
    flow.hass = hass

    with patch(
        "custom_components.junie_remote.config_flow.JunieRemoteClient.list_tunnels",
        new=AsyncMock(return_value=[]),
    ):
        result = await flow.async_step_manual(
            user_input={
                "auth_input": VALID_STORAGE_STATE,
                "base_url": "https://junie.jetbrains.com",
            }
        )
        assert result["type"] == "form"
        assert result["step_id"] == "storage"
        assert flow._config_data["auth_input"] == VALID_STORAGE_STATE


# --- Config Flow JBA OAuth Step Tests ---


async def test_step_jba_oauth_shows_form(hass: MockHomeAssistant) -> None:
    """Verify JBA OAuth step shows form with login instructions."""
    flow = JunieRemoteConfigFlow()
    flow.hass = hass

    result = await flow.async_step_jba_oauth(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "jba_oauth"
    assert result["description_placeholders"]["login_url"] == "https://account.jetbrains.com/login"
    assert "auth_input" in result["data_schema"].schema


async def test_step_jba_oauth_empty_cookies_error(hass: MockHomeAssistant) -> None:
    """Verify validation error when auth_input provides no valid cookies in JBA flow."""
    flow = JunieRemoteConfigFlow()
    flow.hass = hass

    result = await flow.async_step_jba_oauth(user_input={"auth_input": "invalid-no-cookie-pairs"})
    assert result["type"] == "form"
    assert result["step_id"] == "jba_oauth"
    assert result["errors"]["base"] == "invalid_auth"


async def test_step_jba_oauth_cannot_connect_error(hass: MockHomeAssistant) -> None:
    """Verify connection error in JBA flow."""
    flow = JunieRemoteConfigFlow()
    flow.hass = hass

    with patch(
        "custom_components.junie_remote.config_flow.JunieRemoteClient.list_tunnels",
        side_effect=JunieRemoteError("Network unreachable"),
    ):
        result = await flow.async_step_jba_oauth(user_input={"auth_input": VALID_COOKIE_HEADER})
        assert result["type"] == "form"
        assert result["step_id"] == "jba_oauth"
        assert result["errors"]["base"] == "cannot_connect"


async def test_step_jba_oauth_success_proceeds_to_storage(hass: MockHomeAssistant) -> None:
    """Verify valid credentials in JBA flow transition directly to Step 2 (storage)."""
    flow = JunieRemoteConfigFlow()
    flow.hass = hass

    with patch(
        "custom_components.junie_remote.config_flow.JunieRemoteClient.list_tunnels",
        new=AsyncMock(return_value=[]),
    ):
        result = await flow.async_step_jba_oauth(
            user_input={
                "auth_input": VALID_STORAGE_STATE,
                "base_url": "https://junie.jetbrains.com",
            }
        )
        assert result["type"] == "form"
        assert result["step_id"] == "storage"
        assert flow._config_data["auth_input"] == VALID_STORAGE_STATE


async def test_step_manual_and_jba_abort_if_already_configured(hass: MockHomeAssistant) -> None:
    """Verify manual and JBA steps abort if integration is already configured."""
    entry = ConfigEntry(
        entry_id="existing_entry",
        domain=DOMAIN,
        title="JetBrains Junie Remote",
        data={"auth_input": VALID_COOKIE_HEADER},
    )
    hass.config_entries.entries[entry.entry_id] = entry

    flow = JunieRemoteConfigFlow()
    flow.hass = hass

    result_manual = await flow.async_step_manual(user_input=None)
    assert result_manual["type"] == "abort"
    assert result_manual["reason"] == "already_configured"

    result_jba = await flow.async_step_jba_oauth(user_input=None)
    assert result_jba["type"] == "abort"
    assert result_jba["reason"] == "already_configured"


# --- Config Flow Step 2 (Storage) Tests ---


async def test_step_storage_local_success(hass: MockHomeAssistant) -> None:
    """Verify full config flow completion with Local storage."""
    flow = JunieRemoteConfigFlow()
    flow.hass = hass
    flow._config_data = {
        "auth_input": VALID_STORAGE_STATE,
        "base_url": "https://junie.jetbrains.com",
    }

    result = await flow.async_step_storage(
        user_input={
            CONF_STORAGE_TYPE: STORAGE_TYPE_LOCAL,
            CONF_LOCAL_STORAGE_PATH: DEFAULT_LOCAL_STORAGE_PATH,
        }
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "JetBrains Junie Remote"
    assert result["data"]["auth_input"] == VALID_STORAGE_STATE
    assert result["data"][CONF_STORAGE_TYPE] == STORAGE_TYPE_LOCAL
    assert result["data"][CONF_LOCAL_STORAGE_PATH] == DEFAULT_LOCAL_STORAGE_PATH


async def test_step_storage_s3_missing_bucket_error(hass: MockHomeAssistant) -> None:
    """Verify validation error when S3 storage is selected but bucket is omitted."""
    flow = JunieRemoteConfigFlow()
    flow.hass = hass
    flow._config_data = {"auth_input": VALID_COOKIE_HEADER}

    result = await flow.async_step_storage(
        user_input={
            CONF_STORAGE_TYPE: STORAGE_TYPE_S3,
            CONF_S3_BUCKET: "",
            CONF_S3_ENDPOINT: "https://s3.example.com",
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "storage"
    assert result["errors"]["base"] == "missing_s3_bucket"
    assert result["errors"][CONF_S3_BUCKET] == "missing_s3_bucket"


async def test_step_storage_s3_success(hass: MockHomeAssistant) -> None:
    """Verify full config flow completion with valid S3 configuration."""
    flow = JunieRemoteConfigFlow()
    flow.hass = hass
    flow._config_data = {
        "auth_input": VALID_COOKIE_HEADER,
        "base_url": "https://junie.jetbrains.com",
    }

    result = await flow.async_step_storage(
        user_input={
            CONF_STORAGE_TYPE: STORAGE_TYPE_S3,
            CONF_S3_ENDPOINT: "https://minio.lan:9000",
            CONF_S3_BUCKET: "junie-transcripts",
            CONF_S3_REGION: "auto",
            CONF_S3_ACCESS_KEY: "minio-key",
            CONF_S3_SECRET_KEY: "minio-secret",
            CONF_S3_PUBLIC_URL_BASE: "https://s3.lan/junie-transcripts",
        }
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "JetBrains Junie Remote"
    assert result["data"][CONF_STORAGE_TYPE] == STORAGE_TYPE_S3
    assert result["data"][CONF_S3_BUCKET] == "junie-transcripts"
    assert result["data"][CONF_S3_ENDPOINT] == "https://minio.lan:9000"
    assert result["data"][CONF_S3_PUBLIC_URL_BASE] == "https://s3.lan/junie-transcripts"


# --- Reauth Flow Tests ---


async def test_reauth_flow_success(hass: MockHomeAssistant) -> None:
    """Verify re-authentication flow successfully updates existing entry."""
    entry = ConfigEntry(
        entry_id="existing_entry_1",
        domain=DOMAIN,
        title="JetBrains Junie Remote",
        data={
            "auth_input": "expired_session_cookie",
            "base_url": "https://junie.jetbrains.com",
        },
    )
    hass.config_entries.entries[entry.entry_id] = entry

    flow = JunieRemoteConfigFlow()
    flow.hass = hass
    flow.context = {"entry_id": entry.entry_id}

    # Step 1: initiate reauth
    init_res = await flow.async_step_reauth()
    assert init_res["type"] == "form"
    assert init_res["step_id"] == "reauth_confirm"

    # Step 2: enter invalid auth
    invalid_res = await flow.async_step_reauth_confirm(user_input={"auth_input": ""})
    assert invalid_res["type"] == "form"
    assert invalid_res["errors"]["base"] == "invalid_auth"

    # Step 3: enter valid auth
    with patch(
        "custom_components.junie_remote.config_flow.JunieRemoteClient.list_tunnels",
        new=AsyncMock(return_value=[]),
    ):
        success_res = await flow.async_step_reauth_confirm(
            user_input={"auth_input": VALID_STORAGE_STATE}
        )
        assert success_res["type"] == "abort"
        assert success_res["reason"] == "reauth_successful"
        assert entry.data["auth_input"] == VALID_STORAGE_STATE


# --- Options Flow Tests ---


async def test_options_flow_init_shows_form(hass: MockHomeAssistant) -> None:
    """Verify options flow displays current configuration as defaults."""
    entry = ConfigEntry(
        entry_id="opt_entry_1",
        domain=DOMAIN,
        data={
            "auth_input": VALID_STORAGE_STATE,
            CONF_STORAGE_TYPE: STORAGE_TYPE_LOCAL,
            CONF_LOCAL_STORAGE_PATH: DEFAULT_LOCAL_STORAGE_PATH,
        },
        options={},
    )
    hass.config_entries.entries[entry.entry_id] = entry

    options_flow = JunieRemoteConfigFlow.async_get_options_flow(entry)
    options_flow.hass = hass

    result = await options_flow.async_step_init(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "init"
    assert result["errors"] == {}


async def test_options_flow_update_storage_success(hass: MockHomeAssistant) -> None:
    """Verify options flow updates storage configuration to S3."""
    entry = ConfigEntry(
        entry_id="opt_entry_2",
        domain=DOMAIN,
        data={
            "auth_input": VALID_COOKIE_HEADER,
            CONF_STORAGE_TYPE: STORAGE_TYPE_LOCAL,
            CONF_LOCAL_STORAGE_PATH: DEFAULT_LOCAL_STORAGE_PATH,
        },
        options={},
    )

    options_flow = JunieRemoteOptionsFlow(entry)
    options_flow.hass = hass

    result = await options_flow.async_step_init(
        user_input={
            "auth_input": VALID_COOKIE_HEADER,
            CONF_STORAGE_TYPE: STORAGE_TYPE_S3,
            CONF_S3_ENDPOINT: "https://garage.storage:3900",
            CONF_S3_BUCKET: "transcripts-prod",
            CONF_S3_REGION: "garage",
            CONF_S3_ACCESS_KEY: "garage-key",
            CONF_S3_SECRET_KEY: "garage-secret",
            CONF_S3_PUBLIC_URL_BASE: "",
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_STORAGE_TYPE] == STORAGE_TYPE_S3
    assert result["data"][CONF_S3_BUCKET] == "transcripts-prod"


async def test_options_flow_s3_missing_bucket_error(hass: MockHomeAssistant) -> None:
    """Verify validation error in options flow when switching to S3 without bucket."""
    entry = ConfigEntry(
        entry_id="opt_entry_3",
        domain=DOMAIN,
        data={"auth_input": VALID_COOKIE_HEADER, CONF_STORAGE_TYPE: STORAGE_TYPE_LOCAL},
        options={},
    )

    options_flow = JunieRemoteOptionsFlow(entry)
    options_flow.hass = hass

    result = await options_flow.async_step_init(
        user_input={
            "auth_input": VALID_COOKIE_HEADER,
            CONF_STORAGE_TYPE: STORAGE_TYPE_S3,
            CONF_S3_BUCKET: "",
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "init"
    assert result["errors"]["base"] == "missing_s3_bucket"
    assert result["errors"][CONF_S3_BUCKET] == "missing_s3_bucket"


async def test_options_flow_update_auth_input_invalid(hass: MockHomeAssistant) -> None:
    """Verify error when updating auth_input with invalid cookies."""
    entry = ConfigEntry(
        entry_id="opt_entry_4",
        domain=DOMAIN,
        data={"auth_input": VALID_COOKIE_HEADER, CONF_STORAGE_TYPE: STORAGE_TYPE_LOCAL},
        options={},
    )

    options_flow = JunieRemoteOptionsFlow(entry)
    options_flow.hass = hass

    result = await options_flow.async_step_init(
        user_input={
            "auth_input": "invalid-cookie-string",
            CONF_STORAGE_TYPE: STORAGE_TYPE_LOCAL,
            CONF_LOCAL_STORAGE_PATH: DEFAULT_LOCAL_STORAGE_PATH,
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "init"
    assert result["errors"]["base"] == "invalid_auth"


# --- Local transcript privacy ---


async def test_storage_step_rejects_public_local_paths(hass: MockHomeAssistant, tmp_path) -> None:
    """Paths inside /config/www (or its symlinks) are rejected with a clear error."""
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "www").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "www", target_is_directory=True)
    for bad in ("www/junie_remote", "www", str(tmp_path / "www" / "x"), "link/sub"):
        flow = JunieRemoteConfigFlow()
        flow.hass = hass
        flow._config_data = {"auth_input": VALID_COOKIE_HEADER}
        result = await flow.async_step_storage(
            user_input={CONF_STORAGE_TYPE: STORAGE_TYPE_LOCAL, CONF_LOCAL_STORAGE_PATH: bad}
        )
        assert result["type"] == "form", bad
        assert result["errors"][CONF_LOCAL_STORAGE_PATH] == "public_local_path"

    flow = JunieRemoteConfigFlow()
    flow.hass = hass
    flow._config_data = {"auth_input": VALID_COOKIE_HEADER}
    result = await flow.async_step_storage(
        user_input={
            CONF_STORAGE_TYPE: STORAGE_TYPE_LOCAL,
            CONF_LOCAL_STORAGE_PATH: "private/junie",
        }
    )
    assert result["type"] == "create_entry"


async def test_options_flow_rejects_public_path_and_prefills_private_default(
    hass: MockHomeAssistant, tmp_path
) -> None:
    """A legacy public path is not pre-filled and cannot be re-submitted."""
    hass.config.config_dir = str(tmp_path)
    entry = ConfigEntry(
        entry_id="legacy",
        domain=DOMAIN,
        data={
            "auth_input": VALID_COOKIE_HEADER,
            CONF_STORAGE_TYPE: STORAGE_TYPE_LOCAL,
            CONF_LOCAL_STORAGE_PATH: "www/junie_remote",
        },
        options={},
    )
    flow = JunieRemoteConfigFlow.async_get_options_flow(entry)
    flow.hass = hass
    form = await flow.async_step_init(user_input=None)
    schema = form["data_schema"].schema
    defaults = {
        getattr(k, "schema", k): getattr(k, "default", None) for k in schema
    }
    default = defaults[CONF_LOCAL_STORAGE_PATH]
    assert (default() if callable(default) else default) == DEFAULT_LOCAL_STORAGE_PATH

    result = await flow.async_step_init(
        user_input={
            "auth_input": VALID_COOKIE_HEADER,
            CONF_STORAGE_TYPE: STORAGE_TYPE_LOCAL,
            CONF_LOCAL_STORAGE_PATH: "www/junie_remote",
        }
    )
    assert result["type"] == "form"
    assert result["errors"][CONF_LOCAL_STORAGE_PATH] == "public_local_path"


def test_strings_warn_about_public_local_exposure_before_storage_selection() -> None:
    """The storage step and options warn immediately, in plain language."""
    import json
    from pathlib import Path

    strings = json.loads(
        (Path(__file__).parents[1] / "custom_components/junie_remote/strings.json").read_text()
    )
    for text in (
        strings["config"]["step"]["storage"]["description"],
        strings["options"]["step"]["init"]["description"],
    ):
        assert "/local/" in text and "without authentication" in text
        assert "NOT deleted" in text and "backups" in text
        assert "S3" in text and "bearer" in text
    assert "public_local_path" in strings["config"]["error"]
    assert "public_local_path" in strings["options"]["error"]
