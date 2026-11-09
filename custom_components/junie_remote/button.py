# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Button platform for JetBrains Junie Remote integration."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN
from .coordinator import JunieRemoteCoordinator
from .entity import JunieRemoteHostEntity
from .ha_compat import ButtonEntity, ConfigEntry, HomeAssistant, callback


class JunieRemoteStopButton(JunieRemoteHostEntity, ButtonEntity):
    """Button to stop/cancel the currently running task on the remote host."""

    _attr_name = "Stop Task"
    _attr_icon = "mdi:stop-circle-outline"

    def __init__(self, coordinator: JunieRemoteCoordinator, host_key: str) -> None:
        """Initialize the stop button."""
        super().__init__(coordinator, host_key)
        self._attr_unique_id = f"{host_key}_stop"

    async def async_press(self) -> None:
        """Press the stop button to cancel current task."""
        await self.coordinator.async_cancel(self.host_key)


class JunieRemoteConfirmPlanButton(JunieRemoteHostEntity, ButtonEntity):
    """Button to confirm and execute the active proposed plan."""

    _attr_name = "Confirm Plan"
    _attr_icon = "mdi:clipboard-check-outline"

    def __init__(self, coordinator: JunieRemoteCoordinator, host_key: str) -> None:
        """Initialize the confirm plan button."""
        super().__init__(coordinator, host_key)
        self._attr_unique_id = f"{host_key}_confirm_plan"

    async def async_press(self) -> None:
        """Press the button to confirm and implement the proposed plan."""
        await self.coordinator.async_confirm_plan(self.host_key)


class JunieRemoteTakeOverButton(JunieRemoteHostEntity, ButtonEntity):
    """Button to kick conflicting web clients and take over the session."""

    _attr_name = "Take Over"
    _attr_icon = "mdi:account-switch-outline"

    def __init__(self, coordinator: JunieRemoteCoordinator, host_key: str) -> None:
        """Initialize the take over button."""
        super().__init__(coordinator, host_key)
        self._attr_unique_id = f"{host_key}_take_over"

    async def async_press(self) -> None:
        """Press the button to kick connected clients and take over connection."""
        await self.coordinator.async_kick_and_takeover(self.host_key)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up Junie Remote button entities from a config entry."""
    coordinator: JunieRemoteCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_host_keys: set[str] = set()

    @callback
    def _add_new_entities() -> None:
        new_keys = set(coordinator.hosts.keys()) - known_host_keys
        if new_keys:
            entities: list[ButtonEntity] = []
            for host_key in sorted(new_keys):
                entities.extend([
                    JunieRemoteStopButton(coordinator, host_key),
                    JunieRemoteConfirmPlanButton(coordinator, host_key),
                    JunieRemoteTakeOverButton(coordinator, host_key),
                ])
            known_host_keys.update(new_keys)
            async_add_entities(entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))
