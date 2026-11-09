# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Unit tests for Junie Remote entities (sensor, switch, select, button) and services."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.junie_remote import (
    DOMAIN,
    _async_register_services,
    _async_unregister_services,
    _build_response_payload,
    _extract_host_key,
    _get_coordinator_for_host,
    async_setup,
    async_setup_entry,
)
from custom_components.junie_remote.button import (
    JunieRemoteConfirmPlanButton,
    JunieRemoteStopButton,
    JunieRemoteTakeOverButton,
)
from custom_components.junie_remote.button import (
    async_setup_entry as async_setup_button,
)
from custom_components.junie_remote.client import JunieRemoteClient
from custom_components.junie_remote.const import (
    SERVICE_CANCEL,
    SERVICE_CANCEL_TASK,
    SERVICE_CLEANUP_TRANSCRIPTS,
    SERVICE_CONFIRM_PLAN,
    SERVICE_KICK_CLIENT,
    SERVICE_RESPOND,
    SERVICE_RESPOND_REQUEST,
    SERVICE_RESUME_TRANSCRIPTS,
    SERVICE_SELECT_MODEL,
    SERVICE_SEND_PLAN_PROMPT,
    SERVICE_SEND_PROMPT,
    SERVICE_TOGGLE_BRAVE_MODE,
)
from custom_components.junie_remote.coordinator import (
    HostBridgeState,
    JunieRemoteCoordinator,
)
from custom_components.junie_remote.entity import JunieRemoteHostEntity
from custom_components.junie_remote.ha_compat import (
    ConfigEntry,
    HomeAssistant,
    HomeAssistantError,
    Unauthorized,
)
from custom_components.junie_remote.models import (
    ChatSessionState,
    ModelOption,
    ModelSelectionState,
    PlanProposal,
    TunnelInfo,
    TunnelMetadata,
)
from custom_components.junie_remote.select import (
    JunieRemoteModelEffortSelect,
)
from custom_components.junie_remote.select import (
    async_setup_entry as async_setup_select,
)
from custom_components.junie_remote.sensor import (
    JunieRemoteStatusSensor,
)
from custom_components.junie_remote.sensor import (
    async_setup_entry as async_setup_sensor,
)
from custom_components.junie_remote.storage import (
    LocalTranscriptStorage,
    TranscriptDocument,
    TranscriptResult,
)
from custom_components.junie_remote.switch import (
    JunieRemoteBraveModeSwitch,
)
from custom_components.junie_remote.switch import (
    async_setup_entry as async_setup_switch,
)
from custom_components.junie_remote.transcript_inventory import TranscriptInventory


@pytest.fixture
def hass() -> HomeAssistant:
    """Fixture providing a mock HomeAssistant instance."""
    return HomeAssistant()


@pytest.fixture
def mock_storage(tmp_path: Path) -> LocalTranscriptStorage:
    """Fixture providing local transcript storage."""
    return LocalTranscriptStorage(
        base_dir=tmp_path / "transcripts",
        entry_id="entry-1",
        inventory=TranscriptInventory(HomeAssistant()),
    )


def make_test_host(
    host_key: str = "alice_linux_my_repo",
    tunnel_id: str = "tunnel-1234",
    user_name: str = "alice",
    os_name: str = "Linux",
    git_repo: str = "https://github.com/org/my-repo.git",
    connection_status: str = "connected",
) -> HostBridgeState:
    """Helper to build a configured HostBridgeState."""
    meta = TunnelMetadata(
        user_name=user_name,
        os_name=os_name,
        git_repo_url=git_repo,
        current_directory="/home/alice/my-repo",
    )
    tunnel = TunnelInfo(
        tunnel_id=tunnel_id,
        connected_clients=1,
        metadata=meta,
    )
    chat_state = ChatSessionState(
        title="Test Session",
        git_branch="master",
        working_dir="/home/alice/my-repo",
        session_status="idle",
        can_send_prompt=True,
        brave_mode=False,
        has_plan=False,
    )
    return HostBridgeState(
        host_key=host_key,
        tunnel=tunnel,
        chat_state=chat_state,
        connection_status=connection_status,
        transcript_result=TranscriptResult(
            json_url="http://ha/local/latest.json",
            md_url="http://ha/local/latest.md",
            last_step_preview="Executed pytest tests",
            updated_at="2026-11-07T12:00:00Z",
        ),
    )


