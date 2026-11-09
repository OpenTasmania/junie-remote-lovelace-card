# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Base entity class for JetBrains Junie Remote integration."""

from __future__ import annotations

from .const import DOMAIN
from .coordinator import HostBridgeState, JunieRemoteCoordinator
from .ha_compat import CoordinatorEntity, DeviceInfo


class JunieRemoteHostEntity(CoordinatorEntity[dict[str, HostBridgeState]]):
    """Base entity bound to a specific host on the Junie Remote coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: JunieRemoteCoordinator, host_key: str) -> None:
        """Initialize the host entity."""
        super().__init__(coordinator)
        self.host_key = host_key

    @property
    def host_state(self) -> HostBridgeState | None:
        """Return the current host bridge state from the coordinator."""
        return self.coordinator.hosts.get(self.host_key)

    @property
    def available(self) -> bool:
        """Return True if host is known and coordinator last update succeeded."""
        return super().available and self.host_state is not None

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device registry information for this remote host."""
        host_state = self.host_state
        if not host_state:
            return None
        return DeviceInfo(
            identifiers={(DOMAIN, self.host_key)},
            name=host_state.device_name,
            manufacturer="JetBrains",
            model=host_state.tunnel.metadata.os_name or "Junie CLI",
            configuration_url="https://junie.jetbrains.com/remote/",
        )
