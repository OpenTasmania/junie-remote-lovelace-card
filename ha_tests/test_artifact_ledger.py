"""Exercise artifact ownership using real Home Assistant Store files."""

import asyncio
import errno
import json
import os
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.lovelace.const import ConfigNotFound
from homeassistant.components.lovelace.resources import (
    ResourceStorageCollection,
    ResourceYAMLCollection,
)
from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.junie_remote as integration
from custom_components.junie_remote import _async_sync_fallback
from custom_components.junie_remote.artifact_ledger import ArtifactLedger, ArtifactLedgerError

REAL_STORE_WRITE = Store._async_write_data


async def test_real_resource_removal_flushes_to_disk_and_reinstall(hass, tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    resources = ResourceStorageCollection(
        hass, SimpleNamespace(async_load=AsyncMock(return_value={}))
    )
    monkeypatch.setattr(
        resources.store, "_async_write_data", REAL_STORE_WRITE.__get__(resources.store)
    )
    ledger = hass.data[integration.ARTIFACT_HASS_KEY] = ArtifactLedger(hass)
    monkeypatch.setattr(ledger._store, "_async_write_data", REAL_STORE_WRITE.__get__(ledger._store))
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    await integration._async_register_lovelace_resource(hass)
    assert len(resources.async_items()) == 1
    await integration.async_remove_entry(hass, SimpleNamespace(entry_id="removed"))
    assert resources.async_items() == []
    disk = json.loads(Path(hass.config.path(".storage/lovelace_resources")).read_text())
    assert disk["data"]["items"] == []
    assert ledger.resource is None
    await integration._async_register_lovelace_resource(hass)
    assert len(resources.async_items()) == 1


async def test_real_resource_failed_flush_retains_ownership_for_retry(hass, tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    resources = ResourceStorageCollection(
        hass, SimpleNamespace(async_load=AsyncMock(return_value={}))
    )
    monkeypatch.setattr(
        resources.store, "_async_write_data", REAL_STORE_WRITE.__get__(resources.store)
    )
    ledger = hass.data[integration.ARTIFACT_HASS_KEY] = ArtifactLedger(hass)
    monkeypatch.setattr(ledger._store, "_async_write_data", REAL_STORE_WRITE.__get__(ledger._store))
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    await integration._async_register_lovelace_resource(hass)
    record = ledger.resource
    save = resources.store.async_save
    monkeypatch.setattr(resources.store, "async_save", AsyncMock())
    await integration.async_remove_entry(hass, SimpleNamespace(entry_id="removed"))
    assert ledger.resource == record
    monkeypatch.setattr(resources.store, "async_save", save)
    await integration.async_remove_entry(hass, SimpleNamespace(entry_id="removed"))
    assert ledger.resource is None
    assert resources.async_items() == []


async def test_real_config_entry_removal_waits_for_disabled_entry(hass, tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    resources = ResourceStorageCollection(
        hass, SimpleNamespace(async_load=AsyncMock(return_value={}))
    )
    monkeypatch.setattr(
        resources.store, "_async_write_data", REAL_STORE_WRITE.__get__(resources.store)
    )
    ledger = hass.data[integration.ARTIFACT_HASS_KEY] = ArtifactLedger(hass)
    monkeypatch.setattr(ledger._store, "_async_write_data", REAL_STORE_WRITE.__get__(ledger._store))
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    await integration._async_register_lovelace_resource(hass)
    entries = [MockConfigEntry(domain=integration.DOMAIN) for _ in range(2)]
    object.__setattr__(entries[1], "disabled_by", ConfigEntryDisabler.USER)
    component = SimpleNamespace(
        domain=integration.DOMAIN, async_get_component=AsyncMock(return_value=integration)
    )
    for entry in entries:
        entry.add_to_hass(hass)
        object.__setattr__(entry, "_integration_for_domain", component)
    await hass.config_entries._async_remove(entries[0].entry_id)
    assert len(resources.async_items()) == 1
    await hass.config_entries._async_remove(entries[1].entry_id)
    assert resources.async_items() == []
    assert ledger.resource is None


async def test_real_resource_collection_create_update_and_user_modification(
    tmp_path, monkeypatch
):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    bundle = frontend / "junie-remote-card.js"
    bundle.write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    hass = HomeAssistant(str(tmp_path))
    resources = ResourceStorageCollection(hass, SimpleNamespace(async_load=AsyncMock()))
    await resources.store.async_save({"items": []})
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)

    await asyncio.gather(*(integration._async_register_lovelace_resource(hass) for _ in range(3)))
    item, = resources.async_items()
    assert item["url"] == (
        "/junie_remote/junie-remote-card.js?v="
        "a7937b64b8caa58f03721bb6bacf5c78cb235febe0e70b1b84cd99541461a08e"
    )
    assert item["type"] == "module"
    item_id = item["id"]
    assert hass.data[integration.ARTIFACT_HASS_KEY].resource == item

    bundle.write_bytes(b"second")
    await integration._async_register_lovelace_resource(hass)
    updated, = resources.async_items()
    assert updated["id"] == item_id
    assert updated["url"] != item["url"]
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items() == [updated]

    await resources.async_update_item(item_id, {"url": "/local/manual.js"})
    bundle.write_bytes(b"third")
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items()[0]["url"] == "/local/manual.js"


async def test_real_yaml_resources_are_never_modified(hass, tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    resources = ResourceYAMLCollection([{"type": "module", "url": "/local/manual.js"}])
    hass.data["lovelace"] = SimpleNamespace(resource_mode="yaml", resources=resources)
    await integration._async_register_lovelace_resource(hass)
    ledger = hass.data[integration.ARTIFACT_HASS_KEY] = ArtifactLedger(hass)
    await ledger.async_load()
    await ledger.async_set_resource({"id": "owned", "type": "module", "url": "/old"})
    await integration.async_remove_entry(hass, SimpleNamespace(entry_id="removed"))
    assert resources.async_items() == [{"type": "module", "url": "/local/manual.js"}]
    assert ledger.resource is not None


async def test_real_resource_load_failure_is_not_treated_as_empty(
    hass, tmp_path, monkeypatch, caplog
):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    config = SimpleNamespace(async_load=AsyncMock(side_effect=HomeAssistantError("bad dashboard")))
    resources = ResourceStorageCollection(hass, config)
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items() == []
    assert not resources.loaded
    assert "bad dashboard" in caplog.text


async def test_real_corrupt_resource_store_is_not_reset(tmp_path, monkeypatch, caplog):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    path = tmp_path / ".storage" / "lovelace_resources"
    path.parent.mkdir()
    path.write_text("{broken")
    hass = HomeAssistant(str(tmp_path))
    resources = ResourceStorageCollection(hass, SimpleNamespace(async_load=AsyncMock()))
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items() == []
    assert path.read_text() == "{broken"
    assert "manual review required" in caplog.text


async def test_real_resource_initial_install_without_dashboard(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    hass = HomeAssistant(str(tmp_path))
    config = SimpleNamespace(async_load=AsyncMock(side_effect=ConfigNotFound))
    resources = ResourceStorageCollection(hass, config)
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    await integration._async_register_lovelace_resource(hass)
    assert len(resources.async_items()) == 1
    assert resources.async_items()[0]["url"].startswith("/junie_remote/junie-remote-card.js?v=")


async def test_real_preloaded_empty_missing_store_registers(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    hass = HomeAssistant(str(tmp_path))
    resources = ResourceStorageCollection(
        hass, SimpleNamespace(async_load=AsyncMock(side_effect=ConfigNotFound))
    )
    await resources.async_load()
    resources.loaded = True
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    await integration._async_register_lovelace_resource(hass)
    assert len(resources.async_items()) == 1
    assert hass.data[integration.ARTIFACT_HASS_KEY].resource == resources.async_items()[0]


@pytest.mark.parametrize("legacy", [[], [{"type": "module", "url": "/local/manual.js"}], "invalid"])
async def test_real_preloaded_dashboard_resources_are_not_overwritten(
    tmp_path, monkeypatch, caplog, legacy
):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    hass = HomeAssistant(str(tmp_path))
    config = SimpleNamespace(async_load=AsyncMock(return_value={"resources": legacy}))
    resources = ResourceStorageCollection(hass, config)
    resources.loaded = True
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items() == []
    assert not (tmp_path / ".storage" / "lovelace_resources").exists()
    assert "manual review required" in caplog.text


async def test_real_preloaded_dashboard_load_failure_is_not_empty(tmp_path, monkeypatch, caplog):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    hass = HomeAssistant(str(tmp_path))
    config = SimpleNamespace(async_load=AsyncMock(side_effect=HomeAssistantError("bad dashboard")))
    resources = ResourceStorageCollection(hass, config)
    resources.loaded = True
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items() == []
    assert "bad dashboard" in caplog.text


async def test_real_lovelace_websocket_preloads_before_registration(
    hass, hass_ws_client, tmp_path, monkeypatch
):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    assert await async_setup_component(hass, "http", {"http": {}})
    assert await async_setup_component(hass, "websocket_api", {})
    assert await async_setup_component(hass, "lovelace", {"lovelace": {}})
    client = await hass_ws_client()
    await client.send_json({"id": 1, "type": "lovelace/resources"})
    result = await client.receive_json()
    assert result["success"] and result["result"] == []
    resources = hass.data["lovelace"].resources
    assert resources.loaded
    ledger = hass.data[integration.ARTIFACT_HASS_KEY] = ArtifactLedger(hass)
    monkeypatch.setattr(
        resources.store, "_async_write_data", REAL_STORE_WRITE.__get__(resources.store)
    )
    monkeypatch.setattr(ledger._store, "_async_write_data", REAL_STORE_WRITE.__get__(ledger._store))
    await integration._async_register_lovelace_resource(hass)
    assert len(resources.async_items()) == 1
    assert ledger.resource == resources.async_items()[0]


@pytest.mark.parametrize("legacy_type", ["module", "not-a-resource-type"])
async def test_real_legacy_import_preserves_resources(
    hass, tmp_path, monkeypatch, caplog, legacy_type
):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    legacy = {"type": legacy_type, "url": "/junie_remote/junie-remote-card.js?old=1"}
    config = SimpleNamespace(
        async_load=AsyncMock(return_value={"resources": [legacy]}), async_save=AsyncMock()
    )
    resources = ResourceStorageCollection(hass, config)
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items() == []
    assert not resources.loaded
    assert await config.async_load(False) == {"resources": [legacy]}
    config.async_save.assert_not_awaited()
    assert "manual review required" in caplog.text


async def test_real_resource_store_restart_and_missing_delayed_write(tmp_path, monkeypatch, caplog):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    bundle = frontend / "junie-remote-card.js"
    bundle.write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))

    def make_hass():
        hass = HomeAssistant(str(tmp_path))
        config = SimpleNamespace(async_load=AsyncMock(return_value={}))
        resources = ResourceStorageCollection(hass, config)
        hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
        return hass, resources

    hass, resources = make_hass()
    await resources.store.async_save({"items": []})
    await integration._async_register_lovelace_resource(hass)
    original, = resources.async_items()
    restarted, after_restart = make_hass()
    bundle.write_bytes(b"second")
    await integration._async_register_lovelace_resource(restarted)
    updated, = after_restart.async_items()
    assert updated["id"] == original["id"]
    assert updated["url"] != original["url"]
    restarted_again, persisted = make_hass()
    await integration._async_register_lovelace_resource(restarted_again)
    assert persisted.async_items() == [updated]

    # Simulate a crash before HA persisted a resource; the durable ledger must
    # not treat the missing resource as permission to create a replacement.
    await after_restart.store.async_save({"items": []})
    crashed, missing = make_hass()
    await integration._async_register_lovelace_resource(crashed)
    assert missing.async_items() == []
    assert "missing or modified" in caplog.text


async def test_real_resource_failed_flush_does_not_record_ownership(tmp_path, monkeypatch, caplog):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    hass = HomeAssistant(str(tmp_path))
    resources = ResourceStorageCollection(
        hass, SimpleNamespace(async_load=AsyncMock(return_value={}))
    )
    await resources.store.async_save({"items": []})
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    monkeypatch.setattr(resources.store, "async_save", AsyncMock(return_value=None))
    await integration._async_register_lovelace_resource(hass)
    assert len(resources.async_items()) == 1
    assert hass.data[integration.ARTIFACT_HASS_KEY].resource is None
    persisted = json.loads((tmp_path / ".storage" / "lovelace_resources").read_text())
    assert persisted["data"]["items"] == []
    assert "manual review required" in caplog.text


async def test_real_failed_update_flush_leaves_old_disk_resource_unowned(
    tmp_path, monkeypatch, caplog
):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    bundle = frontend / "junie-remote-card.js"
    bundle.write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    hass = HomeAssistant(str(tmp_path))
    config = SimpleNamespace(async_load=AsyncMock(return_value={}))
    resources = ResourceStorageCollection(hass, config)
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    await integration._async_register_lovelace_resource(hass)
    original, = resources.async_items()

    bundle.write_bytes(b"second")
    monkeypatch.setattr(resources.store, "async_save", AsyncMock(return_value=None))
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items()[0]["url"] != original["url"]
    assert hass.data[integration.ARTIFACT_HASS_KEY].resource is None
    assert "manual review required" in caplog.text

    restarted = HomeAssistant(str(tmp_path))
    restored = ResourceStorageCollection(restarted, config)
    restarted.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=restored)
    await integration._async_register_lovelace_resource(restarted)
    assert restored.async_items() == [original]
    assert restarted.data[integration.ARTIFACT_HASS_KEY].resource is None


async def test_real_resource_unsupported_flush_does_not_mutate(tmp_path, monkeypatch, caplog):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    hass = HomeAssistant(str(tmp_path))
    resources = ResourceStorageCollection(
        hass, SimpleNamespace(async_load=AsyncMock(return_value={}))
    )
    await resources.store.async_save({"items": []})
    monkeypatch.setattr(resources.store, "async_save", None)
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items() == []
    assert hass.data[integration.ARTIFACT_HASS_KEY].resource is None
    assert "manual review required" in caplog.text


async def test_real_resource_changed_during_create_is_not_owned(tmp_path, monkeypatch, caplog):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    hass = HomeAssistant(str(tmp_path))
    resources = ResourceStorageCollection(
        hass, SimpleNamespace(async_load=AsyncMock(return_value={}))
    )
    await resources.store.async_save({"items": []})
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    create = resources.async_create_item

    async def create_then_modify(data):
        item = await create(data)
        await resources.async_update_item(item["id"], {"url": "/local/manual.js"})
        return item

    monkeypatch.setattr(resources, "async_create_item", create_then_modify)
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items()[0]["url"] == "/local/manual.js"
    assert hass.data[integration.ARTIFACT_HASS_KEY].resource is None
    assert "manual review required" in caplog.text


async def test_real_resource_collection_replaced_during_flush_is_not_owned(
    tmp_path, monkeypatch, caplog
):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "junie-remote-card.js").write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(tmp_path / "__init__.py"))
    hass = HomeAssistant(str(tmp_path))
    config = SimpleNamespace(async_load=AsyncMock(return_value={}))
    resources = ResourceStorageCollection(hass, config)
    await resources.store.async_save({"items": []})
    lovelace = hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=resources)
    save = resources.store.async_save

    async def save_then_replace(data):
        await save(data)
        lovelace.resources = ResourceStorageCollection(hass, config)

    monkeypatch.setattr(resources.store, "async_save", save_then_replace)
    await integration._async_register_lovelace_resource(hass)
    assert hass.data[integration.ARTIFACT_HASS_KEY].resource is None
    assert "manual review required" in caplog.text


