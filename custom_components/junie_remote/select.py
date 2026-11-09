# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Select platform for JetBrains Junie Remote integration."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN
from .coordinator import JunieRemoteCoordinator
from .entity import JunieRemoteHostEntity
from .ha_compat import ConfigEntry, HomeAssistant, SelectEntity, callback


class JunieRemoteModelEffortSelect(JunieRemoteHostEntity, SelectEntity):
    """Select entity for choosing the active LLM model and effort level."""

    _attr_name = "Model & Effort"
    _attr_icon = "mdi:brain"

    def __init__(self, coordinator: JunieRemoteCoordinator, host_key: str) -> None:
        """Initialize the model select entity."""
        super().__init__(coordinator, host_key)
        self._attr_unique_id = f"{host_key}_model_effort"

    @property
    def options(self) -> list[str]:
        """Return list of selectable options formatted as 'model_id:effort_id'."""
        if not self.host_state:
            return []
        opts = [
            val
            for val, _ in self.host_state.chat_state.model_selection.get_selectable_options()
        ]
        curr = self.host_state.chat_state.model_selection.current_selection
        if curr and curr not in opts:
            opts.insert(0, curr)
        return opts

    @property
    def current_option(self) -> str | None:
        """Return currently selected model:effort string."""
        if not self.host_state:
            return None
        curr = self.host_state.chat_state.model_selection.current_selection
        return curr or None

    async def async_select_option(self, option: str) -> None:
        """Change the selected model and reasoning effort level."""
        parts = option.split(":", 1)
        model_id = parts[0]
        effort_id = parts[1] if len(parts) > 1 else None
        await self.coordinator.async_select_model(self.host_key, model_id, effort_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up Junie Remote select entities from a config entry."""
    coordinator: JunieRemoteCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_host_keys: set[str] = set()

    @callback
    def _add_new_entities() -> None:
        new_keys = set(coordinator.hosts.keys()) - known_host_keys
        if new_keys:
            entities = [
                JunieRemoteModelEffortSelect(coordinator, host_key)
                for host_key in sorted(new_keys)
            ]
            known_host_keys.update(new_keys)
            async_add_entities(entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))