@pytest.fixture
def coordinator(
    hass: HomeAssistant, mock_storage: LocalTranscriptStorage
) -> JunieRemoteCoordinator:
    """Fixture providing a coordinator with one pre-registered host."""
    client = MagicMock(spec=JunieRemoteClient)
    coord = JunieRemoteCoordinator(
        hass=hass,
        client=client,
        storage=mock_storage,
        auto_connect=False,
    )
    host = make_test_host()
    coord.hosts[host.host_key] = host
    coord.async_send_prompt = AsyncMock()
    coord.async_send_plan_prompt = AsyncMock()
    coord.async_confirm_plan = AsyncMock()
    coord.async_cancel = AsyncMock()
    coord.async_toggle_brave_mode = AsyncMock()
    coord.async_select_model = AsyncMock()
    coord.async_respond_request = AsyncMock()
    coord.async_kick_and_takeover = AsyncMock()
    return coord


# =========================================================================
# Base Entity Tests
# =========================================================================


def test_base_host_entity(coordinator: JunieRemoteCoordinator) -> None:
    """Verify JunieRemoteHostEntity properties and device_info."""
    entity = JunieRemoteHostEntity(coordinator, "alice_linux_my_repo")

    assert entity.host_key == "alice_linux_my_repo"
    assert entity.available is True
    assert entity.host_state is not None

    dev = entity.device_info
    assert dev is not None
    assert (DOMAIN, "alice_linux_my_repo") in dev.identifiers
    assert "alice@Linux" in (dev.name or "")
    assert dev.manufacturer == "JetBrains"
    assert dev.model == "Linux"
    assert dev.configuration_url == "https://junie.jetbrains.com/remote/"

    # When host does not exist
    missing_entity = JunieRemoteHostEntity(coordinator, "non_existent_host")
    assert missing_entity.available is False
    assert missing_entity.host_state is None
    assert missing_entity.device_info is None


# =========================================================================
# Sensor Platform Tests
# =========================================================================


def test_status_sensor_native_values(coordinator: JunieRemoteCoordinator) -> None:
    """Verify sensor native_value across connected session statuses and disconnected states."""
    host = coordinator.hosts["alice_linux_my_repo"]
    sensor = JunieRemoteStatusSensor(coordinator, "alice_linux_my_repo")

    assert sensor.unique_id == "alice_linux_my_repo_status"

    # 1. Connected & session_status
    host.connection_status = "connected"
    host.chat_state.session_status = "idle"
    assert sensor.native_value == "idle"
    assert sensor.icon == "mdi:robot-happy"

    host.chat_state.session_status = "working"
    assert sensor.native_value == "working"
    assert sensor.icon == "mdi:progress-clock"

    host.chat_state.session_status = "waiting-for-input"
    assert sensor.native_value == "waiting-for-input"
    assert sensor.icon == "mdi:help-circle-outline"

    # 2. Non-connected states report connection_status
    non_connected = (
        "connecting",
        "reconnecting",
        "rejected",
        "kicked",
        "disconnected",
        "tunnel-not-found",
    )
    for status in non_connected:
        host.connection_status = status
        assert sensor.native_value == status
        if status in ("disconnected", "rejected", "kicked", "tunnel-not-found"):
            assert sensor.icon == "mdi:lan-disconnect"

    # Missing host returns None
    missing_sensor = JunieRemoteStatusSensor(coordinator, "missing_host")
    assert missing_sensor.native_value is None


