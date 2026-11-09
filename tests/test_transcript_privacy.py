# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Entry wiring for private local transcripts, legacy retention and multi-entry use."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.junie_remote import async_setup_entry, async_unload_entry
from custom_components.junie_remote.client import JunieRemoteClient
from custom_components.junie_remote.const import CONF_LOCAL_STORAGE_PATH, DOMAIN
from custom_components.junie_remote.ha_compat import ConfigEntry, MockHomeAssistant
from custom_components.junie_remote.models import ChatSessionState, TunnelInfo, TunnelMetadata
from custom_components.junie_remote.storage import (
    LocalTranscriptStorage,
    TranscriptDocument,
    TranscriptNotFoundError,
)
from custom_components.junie_remote.transcript_http import async_register_transcript_view
from custom_components.junie_remote.transcript_inventory import INVENTORY_HASS_KEY


@pytest.fixture
def hass(tmp_path: Path) -> MockHomeAssistant:
    instance = MockHomeAssistant()
    instance.config.config_dir = str(tmp_path)
    return instance


def doc(host: str = "h") -> TranscriptDocument:
    tunnel = TunnelInfo(
        tunnel_id="t", connected_clients=0, metadata=TunnelMetadata(user_name="u", os_name="o")
    )
    return TranscriptDocument.build(host, tunnel, ChatSessionState(title="secret"), "connected")


async def setup(hass: MockHomeAssistant, entry_id: str, **data: Any) -> Any:
    client = MagicMock(spec=JunieRemoteClient)
    client.list_tunnels = AsyncMock(return_value=[])
    client.close = AsyncMock()
    entry = ConfigEntry(entry_id=entry_id, data={"auth_input": "x", **data})
    hass.config_entries.entries[entry_id] = entry
    with patch("custom_components.junie_remote.JunieRemoteClient", return_value=client):
        assert await async_setup_entry(hass, entry)
    return entry


async def test_setup_uses_private_default_outside_www_and_never_serves_local(
    hass: MockHomeAssistant, tmp_path: Path
) -> None:
    entry = await setup(hass, "e1")
    storage = hass.data[DOMAIN][entry.entry_id].storage
    assert isinstance(storage, LocalTranscriptStorage)
    assert storage.base_dir == tmp_path / "junie_remote" / "transcripts"
    result = await storage.async_save_transcript(doc())
    assert result.json_url.startswith(f"/api/junie_remote/transcripts/{entry.entry_id}/h/json")
    assert not (tmp_path / "www").exists()
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written and all((tmp_path / "junie_remote") in p.parents for p in written)


async def test_legacy_public_copies_are_retained_with_a_warning(
    hass: MockHomeAssistant, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    legacy = tmp_path / "www" / "junie_remote" / "old_host"
    legacy.mkdir(parents=True)
    (legacy / "latest.json").write_text("legacy secret")
    (legacy / "latest.md").write_text("legacy md")
    caplog.set_level(logging.WARNING)
    entry = await setup(hass, "e1", **{CONF_LOCAL_STORAGE_PATH: "www/junie_remote"})
    storage = hass.data[DOMAIN][entry.entry_id].storage
    # the legacy path is public, so the private default is used instead
    assert storage.base_dir == tmp_path / "junie_remote" / "transcripts"
    assert storage.public_path_fallback == "www/junie_remote"
    await storage.async_save_transcript(doc("old_host"))
    assert (legacy / "latest.json").read_text() == "legacy secret"
    assert (legacy / "latest.md").read_text() == "legacy md"
    assert sorted(p.name for p in legacy.iterdir()) == ["latest.json", "latest.md"]
    text = caplog.text
    assert "remain" in text and "/local/junie_remote/" in text and "not deleted" in text
    assert "publicly served" in text
    assert "legacy secret" not in text


async def test_custom_private_path_and_multiple_entries_are_isolated(
    hass: MockHomeAssistant, tmp_path: Path
) -> None:
    custom = tmp_path / "elsewhere"
    first = await setup(hass, "e1", **{CONF_LOCAL_STORAGE_PATH: str(custom)})
    second = await setup(hass, "e2", **{CONF_LOCAL_STORAGE_PATH: str(custom)})
    s1 = hass.data[DOMAIN][first.entry_id].storage
    s2 = hass.data[DOMAIN][second.entry_id].storage
    assert s1.inventory is s2.inventory is hass.data[INVENTORY_HASS_KEY]
    await s1.async_save_transcript(doc("shared-host"))
    assert (custom / "e1" / "shared-host" / "latest.json").is_file()
    assert not (custom / "e2").exists()
    with pytest.raises(TranscriptNotFoundError):
        await s2.async_read_transcript("shared-host", "json")
    assert s2.inventory.local_records("e2") == []


async def test_reload_and_removal_retain_files_and_ownership(
    hass: MockHomeAssistant, tmp_path: Path
) -> None:
    entry = await setup(hass, "e1")
    storage = hass.data[DOMAIN][entry.entry_id].storage
    await storage.async_save_transcript(doc())
    files = sorted(p for p in (tmp_path / "junie_remote").rglob("*") if p.is_file())
    assert await async_unload_entry(hass, entry)
    assert sorted(p for p in (tmp_path / "junie_remote").rglob("*") if p.is_file()) == files
    # restarted process: a fresh inventory object over the same persisted Store still owns them
    hass.data.pop(INVENTORY_HASS_KEY)
    entry = await setup(hass, "e1")
    storage = hass.data[DOMAIN][entry.entry_id].storage
    assert (await storage.async_read_transcript("h", "json")).startswith(b"{")
    assert await storage.async_save_transcript(doc())


def test_view_registration_is_skipped_without_real_ha_http(hass: MockHomeAssistant) -> None:
    assert async_register_transcript_view(hass) is False
