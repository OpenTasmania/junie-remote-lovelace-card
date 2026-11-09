# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Sensor platform for JetBrains Junie Remote integration."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN
from .coordinator import JunieRemoteCoordinator
from .entity import JunieRemoteHostEntity
from .ha_compat import ConfigEntry, HomeAssistant, SensorEntity, callback


class JunieRemoteStatusSensor(JunieRemoteHostEntity, SensorEntity):
    """Sensor exposing Junie Remote host status and session state."""

    _attr_name = "Status"
    _attr_translation_key = "status"

    def __init__(self, coordinator: JunieRemoteCoordinator, host_key: str) -> None:
        """Initialize the status sensor."""
        super().__init__(coordinator, host_key)
        self._attr_unique_id = f"{host_key}_status"

    @property
    def native_value(self) -> str | None:
        """Return the current status of the Junie remote session."""
        host_state = self.host_state
        if not host_state:
            return None
        if host_state.connection_status == "connected":
            return host_state.chat_state.session_status or "idle"
        return host_state.connection_status

    @property
    def icon(self) -> str:
        """Return dynamic status icon."""
        val = self.native_value
        if val == "working":
            return "mdi:progress-clock"
        if val == "waiting-for-input":
            return "mdi:help-circle-outline"
        if val == "idle":
            return "mdi:robot-happy"
        if val in ("disconnected", "offline", "rejected", "kicked", "tunnel-not-found"):
            return "mdi:lan-disconnect"
        return "mdi:robot"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return concise state attributes for Home Assistant state machine."""
        host_state = self.host_state
        if not host_state:
            return {}

        chat_state = host_state.chat_state
        tunnel = host_state.tunnel
        metadata = tunnel.metadata
        res = host_state.transcript_result

        plan_summary: dict[str, Any] | None = None
        if chat_state.plan_proposal is not None:
            plan = chat_state.plan_proposal
            section_names = [
                str(sec.get("name") or sec.get("title") or "")
                for sec in plan.sections
                if isinstance(sec, dict)
            ]
            plan_summary = {
                "ready_for_review": plan.ready_for_review,
                "show_actions": plan.show_actions,
                "plan_file_path": plan.plan_file_path,
                "section_names": section_names,
                "delivery_steps": plan.delivery_steps,
            }

        model_options = [
            {"value": val, "label": label}
            for val, label in chat_state.model_selection.get_selectable_options()
        ]

        last_step_preview = (
            res.last_step_preview
            if res and res.last_step_preview is not None
            else ""
        )

        return {
            "host_key": host_state.host_key,
            "tunnel_id": tunnel.tunnel_id,
            "user_name": metadata.user_name,
            "os_name": metadata.os_name,
            "git_repo": metadata.git_repo_url,
            "git_branch": chat_state.git_branch or metadata.git_branch,
            "working_dir": chat_state.working_dir or metadata.current_directory,
            "title": chat_state.title,
            "connection_status": host_state.connection_status,
            "session_status": chat_state.session_status,
            "can_send_prompt": chat_state.can_send_prompt,
            "brave_mode": chat_state.brave_mode,
            "has_plan": chat_state.has_plan,
            "connected_clients": tunnel.connected_clients,
            "last_error": host_state.last_error,
            "current_model_id": chat_state.model_selection.current_model_id,
            "current_effort_id": chat_state.model_selection.current_effort_id,
            "selected_model_effort": chat_state.model_selection.current_selection,
            "model_options": model_options,
            "active_requests": chat_state.active_requests,
            "plan_summary": plan_summary,
            "progressing_steps_count": len(chat_state.progressing_steps),
            "last_step_preview": last_step_preview,
            "transcript_json_url": res.json_url if res else None,
            "transcript_md_url": res.md_url if res else None,
            "transcript_updated_at": res.updated_at if res else None,
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up Junie Remote sensor entities from a config entry."""
    coordinator: JunieRemoteCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_host_keys: set[str] = set()

    @callback
    def _add_new_entities() -> None:
        new_keys = set(coordinator.hosts.keys()) - known_host_keys
        if new_keys:
            entities = [
                JunieRemoteStatusSensor(coordinator, host_key)
                for host_key in sorted(new_keys)
            ]
            known_host_keys.update(new_keys)
            async_add_entities(entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))