def test_status_sensor_extra_state_attributes(coordinator: JunieRemoteCoordinator) -> None:
    """Verify extra_state_attributes exposes full metadata, model options, active requests, plan."""
    host = coordinator.hosts["alice_linux_my_repo"]
    sensor = JunieRemoteStatusSensor(coordinator, "alice_linux_my_repo")

    # Set up models
    host.chat_state.model_selection = ModelSelectionState(
        current_model_id="claude-3-7-sonnet",
        current_effort_id="high",
        models=[
            ModelOption(
                id="claude-3-7-sonnet",
                name="Claude 3.7 Sonnet",
                supported_efforts=[
                    {"id": "low", "name": "Low"},
                    {"id": "high", "name": "High"},
                ],
            )
        ],
    )

    # Set up active requests
    host.chat_state.active_requests = [
        {"requestId": "req-1", "type": "ask", "question": "Proceed?"}
    ]

    # Set up plan proposal
    host.chat_state.plan_proposal = PlanProposal(
        seq=3,
        ready_for_review=True,
        show_actions=True,
        plan_file_path="/tmp/plan.md",
        sections=[{"name": "Architecture"}, {"title": "Implementation"}],
        delivery_steps=[{"name": "Step 1", "description": "Do work"}],
    )

    attrs = sensor.extra_state_attributes

    assert attrs["host_key"] == "alice_linux_my_repo"
    assert attrs["tunnel_id"] == "tunnel-1234"
    assert attrs["user_name"] == "alice"
    assert attrs["os_name"] == "Linux"
    assert attrs["git_repo"] == "https://github.com/org/my-repo.git"
    assert attrs["git_branch"] == "master"
    assert attrs["working_dir"] == "/home/alice/my-repo"
    assert attrs["title"] == "Test Session"
    assert attrs["connection_status"] == "connected"
    assert attrs["session_status"] == "idle"
    assert attrs["can_send_prompt"] is True
    assert attrs["brave_mode"] is False
    assert attrs["connected_clients"] == 1
    assert attrs["current_model_id"] == "claude-3-7-sonnet"
    assert attrs["current_effort_id"] == "high"
    assert attrs["selected_model_effort"] == "claude-3-7-sonnet:high"
    assert attrs["model_options"] == [
        {"value": "claude-3-7-sonnet:low", "label": "Claude 3.7 Sonnet · Low"},
        {"value": "claude-3-7-sonnet:high", "label": "Claude 3.7 Sonnet · High"},
    ]
    assert attrs["active_requests"] == [
        {"requestId": "req-1", "type": "ask", "question": "Proceed?"}
    ]
    assert attrs["plan_summary"] == {
        "ready_for_review": True,
        "show_actions": True,
        "plan_file_path": "/tmp/plan.md",
        "section_names": ["Architecture", "Implementation"],
        "delivery_steps": [{"name": "Step 1", "description": "Do work"}],
    }
    assert attrs["progressing_steps_count"] == 0
    assert attrs["last_step_preview"] == "Executed pytest tests"
    assert attrs["transcript_json_url"] == "http://ha/local/latest.json"
    assert attrs["transcript_md_url"] == "http://ha/local/latest.md"
    assert attrs["transcript_updated_at"] == "2026-11-07T12:00:00Z"


async def test_sensor_dynamic_addition(
    hass: HomeAssistant, coordinator: JunieRemoteCoordinator
) -> None:
    """Verify dynamic discovery creates sensor entities when new hosts are discovered."""
    entry = ConfigEntry(entry_id="test_entry")
    hass.data[DOMAIN] = {entry.entry_id: coordinator}

    added_entities: list[list[JunieRemoteStatusSensor]] = []

    def mock_add_entities(entities: list[JunieRemoteStatusSensor]) -> None:
        added_entities.append(entities)

    await async_setup_sensor(hass, entry, mock_add_entities)

    # Initially 1 entity added for existing host
    assert len(added_entities) == 1
    assert len(added_entities[0]) == 1
    assert added_entities[0][0].host_key == "alice_linux_my_repo"

    # Now add a second host to coordinator and fire coordinator listeners
    h2 = make_test_host(host_key="bob_macos_web", tunnel_id="tunnel-bob")
    coordinator.hosts[h2.host_key] = h2
    coordinator.async_set_updated_data(coordinator.hosts)

    assert len(added_entities) == 2
    assert len(added_entities[1]) == 1
    assert added_entities[1][0].host_key == "bob_macos_web"


