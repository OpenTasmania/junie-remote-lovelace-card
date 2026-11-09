"""Credential recovery against Home Assistant's real options flow manager."""

from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components
from custom_components.junie_remote.const import DOMAIN
from custom_components.junie_remote.models import JunieAuthError, JunieRemoteError


async def test_options_credential_recovery(hass, enable_custom_integrations, monkeypatch):
    monkeypatch.setattr(custom_components, "__path__", [custom_components.__path__[0]])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"auth_input": "SESSION=old", "storage_type": "s3", "s3_bucket": "bucket"},
        options={"auth_input": "SESSION=stale", "storage_type": "s3", "s3_bucket": "bucket"},
    )
    entry.add_to_hass(hass)
    reloads = []

    async def updated(hass, updated_entry):
        reloads.append(updated_entry.entry_id)

    entry.add_update_listener(updated)
    with patch(
        "custom_components.junie_remote.config_flow.JunieRemoteClient.list_tunnels",
        new=AsyncMock(side_effect=[JunieAuthError("401"), JunieRemoteError("network"), []]),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        data = {
            "auth_input": "SESSION=fresh; XSRF-TOKEN=token",
            "storage_type": "s3",
            "s3_bucket": "bucket",
        }
        result = await hass.config_entries.options.async_configure(result["flow_id"], data)
        assert result["errors"]["base"] == "invalid_auth"
        assert entry.options["auth_input"] == "SESSION=stale"
        result = await hass.config_entries.options.async_configure(result["flow_id"], data)
        assert result["errors"]["base"] == "cannot_connect"
        assert entry.options["s3_bucket"] == "bucket"
        result = await hass.config_entries.options.async_configure(result["flow_id"], data)
        assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["auth_input"] == data["auth_input"]
    assert entry.options["s3_bucket"] == "bucket"
    assert reloads == [entry.entry_id]


async def test_options_reload_uses_new_credentials(hass, enable_custom_integrations, monkeypatch):
    monkeypatch.setattr(custom_components, "__path__", [custom_components.__path__[0]])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"auth_input": "SESSION=original", "storage_type": "local"},
        options={"auth_input": "SESSION=old", "storage_type": "local"},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.junie_remote.client.JunieRemoteClient.list_tunnels",
        new=AsyncMock(return_value=[]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        old = hass.data[DOMAIN][entry.entry_id]
        assert old.client.cookies["SESSION"] == "old"
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"auth_input": "SESSION=new; XSRF-TOKEN=token", "storage_type": "local"},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        new = hass.data[DOMAIN][entry.entry_id]
        assert new is not old
        assert new.client.cookies["SESSION"] == "new"
        assert entry.data["auth_input"] == "SESSION=original"
        assert entry.options["storage_type"] == "local"
