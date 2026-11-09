# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Unit tests for JetBrains Junie Remote DataUpdateCoordinator and integration lifecycle."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.junie_remote import (
    DOMAIN,
    PLATFORMS,
    async_reload_entry,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.junie_remote.client import JunieRemoteClient, JunieTunnelSession
from custom_components.junie_remote.const import (
    CONF_LOCAL_STORAGE_PATH,
    CONF_STORAGE_TYPE,
    STORAGE_TYPE_LOCAL,
)
from custom_components.junie_remote.coordinator import (
    HostBridgeState,
    JunieRemoteCoordinator,
)
from custom_components.junie_remote.ha_compat import ConfigEntry, MockHomeAssistant
from custom_components.junie_remote.models import (
    ChatSessionState,
    JunieRemoteError,
    TunnelInfo,
    TunnelMetadata,
)
from custom_components.junie_remote.storage import (
    LocalTranscriptStorage,
    TranscriptResult,
)
from custom_components.junie_remote.transcript_inventory import TranscriptInventory


@pytest.fixture
def hass() -> MockHomeAssistant:
    """Fixture providing a mock HomeAssistant instance."""
    return MockHomeAssistant()


@pytest.fixture
def mock_storage(tmp_path: Path) -> LocalTranscriptStorage:
    """Fixture providing local transcript storage."""
    base = tmp_path / "transcripts"
    return LocalTranscriptStorage(
        base_dir=base,
        entry_id="entry-1",
        inventory=TranscriptInventory(MockHomeAssistant()),
    )


def make_tunnel(
    tunnel_id: str,
    user_name: str = "alice",
    os_name: str = "linux",
    repo: str = "https://github.com/org/repo.git",
    connected_clients: int = 0,
) -> TunnelInfo:
    """Helper to build TunnelInfo with metadata."""
    meta = TunnelMetadata(
        user_name=user_name,
        os_name=os_name,
        git_repo_url=repo,
        current_directory="/home/alice/repo",
    )
    return TunnelInfo(
        tunnel_id=tunnel_id,
        connected_clients=connected_clients,
        metadata=meta,
    )


# --- Tunnel Discovery & Host State Tests ---