# =========================================================================
# Switch Platform Tests
# =========================================================================


async def test_brave_mode_switch(coordinator: JunieRemoteCoordinator) -> None:
    """Verify Brave Mode switch states and toggle actions."""
    host = coordinator.hosts["alice_linux_my_repo"]
    switch = JunieRemoteBraveModeSwitch(coordinator, "alice_linux_my_repo")

    assert switch.unique_id == "alice_linux_my_repo_brave_mode"
    assert switch.icon == "mdi:shield-alert"
    assert switch.is_on is False

    host.chat_state.brave_mode = True
    assert switch.is_on is True

    # Turn on
    await switch.async_turn_on()
    coordinator.async_toggle_brave_mode.assert_called_with("alice_linux_my_repo", True)

    # Turn off
    await switch.async_turn_off()
    coordinator.async_toggle_brave_mode.assert_called_with("alice_linux_my_repo", False)


async def test_switch_dynamic_addition(
    hass: HomeAssistant, coordinator: JunieRemoteCoordinator
) -> None:
    """Verify dynamic discovery creates switch entities for new hosts."""
    entry = ConfigEntry(entry_id="test_entry")
    hass.data[DOMAIN] = {entry.entry_id: coordinator}

    added_entities: list[list[JunieRemoteBraveModeSwitch]] = []
    await async_setup_switch(hass, entry, lambda ents: added_entities.append(ents))

    assert len(added_entities) == 1
    assert added_entities[0][0].unique_id == "alice_linux_my_repo_brave_mode"

    # Discover new host
    h2 = make_test_host(host_key="bob_macos_web", tunnel_id="tunnel-bob")
    coordinator.hosts[h2.host_key] = h2
    coordinator.async_set_updated_data(coordinator.hosts)

    assert len(added_entities) == 2
    assert added_entities[1][0].unique_id == "bob_macos_web_brave_mode"


# =========================================================================
# Select Platform Tests
# =========================================================================


async def test_model_effort_select(coordinator: JunieRemoteCoordinator) -> None:
    """Verify model selection options and option change action."""
    host = coordinator.hosts["alice_linux_my_repo"]
    select = JunieRemoteModelEffortSelect(coordinator, "alice_linux_my_repo")

    assert select.unique_id == "alice_linux_my_repo_model_effort"
    assert select.icon == "mdi:brain"

    host.chat_state.model_selection = ModelSelectionState(
        current_model_id="claude-3-7-sonnet",
        current_effort_id="high",
        models=[
            ModelOption(
                id="claude-3-7-sonnet",
                name="Claude 3.7 Sonnet",
                supported_efforts=[
                    {"id": "low", "name": "Low"},
                    {"id": "high", "name": "High"},
                ],
            ),
            ModelOption(
                id="o3-mini",
                name="o3-mini",
                supported_efforts=[],
            ),
        ],
    )

    assert select.current_option == "claude-3-7-sonnet:high"
    assert select.options == [
        "claude-3-7-sonnet:low",
        "claude-3-7-sonnet:high",
        "o3-mini",
    ]

    # Select model with effort
    await select.async_select_option("claude-3-7-sonnet:low")
    coordinator.async_select_model.assert_called_with(
        "alice_linux_my_repo", "claude-3-7-sonnet", "low"
    )

    # Select model without effort
    await select.async_select_option("o3-mini")
    coordinator.async_select_model.assert_called_with(
        "alice_linux_my_repo", "o3-mini", None
    )


