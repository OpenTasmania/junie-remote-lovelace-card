# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Switch platform for JetBrains Junie Remote integration."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN
from .coordinator import JunieRemoteCoordinator
from .entity import JunieRemoteHostEntity
from .ha_compat import ConfigEntry, HomeAssistant, SwitchEntity, callback


class JunieRemoteBraveModeSwitch(JunieRemoteHostEntity, SwitchEntity):
    """Switch allowing users to toggle Brave Mode on a remote Junie host."""

    _attr_name = "Brave Mode"
    _attr_icon = "mdi:shield-alert"

    def __init__(self, coordinator: JunieRemoteCoordinator, host_key: str) -> None:
        """Initialize the brave mode switch."""
        super().__init__(coordinator, host_key)
        self._attr_unique_id = f"{host_key}_brave_mode"

    @property
    def is_on(self) -> bool:
        """Return True if brave mode is currently enabled."""
        if not self.host_state:
            return False
        return bool(self.host_state.chat_state.brave_mode)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable brave mode."""
        await self.coordinator.async_toggle_brave_mode(self.host_key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable brave mode."""
        await self.coordinator.async_toggle_brave_mode(self.host_key, False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up Junie Remote switch entities from a config entry."""
    coordinator: JunieRemoteCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_host_keys: set[str] = set()

    @callback
    def _add_new_entities() -> None:
        new_keys = set(coordinator.hosts.keys()) - known_host_keys
        if new_keys:
            entities = [
                JunieRemoteBraveModeSwitch(coordinator, host_key)
                for host_key in sorted(new_keys)
            ]
            known_host_keys.update(new_keys)
            async_add_entities(entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))
