# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Verify custom integration translations through the real HA loader."""

from pathlib import Path

from homeassistant import loader
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

import custom_components
from custom_components.junie_remote.const import DOMAIN


async def test_translations_load_correctly(tmp_path, monkeypatch) -> None:
    """HA loads the security warnings and error from the custom integration."""
    components = tmp_path / "custom_components"
    components.mkdir()
    source = Path(__file__).resolve().parents[1] / "custom_components" / DOMAIN
    (components / DOMAIN).symlink_to(source, target_is_directory=True)
    # The editable install includes a non-directory path hook in the namespace.
    monkeypatch.setattr(custom_components, "__path__", [str(components)])
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)

    config = await async_get_translations(hass, "en", "config", [DOMAIN])
    options = await async_get_translations(hass, "en", "options", [DOMAIN])

    storage_desc = config["component.junie_remote.config.step.storage.description"]
    options_desc = options["component.junie_remote.options.step.init.description"]
    public_path_error = config["component.junie_remote.config.error.public_local_path"]
    assert "Security warning" in storage_desc
    assert "New local transcripts are stored privately" in storage_desc
    assert "Security warning" in options_desc
    assert "/config/www" in public_path_error