async def test_select_dynamic_addition(
    hass: HomeAssistant, coordinator: JunieRemoteCoordinator
) -> None:
    """Verify dynamic discovery creates select entities for new hosts."""
    entry = ConfigEntry(entry_id="test_entry")
    hass.data[DOMAIN] = {entry.entry_id: coordinator}

    added_entities: list[list[JunieRemoteModelEffortSelect]] = []
    await async_setup_select(hass, entry, lambda ents: added_entities.append(ents))

    assert len(added_entities) == 1
    assert added_entities[0][0].unique_id == "alice_linux_my_repo_model_effort"

    # Discover new host
    h2 = make_test_host(host_key="bob_macos_web", tunnel_id="tunnel-bob")
    coordinator.hosts[h2.host_key] = h2
    coordinator.async_set_updated_data(coordinator.hosts)

    assert len(added_entities) == 2
    assert added_entities[1][0].unique_id == "bob_macos_web_model_effort"


# =========================================================================
# Button Platform Tests
# =========================================================================


async def test_host_buttons(coordinator: JunieRemoteCoordinator) -> None:
    """Verify Stop, Confirm Plan, and Take Over buttons trigger coordinator actions."""
    stop_button = JunieRemoteStopButton(coordinator, "alice_linux_my_repo")
    confirm_button = JunieRemoteConfirmPlanButton(coordinator, "alice_linux_my_repo")
    takeover_button = JunieRemoteTakeOverButton(coordinator, "alice_linux_my_repo")

    assert stop_button.unique_id == "alice_linux_my_repo_stop"
    assert confirm_button.unique_id == "alice_linux_my_repo_confirm_plan"
    assert takeover_button.unique_id == "alice_linux_my_repo_take_over"

    await stop_button.async_press()
    coordinator.async_cancel.assert_called_once_with("alice_linux_my_repo")

    await confirm_button.async_press()
    coordinator.async_confirm_plan.assert_called_once_with("alice_linux_my_repo")

    await takeover_button.async_press()
    coordinator.async_kick_and_takeover.assert_called_once_with("alice_linux_my_repo")


async def test_button_dynamic_addition(
    hass: HomeAssistant, coordinator: JunieRemoteCoordinator
) -> None:
    """Verify dynamic discovery creates 3 button entities per host."""
    entry = ConfigEntry(entry_id="test_entry")
    hass.data[DOMAIN] = {entry.entry_id: coordinator}

    added_entities: list[list[Any]] = []
    await async_setup_button(hass, entry, lambda ents: added_entities.append(ents))

    assert len(added_entities) == 1
    assert len(added_entities[0]) == 3
    ids = [b.unique_id for b in added_entities[0]]
    assert "alice_linux_my_repo_stop" in ids
    assert "alice_linux_my_repo_confirm_plan" in ids
    assert "alice_linux_my_repo_take_over" in ids

    # Discover new host
    h2 = make_test_host(host_key="bob_macos_web", tunnel_id="tunnel-bob")
    coordinator.hosts[h2.host_key] = h2
    coordinator.async_set_updated_data(coordinator.hosts)

    assert len(added_entities) == 2
    assert len(added_entities[1]) == 3
    b_ids = [b.unique_id for b in added_entities[1]]
    assert "bob_macos_web_stop" in b_ids
    assert "bob_macos_web_confirm_plan" in b_ids
    assert "bob_macos_web_take_over" in b_ids


# =========================================================================
# Host Key Resolution Helper Tests
# =========================================================================