async def test_real_store_restart_preserves_file_and_resource_slot(tmp_path):
    ledger = ArtifactLedger(HomeAssistant(str(tmp_path)))
    await ledger.async_load()
    await ledger.async_set_file({"path": "/config/www/card.js", "sha256": "a" * 64})
    envelope = json.loads((tmp_path / ".storage" / "junie_remote_artifact_ownership").read_text())
    assert envelope["version"] == 1
    assert envelope["data"] == {
        "file": {"path": "/config/www/card.js", "sha256": "a" * 64},
        "resource": None,
    }
    restarted = ArtifactLedger(HomeAssistant(str(tmp_path)))
    await restarted.async_load()
    assert restarted.file == envelope["data"]["file"]


@pytest.mark.parametrize("contents", [
    "not json",
    json.dumps({
        "version": 2, "minor_version": 1, "key": "junie_remote_artifact_ownership",
        "data": {"file": None, "resource": None},
    }),
    json.dumps({"version": 1, "minor_version": 1,
                "key": "junie_remote_artifact_ownership", "data": {"file": "invalid"}}),
])
async def test_invalid_store_fails_closed_without_renaming(tmp_path, contents):
    path = tmp_path / ".storage" / "junie_remote_artifact_ownership"
    path.parent.mkdir()
    path.write_text(contents)
    ledger = ArtifactLedger(HomeAssistant(str(tmp_path)))
    with pytest.raises(ArtifactLedgerError):
        await ledger.async_load()
    assert path.read_text() == contents
    source = tmp_path / "bundle.js"
    source.write_bytes(b"first")
    www = tmp_path / "www"
    www.mkdir()
    target = www / "junie-remote-card.js"
    with pytest.raises(ArtifactLedgerError):
        await _async_sync_fallback(HomeAssistant(str(tmp_path)), source, target)
    assert not target.exists()