async def test_coordinator_initial_discovery(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    """Verify coordinator polls tunnels and populates HostBridgeState with stable host_key."""
    t1 = make_tunnel("tunnel-1", user_name="alice", os_name="linux")
    t2 = make_tunnel("tunnel-2", user_name="bob", os_name="macos", repo="https://github.com/org/web.git")

    mock_client = MagicMock(spec=JunieRemoteClient)
    mock_client.list_tunnels = AsyncMock(return_value=[t1, t2])

    coordinator = JunieRemoteCoordinator(
        hass=hass,
        client=mock_client,
        storage=mock_storage,
        auto_connect=False,
    )

    data = await coordinator._async_update_data()
    assert len(data) == 2

    k1 = t1.compute_host_key()
    k2 = t2.compute_host_key()
    assert k1 in data
    assert k2 in data

    state1 = data[k1]
    assert state1.host_key == k1
    assert state1.tunnel.tunnel_id == "tunnel-1"
    assert "alice@linux" in state1.device_name
    assert state1.connection_status == "disconnected"

    # Verify to_dict serializability
    d1 = state1.to_dict()
    assert d1["host_key"] == k1
    assert d1["tunnel_id"] == "tunnel-1"
    assert "device_name" in d1


# --- Dynamic Tunnel Rebinding Tests ---


async def test_dynamic_tunnel_rebinding_on_cli_restart(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    """Verify dynamic tunnel rebinding when tunnelId changes for the same host_key."""
    t_initial = make_tunnel("tunnel-old", user_name="developer", os_name="linux", repo="https://git.corp/app")
    host_key = t_initial.compute_host_key()

    mock_client = MagicMock(spec=JunieRemoteClient)
    mock_client.list_tunnels = AsyncMock(return_value=[t_initial])

    coordinator = JunieRemoteCoordinator(
        hass=hass,
        client=mock_client,
        storage=mock_storage,
        auto_connect=False,
    )

    # Initial poll
    await coordinator._async_update_data()
    assert host_key in coordinator.hosts
    assert coordinator.hosts[host_key].tunnel.tunnel_id == "tunnel-old"

    # Simulate an active session on the old tunnel
    old_session = MagicMock(spec=JunieTunnelSession)
    old_session.dispose = AsyncMock()
    coordinator.hosts[host_key].session = old_session
    coordinator.hosts[host_key].connection_status = "connected"

    # Now Junie CLI restarts on that host with a new tunnelId!
    t_new = make_tunnel("tunnel-new-999", user_name="developer", os_name="linux", repo="https://git.corp/app")
    assert t_new.compute_host_key() == host_key
    mock_client.list_tunnels = AsyncMock(return_value=[t_new])

    # Next coordinator poll
    with patch.object(coordinator, "_async_connect_host", new=AsyncMock()) as mock_connect:
        await coordinator._async_update_data()

        # 1. Old session was disposed
        old_session.dispose.assert_awaited_once()

        # 2. Host key remains stable and identical
        assert host_key in coordinator.hosts
        state = coordinator.hosts[host_key]
        assert state.host_key == host_key

        # 3. State points to new tunnel
        assert state.tunnel.tunnel_id == "tunnel-new-999"

        # 4. Connect was triggered for the new tunnel
        mock_connect.assert_awaited_once_with(host_key)


# --- Auto-Connect & Event/Transcript Persistence Tests ---


async def test_auto_connect_and_event_transcript_persistence(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    """Verify auto_connect wires callbacks and incoming events trigger transcript saves."""
    tunnel = make_tunnel("tunnel-evt-1", user_name="charlie", os_name="linux")
    host_key = tunnel.compute_host_key()

    mock_client = MagicMock(spec=JunieRemoteClient)
    mock_client.list_tunnels = AsyncMock(return_value=[tunnel])

    coordinator = JunieRemoteCoordinator(
        hass=hass,
        client=mock_client,
        storage=mock_storage,
        auto_connect=True,
    )

    listener_called = False

    def on_update() -> None:
        nonlocal listener_called
        listener_called = True

    coordinator.async_add_listener(on_update)

    # Mock JunieTunnelSession.connect to simulate successful connection
    with patch(
        "custom_components.junie_remote.coordinator.JunieTunnelSession"
    ) as MockSessionCls:
        mock_session = MagicMock(spec=JunieTunnelSession)
        mock_session.connect = AsyncMock()
        mock_session.state = ChatSessionState()
        MockSessionCls.return_value = mock_session

        await coordinator._async_update_data()
        mock_session.connect.assert_awaited_once()

        # Capture callbacks passed to JunieTunnelSession
        _, kwargs = MockSessionCls.call_args
        status_cb = kwargs["on_status_change"]
        event_cb = kwargs["on_event"]

        # Simulate on_status_change("connected", None)
        status_cb("connected", None)
        await asyncio.sleep(0.05)

        assert coordinator.hosts[host_key].connection_status == "connected"
        assert coordinator.hosts[host_key].transcript_result is not None
        assert listener_called is True
        listener_called = False

        # Simulate incoming event: user-prompt
        chat_state = ChatSessionState(
            title="Refactor auth",
            history=[{"type": "user-prompt", "prompt": "Please review security"}],
        )
        event_cb({"type": "ready-step", "step": {"type": "user-prompt"}}, chat_state)
        await asyncio.sleep(0.05)

        assert coordinator.hosts[host_key].chat_state.title == "Refactor auth"
        res = coordinator.hosts[host_key].transcript_result
        assert res is not None
        assert "User: Please review security" in res.last_step_preview
        assert listener_called is True


# --- Offline Host Handling Tests ---


async def test_offline_host_disposes_session(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    """Verify hosts no longer in list_tunnels are marked offline and sessions disposed."""
    t1 = make_tunnel("tunnel-offline-1", user_name="dave")
    h_key = t1.compute_host_key()

    mock_client = MagicMock(spec=JunieRemoteClient)
    mock_client.list_tunnels = AsyncMock(return_value=[t1])

    coordinator = JunieRemoteCoordinator(
        hass=hass, client=mock_client, storage=mock_storage, auto_connect=False
    )
    await coordinator._async_update_data()

    mock_session = MagicMock(spec=JunieTunnelSession)
    mock_session.dispose = AsyncMock()
    coordinator.hosts[h_key].session = mock_session
    coordinator.hosts[h_key].connection_status = "connected"

    # Next poll: tunnel disappears
    mock_client.list_tunnels = AsyncMock(return_value=[])
    await coordinator._async_update_data()

    mock_session.dispose.assert_awaited_once()
    assert coordinator.hosts[h_key].session is None
    assert coordinator.hosts[h_key].connection_status == "offline"


# --- Action Helpers Tests ---


async def test_coordinator_action_helpers_success(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    """Verify coordinator action helpers invoke methods on the connected session."""
    tunnel = make_tunnel("tunnel-act-1")
    host_key = tunnel.compute_host_key()

    mock_client = MagicMock(spec=JunieRemoteClient)
    mock_client.list_tunnels = AsyncMock(return_value=[tunnel])

    coordinator = JunieRemoteCoordinator(
        hass=hass, client=mock_client, storage=mock_storage, auto_connect=False
    )
    await coordinator._async_update_data()

    mock_session = MagicMock(spec=JunieTunnelSession)
    mock_session.send_prompt = AsyncMock()
    mock_session.send_plan_prompt = AsyncMock()
    mock_session.confirm_plan = AsyncMock()
    mock_session.cancel = AsyncMock()
    mock_session.toggle_brave_mode = AsyncMock()
    mock_session.select_model = AsyncMock()
    mock_session.send_response = AsyncMock()
    mock_session.dispose = AsyncMock()

    coordinator.hosts[host_key].session = mock_session
    coordinator.hosts[host_key].connection_status = "connected"

    # Test send_prompt
    await coordinator.async_send_prompt(host_key, "Hello Junie")
    mock_session.send_prompt.assert_awaited_once_with("Hello Junie")

    # Test send_plan_prompt
    await coordinator.async_send_plan_prompt(host_key, "Plan revision")
    mock_session.send_plan_prompt.assert_awaited_once_with("Plan revision")

    # Test confirm_plan
    await coordinator.async_confirm_plan(host_key)
    mock_session.confirm_plan.assert_awaited_once()

    # Test cancel
    await coordinator.async_cancel(host_key)
    mock_session.cancel.assert_awaited_once()

    # Test toggle_brave_mode
    await coordinator.async_toggle_brave_mode(host_key, True)
    mock_session.toggle_brave_mode.assert_awaited_once_with(True)

    # Test select_model
    await coordinator.async_select_model(host_key, "claude-3-7-sonnet", "high")
    mock_session.select_model.assert_awaited_once_with("claude-3-7-sonnet", "high")

    # Test respond_request
    payload = {"confirmed": True}
    await coordinator.async_respond_request(host_key, "Confirmed", payload)
    mock_session.send_response.assert_awaited_once_with("Confirmed", payload)

    # Test kick_and_takeover
    with patch.object(coordinator, "_async_connect_host", new=AsyncMock()) as mock_connect:
        await coordinator.async_kick_and_takeover(host_key)
        mock_connect.assert_awaited_once_with(host_key, kick=True)

    # Test async_shutdown
    await coordinator.async_shutdown()
    mock_session.dispose.assert_awaited_once()
    assert coordinator.hosts[host_key].session is None


async def test_coordinator_action_helpers_errors(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    """Verify coordinator action helpers raise JunieRemoteError on invalid or disconnected host."""
    coordinator = JunieRemoteCoordinator(
        hass=hass,
        client=MagicMock(spec=JunieRemoteClient),
        storage=mock_storage,
        auto_connect=False,
    )

    # Host not found
    with pytest.raises(JunieRemoteError, match="not found"):
        await coordinator.async_send_prompt("unknown_host", "test")

    # Host exists but disconnected
    tunnel = make_tunnel("tunnel-err-1")
    h_key = tunnel.compute_host_key()
    coordinator.hosts[h_key] = HostBridgeState(
        host_key=h_key, tunnel=tunnel, connection_status="disconnected"
    )

    with pytest.raises(JunieRemoteError, match="not connected"):
        await coordinator.async_send_prompt(h_key, "test")


async def test_coordinator_serializes_transcript_saves_per_host(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    """Keep a slow older save from completing after and replacing a newer snapshot."""
    tunnel = make_tunnel("tunnel-save-order")
    host_key = tunnel.compute_host_key()
    coordinator = JunieRemoteCoordinator(
        hass=hass,
        client=MagicMock(spec=JunieRemoteClient),
        storage=mock_storage,
        auto_connect=False,
    )
    state = HostBridgeState(
        host_key=host_key,
        tunnel=tunnel,
        connection_status="connected",
    )
    coordinator.hosts[host_key] = state
    state.chat_state.history.append({"type": "user-prompt", "prompt": "older"})

    first_save_started = asyncio.Event()
    release_first_save = asyncio.Event()
    started: list[str] = []
    completed: list[str] = []

    async def save_transcript(doc: Any) -> TranscriptResult:
        prompt = doc.chat_state.history[-1]["prompt"]
        started.append(prompt)
        if prompt == "older":
            first_save_started.set()
            await release_first_save.wait()
        completed.append(prompt)
        return TranscriptResult(
            json_url=f"https://example.test/{prompt}.json",
            md_url=f"https://example.test/{prompt}.md",
            updated_at=doc.updated_at,
            last_step_preview=prompt,
        )

    with patch.object(mock_storage, "async_save_transcript", new=save_transcript):
        first_save = asyncio.create_task(coordinator._async_save_and_notify(host_key))
        await first_save_started.wait()
        state.chat_state.history.append({"type": "user-prompt", "prompt": "newer"})
        second_save = asyncio.create_task(coordinator._async_save_and_notify(host_key))
        await asyncio.sleep(0)

        assert started == ["older"]

        release_first_save.set()
        await asyncio.gather(first_save, second_save)

    assert completed == ["older", "newer"]
    assert state.transcript_result is not None
    assert state.transcript_result.json_url.endswith("/newer.json")


# --- Integration Setup & Unload Lifecycle Tests ---


async def test_async_setup_registers_static_path(hass: MockHomeAssistant) -> None:
    """Verify async_setup registers frontend directory as a static path."""
    res = await async_setup(hass, {})
    assert res is True
    assert len(hass.http.registered_paths) >= 1
    reg = hass.http.registered_paths[0]
    assert reg["url_path"] == "/junie_remote"
    assert "frontend" in reg["path"]


async def test_async_setup_auto_registers_lovelace_resource_when_running(
    hass: MockHomeAssistant,
) -> None:
    """Verify async_setup auto-registers the Lovelace card resource if running."""
    from custom_components.junie_remote.ha_compat import MockLovelace

    hass.state = "RUNNING"
    mock_lovelace = MockLovelace()
    hass.data["lovelace"] = mock_lovelace

    res = await async_setup(hass, {})
    assert res is True

    items = mock_lovelace.resources.async_items()
    assert len(items) == 1
    assert items[0]["url"].startswith("/junie_remote/junie-remote-card.js?v=")
    assert items[0]["type"] == "module"


async def test_async_setup_auto_registers_lovelace_resource_on_event(
    hass: MockHomeAssistant,
) -> None:
    """Verify async_setup registers resource when EVENT_HOMEASSISTANT_STARTED fires."""
    from custom_components.junie_remote.ha_compat import (
        EVENT_HOMEASSISTANT_STARTED,
        MockLovelace,
    )

    hass.state = "NOT_RUNNING"
    mock_lovelace = MockLovelace()
    hass.data["lovelace"] = mock_lovelace

    res = await async_setup(hass, {})
    assert res is True
    # Not registered yet
    assert len(mock_lovelace.resources.async_items()) == 0

    # Fire startup event
    await hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    items = mock_lovelace.resources.async_items()
    assert len(items) == 1
    assert items[0]["url"].startswith("/junie_remote/junie-remote-card.js?v=")


async def test_async_setup_does_not_duplicate_existing_lovelace_resource(
    hass: MockHomeAssistant,
) -> None:
    """Verify existing Lovelace card resource is not duplicated."""
    from custom_components.junie_remote.ha_compat import MockLovelace

    hass.state = "RUNNING"
    mock_lovelace = MockLovelace()
    await mock_lovelace.resources.async_create_item({
        "url": "/junie_remote/junie-remote-card.js?v=0.1.0",
        "type": "module",
    })
    hass.data["lovelace"] = mock_lovelace

    res = await async_setup(hass, {})
    assert res is True

    items = mock_lovelace.resources.async_items()
    assert len(items) == 1
    assert items[0]["url"] == "/junie_remote/junie-remote-card.js?v=0.1.0"


async def test_async_setup_and_unload_entry_lifecycle(hass: MockHomeAssistant) -> None:
    """Verify async_setup_entry and async_unload_entry full lifecycle."""
    entry = ConfigEntry(
        entry_id="lifecycle_entry_1",
        domain=DOMAIN,
        title="JetBrains Junie Remote",
        data={
            "auth_input": "SESSION=sess_1; XSRF-TOKEN=tok_1",
            "base_url": "https://junie.jetbrains.com",
            CONF_STORAGE_TYPE: STORAGE_TYPE_LOCAL,
            CONF_LOCAL_STORAGE_PATH: "www/junie_remote",
        },
        options={},
    )
    hass.config_entries.entries[entry.entry_id] = entry

    tunnel = make_tunnel("tunnel-life-1", user_name="frank")
    with patch(
        "custom_components.junie_remote.JunieRemoteClient.list_tunnels",
        new=AsyncMock(return_value=[tunnel]),
    ), patch(
        "custom_components.junie_remote.coordinator.JunieTunnelSession.connect",
        new=AsyncMock(),
    ):
        setup_res = await async_setup_entry(hass, entry)
        assert setup_res is True

        # Check coordinator stored in hass.data
        assert DOMAIN in hass.data
        assert entry.entry_id in hass.data[DOMAIN]
        coord: JunieRemoteCoordinator = hass.data[DOMAIN][entry.entry_id]
        assert isinstance(coord, JunieRemoteCoordinator)
        assert tunnel.compute_host_key() in coord.hosts

        # Check platform setups forwarded
        assert len(hass.config_entries.forwarded_setups) == 1
        forwarded_entry, platforms = hass.config_entries.forwarded_setups[0]
        assert forwarded_entry == entry
        assert set(platforms) == set(PLATFORMS)

        # Test reload helper
        with patch.object(
            hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
        ) as mock_reload:
            await async_reload_entry(hass, entry)
            mock_reload.assert_awaited_once_with(entry.entry_id)

        # Test unload entry
        unload_res = await async_unload_entry(hass, entry)
        assert unload_res is True
        assert entry.entry_id not in hass.data[DOMAIN]
        assert len(hass.config_entries.unloaded_platforms) == 1


@pytest.mark.parametrize("failure", [False, RuntimeError("platform failed")])
async def test_failed_platform_unload_preserves_entry_and_services(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage, failure: Any, caplog: Any
) -> None:
    entry = ConfigEntry(entry_id="one", domain=DOMAIN, title="one", data={}, options={})
    client = MagicMock(spec=JunieRemoteClient)
    client.close = AsyncMock()
    coordinator = JunieRemoteCoordinator(hass, client, mock_storage, auto_connect=False)
    hass.data[DOMAIN] = {entry.entry_id: coordinator}
    await async_setup(hass, {})
    unload = (
        AsyncMock(side_effect=failure)
        if isinstance(failure, Exception)
        else AsyncMock(return_value=failure)
    )
    with patch.object(hass.config_entries, "async_unload_platforms", unload):
        assert await async_unload_entry(hass, entry) is False
    assert hass.data[DOMAIN][entry.entry_id] is coordinator
    client.close.assert_not_awaited()
    assert hass.services.has_service(DOMAIN, "send_prompt")
    if isinstance(failure, Exception):
        assert "platform failed" in caplog.text


async def test_unload_retry_and_last_entry_services(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    entries = [
        ConfigEntry(entry_id=name, domain=DOMAIN, title=name, data={}, options={})
        for name in ("one", "two")
    ]
    clients = [MagicMock(spec=JunieRemoteClient) for _ in entries]
    for client in clients:
        client.close = AsyncMock()
    coordinators = [
        JunieRemoteCoordinator(hass, client, mock_storage, auto_connect=False)
        for client in clients
    ]
    hass.data[DOMAIN] = {entry.entry_id: coord for entry, coord in zip(entries, coordinators)}
    await async_setup(hass, {})
    clients[0].close.side_effect = [RuntimeError("close failed"), None]
    assert await async_unload_entry(hass, entries[0]) is False
    assert hass.data[DOMAIN]["one"] is coordinators[0]
    assert hass.services.has_service(DOMAIN, "send_prompt")
    assert await async_unload_entry(hass, entries[0]) is True
    assert hass.services.has_service(DOMAIN, "send_prompt")
    assert await async_unload_entry(hass, entries[1]) is True
    assert not hass.services.has_service(DOMAIN, "send_prompt")
    assert await async_unload_entry(hass, entries[1]) is True


async def test_shutdown_drains_thread_and_queued_saves_despite_cancellation(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    tunnel = make_tunnel("thread-save")
    key = tunnel.compute_host_key()
    coordinator = JunieRemoteCoordinator(
        hass, MagicMock(spec=JunieRemoteClient), mock_storage, auto_connect=False
    )
    state = HostBridgeState(host_key=key, tunnel=tunnel, connection_status="connected")
    coordinator.hosts[key] = state
    state.chat_state.title = "old"
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original_write = LocalTranscriptStorage._write_owned
    first = True

    def blocked_write(*args: Any, **kwargs: Any) -> Path:
        nonlocal first
        if first:
            first = False
            loop.call_soon_threadsafe(started.set)
            if not release.wait(10):
                raise TimeoutError("test did not release worker")
        return original_write(*args, **kwargs)

    notifications: list[str] = []
    coordinator.async_add_listener(lambda: notifications.append("updated"))
    with patch.object(
        LocalTranscriptStorage, "_write_owned", staticmethod(blocked_write)
    ):
        coordinator._schedule_save_and_notify(key)
        try:
            await asyncio.wait_for(started.wait(), 2)
            state.chat_state.title = "new"
            coordinator._schedule_save_and_notify(key)
            shutdown = asyncio.create_task(coordinator.async_shutdown())
            await asyncio.sleep(0)
            assert not shutdown.done()
            shutdown.cancel()
            with pytest.raises(asyncio.CancelledError):
                await shutdown
            again = asyncio.create_task(coordinator.async_shutdown())
            await asyncio.sleep(0)
            assert not again.done()
            coordinator._on_session_status_change(key, "disconnected", None)
        finally:
            release.set()
        await asyncio.wait_for(again, 2)
    assert (
        json.loads(
            (mock_storage.base_dir / "entry-1" / key / "latest.json").read_text()
        )["metadata"]["title"]
        == "new"
    )
    assert notifications == []
    await coordinator.async_shutdown()


async def test_shutdown_waits_for_inflight_refresh_and_connect(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    tunnel = make_tunnel("connecting")
    client = MagicMock(spec=JunieRemoteClient)
    client.list_tunnels = AsyncMock(return_value=[tunnel])
    coordinator = JunieRemoteCoordinator(hass, client, mock_storage)
    entered, release = asyncio.Event(), asyncio.Event()
    session = MagicMock(spec=JunieTunnelSession)

    async def connect() -> None:
        entered.set()
        await release.wait()

    session.connect = connect
    session.dispose = AsyncMock()
    with patch(
        "custom_components.junie_remote.coordinator.JunieTunnelSession", return_value=session
    ):
        refresh = asyncio.create_task(coordinator._async_update_data())
        await asyncio.wait_for(entered.wait(), 2)
        shutdown = asyncio.create_task(coordinator.async_shutdown())
        await asyncio.sleep(0)
        assert not shutdown.done()
        session.dispose.assert_not_awaited()
        release.set()
        await asyncio.wait_for(asyncio.gather(refresh, shutdown), 2)
    session.dispose.assert_awaited_once()
    assert coordinator.hosts[tunnel.compute_host_key()].session is None


async def test_setup_wont_replace_coordinator_after_failed_teardown(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    entry = ConfigEntry(entry_id="old", domain=DOMAIN, title="old", data={}, options={})
    client = MagicMock(spec=JunieRemoteClient)
    client.close = AsyncMock(side_effect=RuntimeError("close failed"))
    coordinator = JunieRemoteCoordinator(hass, client, mock_storage, auto_connect=False)
    hass.data[DOMAIN] = {entry.entry_id: coordinator}
    assert await async_unload_entry(hass, entry) is False
    with patch("custom_components.junie_remote.JunieRemoteClient") as new_client:
        new_client.return_value.list_tunnels = AsyncMock(return_value=[])
        with pytest.raises(RuntimeError, match="close failed"):
            await async_setup_entry(hass, entry)
        new_client.assert_not_called()
    assert hass.data[DOMAIN][entry.entry_id] is coordinator


async def test_shutdown_drains_multiple_hosts_disposal_callbacks_and_failures(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage, caplog: Any
) -> None:
    client = MagicMock(spec=JunieRemoteClient)
    coordinator = JunieRemoteCoordinator(hass, client, mock_storage, auto_connect=False)
    tunnels = [make_tunnel("one", user_name="one"), make_tunnel("two", user_name="two")]
    keys = [t.compute_host_key() for t in tunnels]
    for key, tunnel in zip(keys, tunnels):
        coordinator.hosts[key] = HostBridgeState(host_key=key, tunnel=tunnel)
    started = {key: asyncio.Event() for key in keys}
    release = asyncio.Event()
    calls: list[str] = []

    async def save(doc: Any) -> TranscriptResult:
        calls.append(doc.host_key)
        started[doc.host_key].set()
        await release.wait()
        if doc.host_key == keys[0]:
            raise RuntimeError("write failed")
        return TranscriptResult("json", "md", doc.updated_at, "preview")

    session = MagicMock(spec=JunieTunnelSession)

    async def dispose() -> None:
        coordinator._on_session_status_change(keys[0], "disconnected", None)
        coordinator._on_session_event(keys[0], {}, ChatSessionState(title="late"))

    session.dispose = AsyncMock(side_effect=dispose)
    coordinator.hosts[keys[0]].session = session
    with patch.object(mock_storage, "async_save_transcript", save):
        for key in keys:
            coordinator._schedule_save_and_notify(key)
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), 2)
        first = asyncio.create_task(coordinator.async_shutdown())
        second = asyncio.create_task(coordinator.async_shutdown())
        await asyncio.sleep(0)
        assert not first.done() and not second.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 2)
    assert calls == keys
    assert coordinator.hosts[keys[0]].chat_state.title != "late"
    assert "write failed" in caplog.text
    session.dispose.assert_awaited_once()


async def test_unload_disposal_failure_is_retryable(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage, caplog: Any
) -> None:
    entry = ConfigEntry(entry_id="one", domain=DOMAIN, title="one", data={}, options={})
    client = MagicMock(spec=JunieRemoteClient)
    client.close = AsyncMock()
    coordinator = JunieRemoteCoordinator(hass, client, mock_storage, auto_connect=False)
    tunnel = make_tunnel("one")
    key = tunnel.compute_host_key()
    session = MagicMock(spec=JunieTunnelSession)
    session.dispose = AsyncMock(side_effect=[RuntimeError("dispose failed"), None])
    coordinator.hosts[key] = HostBridgeState(host_key=key, tunnel=tunnel, session=session)
    hass.data[DOMAIN] = {entry.entry_id: coordinator}
    await async_setup(hass, {})
    assert await async_unload_entry(hass, entry) is False
    assert hass.data[DOMAIN][entry.entry_id] is coordinator
    assert coordinator.hosts[key].session is session
    client.close.assert_not_awaited()
    assert "dispose failed" in caplog.text
    assert await async_unload_entry(hass, entry) is True
    assert session.dispose.await_count == 2
    client.close.assert_awaited_once()


async def test_reload_waits_for_old_write_before_new_coordinator_saves(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    entry = ConfigEntry(entry_id="reload", domain=DOMAIN, title="reload", data={}, options={})
    client = MagicMock(spec=JunieRemoteClient)
    client.close = AsyncMock()
    old = JunieRemoteCoordinator(hass, client, mock_storage, auto_connect=False)
    tunnel = make_tunnel("reload")
    key = tunnel.compute_host_key()
    old.hosts[key] = HostBridgeState(
        host_key=key, tunnel=tunnel, chat_state=ChatSessionState(title="old")
    )
    hass.data[DOMAIN] = {entry.entry_id: old}
    started, release = asyncio.Event(), asyncio.Event()
    original_save = mock_storage.async_save_transcript

    async def delayed_save(doc: Any) -> TranscriptResult:
        started.set()
        await release.wait()
        return await original_save(doc)

    with patch.object(mock_storage, "async_save_transcript", delayed_save):
        old._schedule_save_and_notify(key)
        await asyncio.wait_for(started.wait(), 2)
        unload = asyncio.create_task(async_unload_entry(hass, entry))
        await asyncio.sleep(0)
        assert not unload.done()
        client.close.assert_not_awaited()
        release.set()
        assert await asyncio.wait_for(unload, 2)
    new = JunieRemoteCoordinator(
        hass, MagicMock(spec=JunieRemoteClient), mock_storage, auto_connect=False
    )
    new.hosts[key] = HostBridgeState(
        host_key=key, tunnel=tunnel, chat_state=ChatSessionState(title="new")
    )
    new._schedule_save_and_notify(key)
    await new.async_shutdown()
    old._on_session_event(key, {}, ChatSessionState(title="stale"))
    await old.async_shutdown()
    assert (
        json.loads(
            (mock_storage.base_dir / "entry-1" / key / "latest.json").read_text()
        )["metadata"]["title"]
        == "new"
    )


async def test_cancelled_refresh_still_drains_inflight_list_before_close(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    started, release = asyncio.Event(), asyncio.Event()
    client = MagicMock(spec=JunieRemoteClient)

    async def list_tunnels() -> list[TunnelInfo]:
        started.set()
        await release.wait()
        return [make_tunnel("late")]

    client.list_tunnels = list_tunnels
    coordinator = JunieRemoteCoordinator(hass, client, mock_storage)
    refresh = asyncio.create_task(coordinator._async_update_data())
    await asyncio.wait_for(started.wait(), 2)
    refresh.cancel()
    with pytest.raises(asyncio.CancelledError):
        await refresh
    shutdown = asyncio.create_task(coordinator.async_shutdown())
    await asyncio.sleep(0)
    assert not shutdown.done()
    release.set()
    await asyncio.wait_for(shutdown, 2)
    assert coordinator.hosts == {}


async def test_setup_retries_failed_platform_unload_before_replacement(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    entry = ConfigEntry(entry_id="retry", domain=DOMAIN, title="retry", data={}, options={})
    client = MagicMock(spec=JunieRemoteClient)
    client.close = AsyncMock()
    old = JunieRemoteCoordinator(hass, client, mock_storage, auto_connect=False)
    hass.data[DOMAIN] = {entry.entry_id: old}
    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new=AsyncMock(side_effect=[False, True, True]),
    ):
        assert await async_unload_entry(hass, entry) is False
        client.close.assert_not_awaited()
        with patch("custom_components.junie_remote.JunieRemoteClient") as new_client:
            new_client.return_value.list_tunnels = AsyncMock(return_value=[])
            new_client.return_value.close = AsyncMock()
            assert await async_setup_entry(hass, entry) is True
        client.close.assert_awaited_once()
        assert hass.data[DOMAIN][entry.entry_id] is not old
        assert await async_unload_entry(hass, entry) is True


async def test_cancelled_inner_shutdown_retry_drains_thread_and_queued_saves(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    tunnel = make_tunnel("cancel-inner")
    key = tunnel.compute_host_key()
    coordinator = JunieRemoteCoordinator(
        hass, MagicMock(spec=JunieRemoteClient), mock_storage, auto_connect=False
    )
    state = HostBridgeState(host_key=key, tunnel=tunnel, chat_state=ChatSessionState(title="old"))
    coordinator.hosts[key] = state
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original_write = LocalTranscriptStorage._write_owned
    first = True

    def blocked_write(*args: Any, **kwargs: Any) -> Path:
        nonlocal first
        if first:
            first = False
            loop.call_soon_threadsafe(started.set)
            if not release.wait(10):
                raise TimeoutError("test did not release worker")
        return original_write(*args, **kwargs)

    retry = None
    with patch.object(
        LocalTranscriptStorage, "_write_owned", staticmethod(blocked_write)
    ):
        coordinator._schedule_save_and_notify(key)
        try:
            await asyncio.wait_for(started.wait(), 2)
            state.chat_state.title = "new"
            coordinator._schedule_save_and_notify(key)
            shutdown = asyncio.create_task(coordinator.async_shutdown())
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert coordinator._shutdown_task is not None
            coordinator._shutdown_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await shutdown
            retry = asyncio.create_task(coordinator.async_shutdown())
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(retry), 0.05)
        finally:
            release.set()
            if retry is not None:
                await asyncio.gather(retry, return_exceptions=True)
    assert (
        json.loads(
            (mock_storage.base_dir / "entry-1" / key / "latest.json").read_text()
        )["metadata"]["title"]
        == "new"
    )


async def test_save_and_refresh_are_tracked_by_hass_until_finished(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    tunnel = make_tunnel("tracked")
    key = tunnel.compute_host_key()
    started_save, started_refresh, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    client = MagicMock(spec=JunieRemoteClient)

    async def list_tunnels() -> list[TunnelInfo]:
        started_refresh.set()
        await release.wait()
        return []

    async def save(doc: Any) -> TranscriptResult:
        started_save.set()
        await release.wait()
        return TranscriptResult("json", "md", doc.updated_at, "preview")

    client.list_tunnels = list_tunnels
    coordinator = JunieRemoteCoordinator(hass, client, mock_storage, auto_connect=False)
    coordinator.hosts[key] = HostBridgeState(host_key=key, tunnel=tunnel)
    with patch.object(mock_storage, "async_save_transcript", save):
        coordinator._schedule_save_and_notify(key)
        refresh = asyncio.create_task(coordinator._async_update_data())
        try:
            await asyncio.wait_for(asyncio.gather(started_save.wait(), started_refresh.wait()), 2)
            assert coordinator._save_tasks <= set(hass._tasks)
            assert coordinator._producer_tasks <= set(hass._tasks)
            assert coordinator._save_tasks and coordinator._producer_tasks
            assert all(not task.done() for task in hass._tasks)
        finally:
            release.set()
            await asyncio.gather(refresh, return_exceptions=True)
            await coordinator.async_shutdown()


async def test_closing_coordinator_rejects_services(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    coordinator = JunieRemoteCoordinator(
        hass, MagicMock(spec=JunieRemoteClient), mock_storage, auto_connect=False
    )
    tunnel = make_tunnel("closing")
    key = tunnel.compute_host_key()
    session = MagicMock(spec=JunieTunnelSession)
    session.dispose = AsyncMock()
    session.send_prompt = AsyncMock()
    coordinator.hosts[key] = HostBridgeState(
        host_key=key, tunnel=tunnel, session=session, connection_status="connected"
    )
    coordinator._closing = True
    with pytest.raises(JunieRemoteError, match="shutting down"):
        await coordinator.async_send_prompt(key, "hello")
    with pytest.raises(JunieRemoteError, match="shutting down"):
        await coordinator.async_kick_and_takeover(key)
    session.send_prompt.assert_not_awaited()
    await coordinator.async_shutdown()


@pytest.mark.parametrize("tracked_set_name", ["_producer_tasks", "_save_tasks"])
async def test_shutdown_prunes_done_tasks_before_done_callbacks(
    hass: MockHomeAssistant,
    mock_storage: LocalTranscriptStorage,
    tracked_set_name: str,
) -> None:
    coordinator = JunieRemoteCoordinator(
        hass, MagicMock(spec=JunieRemoteClient), mock_storage, auto_connect=False
    )

    async def completed() -> None:
        return None

    task = asyncio.create_task(completed())
    await task
    tracked_tasks = getattr(coordinator, tracked_set_name)
    tracked_tasks.add(task)
    task.add_done_callback(tracked_tasks.discard)

    await coordinator._async_shutdown_inner()

    assert not tracked_tasks


@pytest.mark.parametrize("tracked_set_name", ["_producer_tasks", "_save_tasks"])
async def test_shutdown_handles_eagerly_completed_hass_tasks(
    hass: MockHomeAssistant,
    mock_storage: LocalTranscriptStorage,
    monkeypatch: pytest.MonkeyPatch,
    tracked_set_name: str,
) -> None:
    coordinator = JunieRemoteCoordinator(
        hass, MagicMock(spec=JunieRemoteClient), mock_storage, auto_connect=False
    )
    loop = asyncio.get_running_loop()

    def create_eager_task(coro: Any, name: str | None = None) -> asyncio.Task[Any]:
        task = asyncio.eager_task_factory(loop, coro, name=name)
        hass._tasks.append(task)
        return task

    monkeypatch.setattr(hass, "async_create_task", create_eager_task)

    async def completed() -> None:
        return None

    tracked_tasks = getattr(coordinator, tracked_set_name)
    if tracked_set_name == "_producer_tasks":
        task = coordinator._track_task(completed(), tracked_tasks, "Test producer")
    else:
        work = asyncio.create_task(completed())
        await work
        task = coordinator._track_task(
            coordinator._async_wait_for_save(work), tracked_tasks, "Test save waiter"
        )

    assert task.done()
    await coordinator._async_shutdown_inner()

    assert not tracked_tasks


async def test_cancelled_inner_unload_is_failure_and_retry_drains_refresh(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    entry = ConfigEntry(
        entry_id="cancel-unload", domain=DOMAIN, title="cancel", data={}, options={}
    )
    started, release = asyncio.Event(), asyncio.Event()
    client = MagicMock(spec=JunieRemoteClient)
    client.close = AsyncMock()

    async def list_tunnels() -> list[TunnelInfo]:
        started.set()
        await release.wait()
        return []

    client.list_tunnels = list_tunnels
    coordinator = JunieRemoteCoordinator(hass, client, mock_storage, auto_connect=False)
    hass.data[DOMAIN] = {entry.entry_id: coordinator}
    await async_setup(hass, {})
    refresh = asyncio.create_task(coordinator._async_update_data())
    retry = None
    try:
        await asyncio.wait_for(started.wait(), 2)
        unload = asyncio.create_task(async_unload_entry(hass, entry))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert coordinator._shutdown_task is not None
        coordinator._shutdown_task.cancel()
        assert await unload is False
        assert hass.data[DOMAIN][entry.entry_id] is coordinator
        assert hass.services.has_service(DOMAIN, "send_prompt")
        client.close.assert_not_awaited()
        retry = asyncio.create_task(async_unload_entry(hass, entry))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(retry), 0.05)
        client.close.assert_not_awaited()
    finally:
        release.set()
        await asyncio.gather(refresh, return_exceptions=True)
        if retry is not None:
            await asyncio.gather(retry, return_exceptions=True)
    assert retry is not None and retry.result() is True
    client.close.assert_awaited_once()


@pytest.mark.parametrize("cancel_work", [False, True])
async def test_cancelled_save_waits_for_thread_before_next_save_and_shutdown(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage, cancel_work: bool
) -> None:
    tunnel = make_tunnel("cancel-save")
    key = tunnel.compute_host_key()
    coordinator = JunieRemoteCoordinator(
        hass, MagicMock(spec=JunieRemoteClient), mock_storage, auto_connect=False
    )
    state = HostBridgeState(host_key=key, tunnel=tunnel, chat_state=ChatSessionState(title="old"))
    coordinator.hosts[key] = state
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original_write = LocalTranscriptStorage._write_owned
    first = True

    def blocked_write(*args: Any, **kwargs: Any) -> Path:
        nonlocal first
        if first:
            first = False
            loop.call_soon_threadsafe(started.set)
            if not release.wait(10):
                raise TimeoutError("test did not release worker")
        return original_write(*args, **kwargs)

    shutdown = None
    with patch.object(
        LocalTranscriptStorage, "_write_owned", staticmethod(blocked_write)
    ):
        coordinator._schedule_save_and_notify(key)
        try:
            await asyncio.wait_for(started.wait(), 2)
            tracked = next(iter(coordinator._save_tasks))
            save = next(iter(coordinator._save_work_tasks)) if cancel_work else tracked
            save.cancel()
            await asyncio.sleep(0)
            save.cancel()
            await asyncio.sleep(0)
            assert not tracked.done()
            assert tracked in hass._tasks
            state.chat_state.title = "new"
            coordinator._schedule_save_and_notify(key)
            shutdown = asyncio.create_task(coordinator.async_shutdown())
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(shutdown), 0.05)
        finally:
            release.set()
            if shutdown is not None:
                await asyncio.gather(shutdown, return_exceptions=True)
    assert shutdown is not None and shutdown.result() is None
    assert (
        json.loads(
            (mock_storage.base_dir / "entry-1" / key / "latest.json").read_text()
        )["metadata"]["title"]
        == "new"
    )


async def test_cancelled_queued_save_is_still_drained(
    hass: MockHomeAssistant, mock_storage: LocalTranscriptStorage
) -> None:
    tunnel = make_tunnel("queued")
    key = tunnel.compute_host_key()
    coordinator = JunieRemoteCoordinator(
        hass, MagicMock(spec=JunieRemoteClient), mock_storage, auto_connect=False
    )
    state = HostBridgeState(host_key=key, tunnel=tunnel, chat_state=ChatSessionState(title="old"))
    coordinator.hosts[key] = state
    started, release = asyncio.Event(), asyncio.Event()
    original_save = mock_storage.async_save_transcript

    async def blocked_save(doc: Any) -> TranscriptResult:
        started.set()
        await release.wait()
        return await original_save(doc)

    with patch.object(mock_storage, "async_save_transcript", blocked_save):
        coordinator._schedule_save_and_notify(key)
        try:
            await asyncio.wait_for(started.wait(), 2)
            existing = set(coordinator._save_tasks)
            state.chat_state = ChatSessionState(title="new")
            coordinator._schedule_save_and_notify(key)
            queued = (coordinator._save_tasks - existing).pop()
            queued.cancel()
        finally:
            release.set()
            await coordinator.async_shutdown()
    assert (
        json.loads(
            (mock_storage.base_dir / "entry-1" / key / "latest.json").read_text()
        )["metadata"]["title"]
        == "new"
    )
