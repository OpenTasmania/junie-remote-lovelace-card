"""Durability tests using real HA Store I/O, not hass_storage's mock."""

import asyncio
import json
from threading import Event

import pytest
from homeassistant.core import CoreState, HomeAssistant

from custom_components.junie_remote.models import ChatSessionState, TunnelInfo, TunnelMetadata
from custom_components.junie_remote.storage import LocalTranscriptStorage, TranscriptDocument
from custom_components.junie_remote.transcript_inventory import (
    INVENTORY_STORE_KEY,
    TranscriptInventory,
    TranscriptInventoryError,
)


def make_doc():
    return TranscriptDocument.build(
        "host-a",
        TunnelInfo(tunnel_id="t", connected_clients=0, metadata=TunnelMetadata()),
        ChatSessionState(title="secret"),
        "connected",
    )


@pytest.mark.parametrize("state", [CoreState.not_running, CoreState.stopping])
async def test_real_store_write_failure_never_writes_transcript(tmp_path, state):
    hass = HomeAssistant(str(tmp_path))
    inventory = TranscriptInventory(hass)
    await inventory.async_load()
    (tmp_path / ".storage").mkdir()
    (tmp_path / ".storage" / INVENTORY_STORE_KEY).mkdir()
    hass.set_state(state)
    storage = LocalTranscriptStorage(tmp_path / "private", "entry-a", inventory)

    with pytest.raises(TranscriptInventoryError):
        await storage.async_save_transcript(make_doc())
    assert not list((tmp_path / "private").rglob("*.json"))
    assert inventory.local_records("entry-a") == []


async def test_real_store_persists_intent_and_commit_during_stopping(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    hass.set_state(CoreState.stopping)
    inventory = TranscriptInventory(hass)
    storage = LocalTranscriptStorage(tmp_path / "private", "entry-a", inventory)
    await storage.async_save_transcript(make_doc())

    envelope = json.loads((tmp_path / ".storage" / INVENTORY_STORE_KEY).read_text())
    assert envelope["version"] == 1
    assert len(envelope["data"]["entries"]["entry-a"]["local"]) == 3
    restarted = TranscriptInventory(HomeAssistant(str(tmp_path)))
    await restarted.async_load()
    assert len(restarted.local_records("entry-a")) == 3


async def test_cancelled_inventory_save_waits_for_durable_write_and_keeps_memory(
    tmp_path, monkeypatch
):
    hass = HomeAssistant(str(tmp_path))
    inventory = TranscriptInventory(hass)
    await inventory.async_load()
    writing = Event()
    release = Event()
    original = inventory._store._write_prepared_data

    def blocked_write(*args):
        writing.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(inventory._store, "_write_prepared_data", blocked_write)
    save = asyncio.create_task(inventory.async_prepare_locals("entry-a", [("/owned", "abcd")]))
    try:
        assert await asyncio.to_thread(writing.wait, 5)
        save.cancel()
        save.cancel()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await save
    assert inventory.local_shas("entry-a", "/owned") == {"abcd"}
    fresh = TranscriptInventory(HomeAssistant(str(tmp_path)))
    await fresh.async_load()
    assert fresh.local_shas("entry-a", "/owned") == {"abcd"}


@pytest.mark.parametrize("contents", [
    "not json",
    json.dumps({
        "version": 2, "minor_version": 1, "key": INVENTORY_STORE_KEY,
        "data": {"entries": {}},
    }),
    json.dumps({
        "version": 1, "minor_version": 2, "key": INVENTORY_STORE_KEY,
        "data": {"entries": {}},
    }),
    json.dumps({"version": 1, "minor_version": 1, "key": "other", "data": {"entries": {}}}),
])
async def test_real_store_corrupt_or_unknown_inventory_fails_closed_without_rename(
    tmp_path, contents
):
    store_dir = tmp_path / ".storage"
    store_dir.mkdir()
    path = store_dir / INVENTORY_STORE_KEY
    path.write_text(contents)
    inventory = TranscriptInventory(HomeAssistant(str(tmp_path)))
    with pytest.raises(TranscriptInventoryError):
        await inventory.async_load()
    assert path.read_text() == contents
    assert [p.name for p in store_dir.iterdir()] == [INVENTORY_STORE_KEY]
    storage = LocalTranscriptStorage(tmp_path / "private", "entry-a", inventory)
    with pytest.raises(TranscriptInventoryError):
        await storage.async_save_transcript(make_doc())
    assert not (tmp_path / "private").exists()


async def test_real_store_corrupt_inventory_never_resets_pause(tmp_path):
    inventory = TranscriptInventory(HomeAssistant(str(tmp_path)))
    await inventory.async_load()
    await inventory.async_pause("entry-a")
    restarted = TranscriptInventory(HomeAssistant(str(tmp_path)))
    await restarted.async_load()
    assert restarted.is_paused("entry-a")

    path = tmp_path / ".storage" / INVENTORY_STORE_KEY
    path.write_text("{corrupt")
    after_corruption = TranscriptInventory(HomeAssistant(str(tmp_path)))
    with pytest.raises(TranscriptInventoryError):
        await after_corruption.async_load()
    assert path.read_text() == "{corrupt"
    assert not list((tmp_path / ".storage").glob("*.corrupt.*"))
    storage = LocalTranscriptStorage(tmp_path / "private", "entry-a", after_corruption)
    with pytest.raises(TranscriptInventoryError):
        await storage.async_save_transcript(make_doc())
    assert not (tmp_path / "private").exists()


async def test_real_store_without_private_write_hook_is_refused(tmp_path, monkeypatch):
    from homeassistant.helpers.storage import Store

    from custom_components.junie_remote.artifact_ledger import (
        ArtifactLedger,
        ArtifactLedgerError,
    )

    monkeypatch.delattr(Store, "_async_write_data")
    with pytest.raises(ArtifactLedgerError):
        ArtifactLedger(HomeAssistant(str(tmp_path)))
    with pytest.raises(TranscriptInventoryError):
        TranscriptInventory(HomeAssistant(str(tmp_path)))