async def test_real_store_restart_and_interrupted_commit_do_not_adopt(tmp_path, monkeypatch):
    source = tmp_path / "bundle.js"
    source.write_bytes(b"first")
    www = tmp_path / "www"
    www.mkdir()
    target = www / "junie-remote-card.js"
    hass = HomeAssistant(str(tmp_path))
    await _async_sync_fallback(hass, source, target)
    source.write_bytes(b"second")
    await _async_sync_fallback(HomeAssistant(str(tmp_path)), source, target)
    assert target.read_bytes() == b"second"

    source.write_bytes(b"third")
    from custom_components.junie_remote import ARTIFACT_HASS_KEY

    hass = HomeAssistant(str(tmp_path))
    ledger = hass.data[ARTIFACT_HASS_KEY] = ArtifactLedger(hass)
    original = ledger._store.async_save
    count = 0

    async def fail_final(data):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("commit interrupted")
        await original(data)

    monkeypatch.setattr(ledger._store, "async_save", fail_final)
    with pytest.raises(ArtifactLedgerError):
        await _async_sync_fallback(hass, source, target)
    assert target.read_bytes() == b"third"
    source.write_bytes(b"fourth")
    await _async_sync_fallback(HomeAssistant(str(tmp_path)), source, target)
    assert target.read_bytes() == b"third"