def test_extract_host_key(hass: HomeAssistant, coordinator: JunieRemoteCoordinator) -> None:
    """Verify _extract_host_key resolution from host_key, entity_ids, and fallbacks."""
    entry = ConfigEntry(entry_id="test_entry")
    hass.data[DOMAIN] = {entry.entry_id: coordinator}

    # 1. Direct host_key
    assert _extract_host_key(hass, {"host_key": "custom_host"}) == "custom_host"

    # 2. Exact match from entity_id
    assert (
        _extract_host_key(hass, {"entity_id": "sensor.alice_linux_my_repo_status"})
        == "alice_linux_my_repo"
    )
    assert (
        _extract_host_key(hass, {"entity_id": "switch.alice_linux_my_repo_brave_mode"})
        == "alice_linux_my_repo"
    )
    assert (
        _extract_host_key(hass, {"entity_id": "select.alice_linux_my_repo_model_effort"})
        == "alice_linux_my_repo"
    )
    assert (
        _extract_host_key(hass, {"entity_id": "button.alice_linux_my_repo_stop"})
        == "alice_linux_my_repo"
    )

    # 3. List entity_id
    assert (
        _extract_host_key(hass, {"entity_id": ["sensor.alice_linux_my_repo_status"]})
        == "alice_linux_my_repo"
    )

    # 4. Prefixed entity_id with integration name
    assert (
        _extract_host_key(hass, {"entity_id": "sensor.junie_remote_alice_linux_my_repo_status"})
        == "alice_linux_my_repo"
    )

    # 5. Fallback when single host exists
    assert _extract_host_key(hass, {}) == "alice_linux_my_repo"

    # 6. Failure when multiple hosts exist and none specified
    h2 = make_test_host("host_two")
    coordinator.hosts["host_two"] = h2
    with pytest.raises(ValueError, match="Could not determine target host_key"):
        _extract_host_key(hass, {})


def test_get_coordinator_for_host(hass: HomeAssistant, coordinator: JunieRemoteCoordinator) -> None:
    """Verify _get_coordinator_for_host finds the right coordinator instance."""
    entry = ConfigEntry(entry_id="test_entry")
    hass.data[DOMAIN] = {entry.entry_id: coordinator}

    coord = _get_coordinator_for_host(hass, "alice_linux_my_repo")
    assert coord is coordinator

    # Missing coordinator error
    hass.data[DOMAIN] = {}
    with pytest.raises(ValueError, match="No active Junie Remote coordinators available"):
        _get_coordinator_for_host(hass, "any_host")


# =========================================================================
# Response Payload Builder Tests
# =========================================================================


def test_build_response_payload() -> None:
    """Verify _build_response_payload formats all protocol response types."""
    # 1. Ask
    text, payload = _build_response_payload({
        "method": "ask",
        "request_id": "req-1",
        "response": "My answer",
    })
    assert text == "My answer"
    assert payload == {"method": "ask", "requestId": "req-1", "response": "My answer"}

    # 2. Choice
    text, payload = _build_response_payload({
        "method": "choice",
        "request_id": "req-2",
        "option_id": "opt-abc",
    })
    assert text == "opt-abc"
    assert payload == {"method": "choice", "requestId": "req-2", "optionId": "opt-abc"}

    # 3. Approve - allow once
    text, payload = _build_response_payload({
        "method": "approve",
        "request_id": "req-3",
        "approve": True,
    })
    assert text == "Allow once"
    assert payload == {"method": "approve", "requestId": "req-3", "approve": True}

    # 4. Approve - deny
    text, payload = _build_response_payload({
        "method": "approve",
        "request_id": "req-3",
        "approve": False,
    })
    assert text == "Deny"
    assert payload == {"method": "approve", "requestId": "req-3", "approve": False}

    # 5. Approve - always allow
    text, payload = _build_response_payload({
        "method": "approve",
        "request_id": "req-3",
        "approve": True,
        "add_to_allow_list": True,
        "option_index": 1,
    })
    assert text == "Always allow"
    assert payload == {
        "method": "approve",
        "requestId": "req-3",
        "approve": True,
        "addToAllowList": True,
        "optionIndex": 1,
    }

    # 6. Cancel / action
    text, payload = _build_response_payload({
        "method": "cancel",
        "request_id": "req-4",
    })
    assert text == "OK"
    assert payload == {"method": "cancel", "requestId": "req-4"}

    # 7. Ask-async
    text, payload = _build_response_payload({
        "method": "ask-async",
        "request_id": "req-5",
        "option_ids": ["opt-1", "opt-2"],
        "response": "summary text",
    })
    assert text == "summary text"
    assert payload == {
        "method": "ask-async",
        "requestId": "req-5",
        "optionIds": ["opt-1", "opt-2"],
        "response": "summary text",
    }

    # 8. Pre-built response_payload override
    text, payload = _build_response_payload({
        "display_text": "Custom OK",
        "response_payload": {"raw": 123},
    })
    assert text == "Custom OK"
    assert payload == {"raw": 123}