async def test_real_store_failure_before_publish_keeps_file(tmp_path):
    source = tmp_path / "bundle.js"
    source.write_bytes(b"first")
    www = tmp_path / "www"
    www.mkdir()
    target = www / "junie-remote-card.js"
    # The Store cannot create its file at a path occupied by a directory.
    (tmp_path / ".storage" / "junie_remote_artifact_ownership").mkdir(parents=True)
    with pytest.raises(ArtifactLedgerError):
        await _async_sync_fallback(HomeAssistant(str(tmp_path)), source, target)
    assert not target.exists()


@pytest.mark.parametrize("failure", ["exchange", "temp_create", "write", "recheck"])
async def test_real_store_pre_mutation_failure_is_durable_and_retryable(
    tmp_path, monkeypatch, failure
):
    source = tmp_path / "bundle.js"
    source.write_bytes(b"first")
    www = tmp_path / "www"
    www.mkdir()
    target = www / "junie-remote-card.js"
    await _async_sync_fallback(HomeAssistant(str(tmp_path)), source, target)
    original = ArtifactLedger(HomeAssistant(str(tmp_path)))
    await original.async_load()
    record = original.file
    source.write_bytes(b"second")
    snapshot = integration._fallback_snapshot
    fsync = integration.os.fsync
    mkstemp = integration.tempfile.mkstemp

    def fail(*args, **kwargs):
        code = errno.ENOSPC if failure in ("write", "temp_create") else errno.EINVAL
        raise OSError(code, failure)

    def mismatch(src, dst):
        if src == dst == target:
            return b"first", None
        return snapshot(src, dst)

    def fail_temp_sync(fd):
        if ".junie-card-" in os.readlink(f"/proc/self/fd/{fd}"):
            fail()
        return fsync(fd)

    def fail_temp_create(*args, **kwargs):
        if kwargs.get("prefix") == ".junie-card-":
            fail()
        return mkstemp(*args, **kwargs)

    with monkeypatch.context() as patch:
        if failure == "exchange":
            patch.setattr(integration, "_exchange_fallback", fail)
        elif failure == "temp_create":
            patch.setattr(integration.tempfile, "mkstemp", fail_temp_create)
        elif failure == "write":
            patch.setattr(integration.os, "fsync", fail_temp_sync)
        else:
            patch.setattr(integration, "_fallback_snapshot", mismatch)
        with pytest.raises(OSError):
            await _async_sync_fallback(HomeAssistant(str(tmp_path)), source, target)
    assert target.read_bytes() == b"first"
    restarted = ArtifactLedger(HomeAssistant(str(tmp_path)))
    await restarted.async_load()
    assert restarted.file == record
    await _async_sync_fallback(HomeAssistant(str(tmp_path)), source, target)
    assert target.read_bytes() == b"second"


async def test_real_store_failed_recovery_does_not_restore_memory_or_disk(tmp_path, monkeypatch):
    source = tmp_path / "bundle.js"
    source.write_bytes(b"first")
    (tmp_path / "www").mkdir()
    target = tmp_path / "www" / "card.js"
    hass = HomeAssistant(str(tmp_path))
    await _async_sync_fallback(hass, source, target)
    source.write_bytes(b"second")
    ledger = hass.data[integration.ARTIFACT_HASS_KEY]
    save = ledger._store.async_save
    count = 0

    async def fail_restore(data):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("restore failed")
        await save(data)

    def fail_exchange(*args):
        raise OSError(errno.EINVAL, "unsupported")

    monkeypatch.setattr(ledger._store, "async_save", fail_restore)
    monkeypatch.setattr(integration, "_exchange_fallback", fail_exchange)
    with pytest.raises(ArtifactLedgerError):
        await _async_sync_fallback(hass, source, target)
    assert target.read_bytes() == b"first"
    restarted = ArtifactLedger(HomeAssistant(str(tmp_path)))
    await restarted.async_load()
    assert restarted.file is None
    with pytest.raises(ArtifactLedgerError):
        _ = ledger.file


async def test_real_store_cancelled_recovery_waits_for_durable_restore(tmp_path, monkeypatch):
    source = tmp_path / "bundle.js"
    source.write_bytes(b"first")
    (tmp_path / "www").mkdir()
    target = tmp_path / "www" / "card.js"
    hass = HomeAssistant(str(tmp_path))
    await _async_sync_fallback(hass, source, target)
    ledger = hass.data[integration.ARTIFACT_HASS_KEY]
    record = ledger.file
    source.write_bytes(b"second")
    write = ledger._store._write_prepared_data
    started, release = Event(), Event()
    count = 0

    def block_restore(*args):
        nonlocal count
        count += 1
        if count == 2:
            started.set()
            assert release.wait(5)
        return write(*args)

    def fail_exchange(*args):
        raise OSError(errno.EINVAL, "unsupported")

    monkeypatch.setattr(ledger._store, "_write_prepared_data", block_restore)
    monkeypatch.setattr(integration, "_exchange_fallback", fail_exchange)
    task = asyncio.create_task(_async_sync_fallback(hass, source, target))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(OSError):
        await task
    restarted = ArtifactLedger(HomeAssistant(str(tmp_path)))
    await restarted.async_load()
    assert restarted.file == record


@pytest.mark.parametrize("state", [CoreState.not_running, CoreState.stopping])
async def test_real_store_write_error_stops_publication(tmp_path, monkeypatch, state):
    from custom_components.junie_remote import ARTIFACT_HASS_KEY

    source = tmp_path / "bundle.js"
    source.write_bytes(b"first")
    www = tmp_path / "www"
    www.mkdir()
    target = www / "junie-remote-card.js"
    hass = HomeAssistant(str(tmp_path))
    hass.set_state(state)
    ledger = hass.data[ARTIFACT_HASS_KEY] = ArtifactLedger(hass)

    def fail_write(*args):
        raise OSError("disk write failed")

    monkeypatch.setattr(ledger._store, "_write_prepared_data", fail_write)
    with pytest.raises(ArtifactLedgerError):
        await _async_sync_fallback(hass, source, target)
    assert not target.exists()