# =========================================================================
# Domain Service Tests
# =========================================================================


async def test_domain_services_registration_and_calls(
    hass: HomeAssistant, coordinator: JunieRemoteCoordinator
) -> None:
    """Verify all Junie Remote services are registered and call coordinator methods properly."""
    entry = ConfigEntry(entry_id="test_entry")
    hass.data[DOMAIN] = {entry.entry_id: coordinator}

    _async_register_services(hass)

    # 1. send_prompt
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_PROMPT,
        {"host_key": "alice_linux_my_repo", "prompt": "Run tests"},
    )
    coordinator.async_send_prompt.assert_called_with("alice_linux_my_repo", "Run tests")

    # send_prompt via entity_id
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_PROMPT,
        {"entity_id": "sensor.alice_linux_my_repo_status", "prompt": "Steer task"},
    )
    coordinator.async_send_prompt.assert_called_with("alice_linux_my_repo", "Steer task")

    # 2. send_plan_prompt
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_PLAN_PROMPT,
        {"host_key": "alice_linux_my_repo", "prompt": "Refine step 2"},
    )
    coordinator.async_send_plan_prompt.assert_called_with("alice_linux_my_repo", "Refine step 2")

    # 3. respond_request (and respond alias)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_RESPOND_REQUEST,
        {
            "host_key": "alice_linux_my_repo",
            "request_id": "req-99",
            "method": "ask",
            "response": "Yes please",
        },
    )
    coordinator.async_respond_request.assert_called_with(
        "alice_linux_my_repo",
        "Yes please",
        {"method": "ask", "requestId": "req-99", "response": "Yes please"},
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_RESPOND,
        {
            "entity_id": "sensor.alice_linux_my_repo_status",
            "request_id": "req-choice",
            "method": "choice",
            "option_id": "opt-2",
        },
    )
    coordinator.async_respond_request.assert_called_with(
        "alice_linux_my_repo",
        "opt-2",
        {"method": "choice", "requestId": "req-choice", "optionId": "opt-2"},
    )

    # 4. select_model
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SELECT_MODEL,
        {
            "host_key": "alice_linux_my_repo",
            "model_id": "claude-3-7-sonnet",
            "effort_id": "high",
        },
    )
    coordinator.async_select_model.assert_called_with(
        "alice_linux_my_repo", "claude-3-7-sonnet", "high"
    )

    # 5. kick_client
    await hass.services.async_call(
        DOMAIN,
        SERVICE_KICK_CLIENT,
        {"entity_id": "button.alice_linux_my_repo_take_over"},
    )
    coordinator.async_kick_and_takeover.assert_called_with("alice_linux_my_repo")

    # 6. confirm_plan
    await hass.services.async_call(
        DOMAIN,
        SERVICE_CONFIRM_PLAN,
        {"host_key": "alice_linux_my_repo"},
    )
    coordinator.async_confirm_plan.assert_called_with("alice_linux_my_repo")

    # 7. cancel_task and cancel alias
    await hass.services.async_call(
        DOMAIN,
        SERVICE_CANCEL_TASK,
        {"host_key": "alice_linux_my_repo"},
    )
    coordinator.async_cancel.assert_called_with("alice_linux_my_repo")

    await hass.services.async_call(
        DOMAIN,
        SERVICE_CANCEL,
        {"host_key": "alice_linux_my_repo"},
    )

    # 8. toggle_brave_mode
    await hass.services.async_call(
        DOMAIN,
        SERVICE_TOGGLE_BRAVE_MODE,
        {"host_key": "alice_linux_my_repo", "enabled": True},
    )
    coordinator.async_toggle_brave_mode.assert_called_with("alice_linux_my_repo", True)

    # Test unregistering services
    _async_unregister_services(hass)
    assert not hass.services.has_service(DOMAIN, SERVICE_SEND_PROMPT)


async def test_full_entry_setup_flow(
    hass: HomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    """Verify async_setup and async_setup_entry initialize platforms and services."""
    await async_setup(hass, {})
    assert hass.services.has_service(DOMAIN, SERVICE_SEND_PROMPT)

    mock_client = MagicMock(spec=JunieRemoteClient)
    mock_client.list_tunnels = AsyncMock(return_value=[
        make_test_host("entry_host").tunnel
    ])
    mock_client.connect_client = AsyncMock(return_value="https://test.ws")
    mock_client.close = AsyncMock()

    entry = ConfigEntry(
        entry_id="entry_123",
        data={"auth_input": "dummy_cookie"},
    )

    with patch(
        "custom_components.junie_remote.JunieRemoteClient",
        return_value=mock_client,
    ), patch(
        "custom_components.junie_remote.create_storage_driver",
        return_value=mock_storage,
    ), patch(
        "custom_components.junie_remote.coordinator.JunieTunnelSession.connect",
        new=AsyncMock(),
    ):
        success = await async_setup_entry(hass, entry)
        assert success is True
        assert entry.entry_id in hass.data[DOMAIN]

        # Verify forwarded setups for all 4 platforms
        forwarded = hass.config_entries.forwarded_setups
        assert len(forwarded) == 1
        platforms = forwarded[0][1]
        assert "sensor" in platforms
        assert "switch" in platforms
        assert "select" in platforms
        assert "button" in platforms


async def test_cleanup_and_resume_services_compat(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """Verify cleanup and resume service handlers in standalone compat mode."""
    _async_register_services(hass)
    assert hass.services.has_service(DOMAIN, SERVICE_CLEANUP_TRANSCRIPTS)
    assert hass.services.has_service(DOMAIN, SERVICE_RESUME_TRANSCRIPTS)

    entry = ConfigEntry(entry_id="entry_compat_999", data={})
    hass.config_entries.entries["entry_compat_999"] = entry

    inv = TranscriptInventory(hass)
    hass.data["junie_remote_transcript_inventory"] = inv
    await inv.async_load()

    storage = LocalTranscriptStorage(
        base_dir=tmp_path / "private",
        entry_id=entry.entry_id,
        inventory=inv,
        public_roots=[tmp_path / "www"],
    )
    coord = JunieRemoteCoordinator(hass, MagicMock(), storage, auto_connect=False)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord

    # Save a document
    doc = TranscriptDocument(
        host_key="my_host",
        tunnel=TunnelInfo(tunnel_id="tun-1"),
        chat_state=ChatSessionState(),
        connection_status="connected",
    )
    await storage.async_save_transcript(doc)
    assert len(inv.local_records(entry.entry_id)) == 3

    admin_ctx = MagicMock(user_id="admin_1", is_admin=True)
    non_admin_ctx = MagicMock(user_id="user_1", is_admin=False)

    # 1. Non-admin is rejected
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEANUP_TRANSCRIPTS,
            {"entry_id": entry.entry_id, "confirm": True},
            context=non_admin_ctx,
        )

    # 2. Admin without confirm is rejected
    with pytest.raises(HomeAssistantError, match="requires explicit confirmation"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEANUP_TRANSCRIPTS,
            {"entry_id": entry.entry_id, "confirm": False},
            context=admin_ctx,
        )

    # 3. Admin cleanup succeeds
    await hass.services.async_call(
        DOMAIN,
        SERVICE_CLEANUP_TRANSCRIPTS,
        {"entry_id": entry.entry_id, "confirm": True},
        context=admin_ctx,
    )
    assert len(inv.local_records(entry.entry_id)) == 0
    assert inv.is_paused(entry.entry_id) is True

    # 4. Admin resume succeeds
    await hass.services.async_call(
        DOMAIN,
        SERVICE_RESUME_TRANSCRIPTS,
        {"entry_id": entry.entry_id},
        context=admin_ctx,
    )
    assert inv.is_paused(entry.entry_id) is False
