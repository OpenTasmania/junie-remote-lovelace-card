# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Smoke test for Junie Remote integration initialization and constants."""

import asyncio
import errno
import logging
import os
import threading

import pytest

import custom_components.junie_remote as integration
import custom_components.junie_remote.storage as storage_module
from custom_components.junie_remote import DOMAIN
from custom_components.junie_remote.const import (
    API_BASE_PATH,
    BASE_URL,
    CONF_COOKIE_HEADER,
    CONF_LOCAL_STORAGE_PATH,
    CONF_S3_ACCESS_KEY,
    CONF_S3_BUCKET,
    CONF_S3_ENDPOINT,
    CONF_S3_PUBLIC_URL_BASE,
    CONF_S3_REGION,
    CONF_S3_SECRET_KEY,
    CONF_STORAGE_STATE,
    CONF_STORAGE_TYPE,
    DEFAULT_LOCAL_STORAGE_PATH,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_STORAGE_TYPE,
    SERVICE_CANCEL,
    SERVICE_CANCEL_TASK,
    SERVICE_CONFIRM_PLAN,
    SERVICE_KICK_CLIENT,
    SERVICE_RESPOND,
    SERVICE_RESPOND_REQUEST,
    SERVICE_SELECT_MODEL,
    SERVICE_SEND_PLAN_PROMPT,
    SERVICE_SEND_PROMPT,
    SERVICE_TOGGLE_BRAVE_MODE,
    STORAGE_TYPE_LOCAL,
    STORAGE_TYPE_S3,
)
from custom_components.junie_remote.ha_compat import ConfigEntry, MockHomeAssistant, MockLovelace


def test_domain():
    """Verify integration domain constant."""
    assert DOMAIN == "junie_remote"


async def test_fallback_refreshes_owned_bytes_and_adopts_unowned(tmp_path, monkeypatch):
    frontend = tmp_path / "component" / "frontend"
    frontend.mkdir(parents=True)
    source = frontend / "junie-remote-card.js"
    source.write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(frontend.parent / "__init__.py"))
    hass = MockHomeAssistant()
    hass.config.config_dir = str(tmp_path)
    www = tmp_path / "www"
    www.mkdir()
    target = www / source.name
    target.write_bytes(b"legacy")
    os.utime(target, (1, 1))
    # Unowned (legacy) fallback is now adopted and updated from source.
    await integration._register_static_path(hass)
    assert target.read_bytes() == b"first"
    source.write_bytes(b"second")
    os.utime(source, (1, 1))
    await integration._register_static_path(hass)
    assert target.read_bytes() == b"second"
    before = target.stat().st_mtime_ns
    await integration._register_static_path(hass)
    assert target.stat().st_mtime_ns == before


@pytest.fixture
def fallback(tmp_path, monkeypatch):
    frontend = tmp_path / "component" / "frontend"
    frontend.mkdir(parents=True)
    source = frontend / "junie-remote-card.js"
    source.write_bytes(b"first")
    monkeypatch.setattr(integration, "__file__", str(frontend.parent / "__init__.py"))
    hass = MockHomeAssistant()
    hass.config.config_dir = str(tmp_path)
    www = tmp_path / "www"
    www.mkdir()
    return hass, source, www / source.name


@pytest.mark.parametrize("url", [
    "/junie_remote/junie-remote-card.js",
    "/junie_remote/junie-remote-card.js?custom=1",
    "/local/junie-remote-card.js?v=manual",
])
async def test_manual_resource_not_adopted_or_duplicated(fallback, url):
    hass, _, _ = fallback
    resources = MockLovelace().resources
    hass.data["lovelace"] = MockLovelace()
    hass.data["lovelace"].resources = resources
    original = await resources.async_create_item({"res_type": "module", "url": url})
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items() == [original]
    assert hass.data[integration.ARTIFACT_HASS_KEY].resource is None


async def test_resource_restart_update_and_missing_bundle(fallback, caplog):
    hass, source, _ = fallback
    hass.data["lovelace"] = MockLovelace()
    resources = hass.data["lovelace"].resources
    await integration._async_register_lovelace_resource(hass)
    original, = resources.async_items()
    assert original["url"].endswith(
        "a7937b64b8caa58f03721bb6bacf5c78cb235febe0e70b1b84cd99541461a08e"
    )
    hass.data.pop(integration.ARTIFACT_HASS_KEY)
    source.write_bytes(b"second")
    await asyncio.gather(*(integration._async_register_lovelace_resource(hass) for _ in range(3)))
    updated, = resources.async_items()
    assert updated["id"] == original["id"]
    assert updated["url"] != original["url"]
    source.unlink()
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items() == [updated]
    assert "manual review required" in caplog.text


async def test_permanent_removal_deletes_owned_artifacts_and_reinstall(fallback):
    hass, source, target = fallback
    hass.data["lovelace"] = MockLovelace()
    await integration._register_static_path(hass)
    await integration._async_register_lovelace_resource(hass)
    assert target.exists() and len(hass.data["lovelace"].resources.async_items()) == 1

    await integration.async_remove_entry(hass, ConfigEntry(entry_id="removed"))
    assert not target.exists()
    assert hass.data["lovelace"].resources.async_items() == []

    await integration._register_static_path(hass)
    await integration._async_register_lovelace_resource(hass)
    assert target.read_bytes() == source.read_bytes()
    assert len(hass.data["lovelace"].resources.async_items()) == 1


@pytest.mark.parametrize("blocker", ["configured", "live", "failed_unload"])
async def test_removal_preserves_artifacts_when_an_entry_needs_them(fallback, blocker):
    from types import SimpleNamespace

    hass, _, target = fallback
    hass.data["lovelace"] = MockLovelace()
    await integration._register_static_path(hass)
    await integration._async_register_lovelace_resource(hass)
    entry = ConfigEntry(entry_id="removed")
    if blocker == "configured":
        hass.config_entries.entries["disabled"] = ConfigEntry(entry_id="disabled")
    elif blocker == "live":
        hass.data[DOMAIN] = {"removed": object()}
    else:
        entry.state = SimpleNamespace(name="FAILED_UNLOAD")
    await integration.async_remove_entry(hass, entry)
    assert target.exists()
    assert len(hass.data["lovelace"].resources.async_items()) == 1


async def test_removal_preserves_modified_artifacts_and_retries(fallback, caplog):
    hass, _, target = fallback
    hass.data["lovelace"] = MockLovelace()
    resources = hass.data["lovelace"].resources
    await integration._register_static_path(hass)
    await integration._async_register_lovelace_resource(hass)
    item, = resources.async_items()
    target.write_bytes(b"manual")
    await resources.async_update_item(item["id"], {"url": "/local/manual.js"})
    await integration.async_remove_entry(hass, ConfigEntry())
    assert target.read_bytes() == b"manual"
    assert resources.async_items()[0]["url"] == "/local/manual.js"
    assert "manual review required" in caplog.text
    target.write_bytes(b"first")
    await resources.async_update_item(item["id"], {"url": item["url"]})
    await integration.async_remove_entry(hass, ConfigEntry())
    assert not target.exists()
    assert resources.async_items() == []


async def test_pending_startup_callback_cannot_recreate_after_removal(fallback):
    hass, _, target = fallback
    hass.data["lovelace"] = MockLovelace()
    await integration.async_setup(hass, {})
    assert target.exists()
    await integration.async_remove_entry(hass, ConfigEntry())
    await hass.bus.async_fire(integration.EVENT_HOMEASSISTANT_STARTED)
    assert not target.exists()
    assert hass.data["lovelace"].resources.async_items() == []


async def test_new_entry_during_removal_prevents_artifact_deletion(fallback, monkeypatch):
    hass, _, target = fallback
    hass.data["lovelace"] = MockLovelace()
    await integration._register_static_path(hass)
    await integration._async_register_lovelace_resource(hass)
    ledger = hass.data[integration.ARTIFACT_HASS_KEY]
    load = ledger.async_load
    started, release = asyncio.Event(), asyncio.Event()

    async def blocked_load():
        started.set()
        await release.wait()
        await load()

    monkeypatch.setattr(ledger, "async_load", blocked_load)
    task = asyncio.create_task(integration.async_remove_entry(hass, ConfigEntry()))
    await started.wait()
    hass.config_entries.entries["new"] = ConfigEntry(entry_id="new")
    release.set()
    await task
    assert target.exists()
    assert len(hass.data["lovelace"].resources.async_items()) == 1


async def test_interrupted_file_deletion_does_not_adopt_replacement(fallback, monkeypatch):
    hass, _, target = fallback
    await integration._register_static_path(hass)

    def interrupted(path, sha):
        target.unlink()
        raise RuntimeError("crash after unlink")

    delete = integration._delete_owned_local_file
    monkeypatch.setattr(integration, "_delete_owned_local_file", interrupted)
    await integration.async_remove_entry(hass, ConfigEntry())
    target.write_bytes(b"first")
    monkeypatch.setattr(integration, "_delete_owned_local_file", delete)
    await integration.async_remove_entry(hass, ConfigEntry())
    assert target.read_bytes() == b"first"


async def test_interrupted_deletion_post_rename_failure_does_not_restore_record(
    fallback, monkeypatch
):
    hass, _, target = fallback
    await integration._register_static_path(hass)
    ledger = hass.data[integration.ARTIFACT_HASS_KEY]
    record = ledger.file
    assert record is not None

    def fail_after_quarantine(path, sha):
        # Pretend deletion failed after the target was moved to quarantine.
        return (
            "Failed to delete: unlink error; quarantine '.junie-remote-cleanup-1' retained",
            False,
            True,
        )

    monkeypatch.setattr(integration, "_delete_owned_local_file", fail_after_quarantine)
    await integration.async_remove_entry(hass, ConfigEntry())
    assert ledger.file is None


async def test_interrupted_deletion_pre_mutation_failure_restores_record(
    fallback, monkeypatch
):
    hass, _, target = fallback
    await integration._register_static_path(hass)
    ledger = hass.data[integration.ARTIFACT_HASS_KEY]
    record = ledger.file
    assert record is not None

    def fail_before_quarantine(path, sha):
        # Pretend deletion failed before the target was touched.
        return "Failed to delete: pre-check error", False, False

    monkeypatch.setattr(integration, "_delete_owned_local_file", fail_before_quarantine)
    await integration.async_remove_entry(hass, ConfigEntry())
    assert ledger.file == record


async def test_real_orphan_quarantine_deletion_restores_record_and_retries(fallback):
    hass, _, target = fallback
    await integration._register_static_path(hass)
    ledger = hass.data[integration.ARTIFACT_HASS_KEY]
    record = ledger.file
    assert record is not None
    orphan = target.with_name(".junie-remote-cleanup-existing")
    orphan.write_bytes(b"manual review")

    await integration.async_remove_entry(hass, ConfigEntry())

    assert ledger.file == record
    assert target.read_bytes() == b"first"
    assert orphan.read_bytes() == b"manual review"

    orphan.unlink()
    await integration.async_remove_entry(hass, ConfigEntry())

    assert not target.exists()
    assert ledger.file is None


async def test_real_post_rename_failure_clears_ownership_and_adopts_source(
    fallback, monkeypatch
):
    hass, source, target = fallback
    await integration._register_static_path(hass)
    ledger = hass.data[integration.ARTIFACT_HASS_KEY]
    real_unlink = os.unlink

    def fail_quarantine_unlink(path, *args, **kwargs):
        if isinstance(path, str) and path.startswith(".junie-remote-cleanup-"):
            raise OSError("unlink failed after quarantine")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(storage_module.os, "unlink", fail_quarantine_unlink)
    await integration.async_remove_entry(hass, ConfigEntry())
    assert ledger.file is None
    assert not target.exists()
    quarantined, = target.parent.glob(".junie-remote-cleanup-*")
    assert quarantined.read_bytes() == b"first"

    monkeypatch.setattr(storage_module.os, "unlink", real_unlink)
    target.write_bytes(b"replacement")
    await integration._register_static_path(hass)

    # After ownership is cleared, the sync adopts the file from source.
    assert ledger.file is not None
    assert target.read_bytes() == b"first"
    assert quarantined.read_bytes() == b"first"


async def test_removal_of_missing_artifacts_is_harmless(fallback):
    hass, _, target = fallback
    hass.data["lovelace"] = MockLovelace()
    resources = hass.data["lovelace"].resources
    await integration._register_static_path(hass)
    await integration._async_register_lovelace_resource(hass)
    item, = resources.async_items()
    target.unlink()
    await resources.async_delete_item(item["id"])
    await integration.async_remove_entry(hass, ConfigEntry())
    ledger = hass.data[integration.ARTIFACT_HASS_KEY]
    assert ledger.file is None and ledger.resource is None
    assert not target.exists() and resources.async_items() == []


async def test_manual_resource_preserved_and_file_adopted(fallback):
    """Manual Lovelace resource is preserved; unowned file is adopted from source."""
    hass, _, target = fallback
    target.write_bytes(b"manual")
    hass.data["lovelace"] = MockLovelace()
    resources = hass.data["lovelace"].resources
    item = await resources.async_create_item({
        "res_type": "module", "url": "/local/junie-remote-card.js"
    })
    await integration._register_static_path(hass)
    # The sync now adopts the unowned file from the source bundle.
    assert target.read_bytes() == b"first"
    await integration._async_register_lovelace_resource(hass)
    await integration.async_remove_entry(hass, ConfigEntry())
    # Manual resource is never removed by the integration.
    assert resources.async_items() == [item]
    # File was adopted and owned, so removal deletes it.
    assert not target.exists()


async def test_resource_with_additional_user_fields_is_not_removed(fallback):
    hass, _, _ = fallback
    hass.data["lovelace"] = MockLovelace()
    resources = hass.data["lovelace"].resources
    await integration._async_register_lovelace_resource(hass)
    resources._items[0]["custom"] = "keep"
    await integration.async_remove_entry(hass, ConfigEntry())
    assert resources.async_items()[0]["custom"] == "keep"


async def test_resource_load_failure_does_not_create(fallback, monkeypatch, caplog):
    hass, _, _ = fallback
    hass.data["lovelace"] = MockLovelace()
    resources = hass.data["lovelace"].resources
    resources.loaded = False

    async def fail():
        raise OSError("load failed")

    monkeypatch.setattr(resources, "async_load", fail)
    await integration._async_register_lovelace_resource(hass)
    assert not resources.async_items()
    assert not resources.loaded
    assert "load failed" in caplog.text


async def test_resource_added_during_ledger_commit_is_not_duplicated(fallback, monkeypatch):
    hass, _, _ = fallback
    hass.data["lovelace"] = MockLovelace()
    resources = hass.data["lovelace"].resources
    ledger = hass.data[integration.ARTIFACT_HASS_KEY] = integration.ArtifactLedger(hass)
    save = ledger.async_set_resource

    async def insert_manual(record):
        await save(record)
        await resources.async_create_item({
            "res_type": "module", "url": "/local/junie-remote-card.js?manual=1"
        })

    monkeypatch.setattr(ledger, "async_set_resource", insert_manual)
    await integration._async_register_lovelace_resource(hass)
    assert len(resources.async_items()) == 1
    assert resources.async_items()[0]["url"] == "/local/junie-remote-card.js?manual=1"


async def test_resource_mode_change_during_registration_prevents_mutation(fallback, monkeypatch):
    hass, _, _ = fallback
    hass.data["lovelace"] = MockLovelace()
    resources = hass.data["lovelace"].resources
    ledger = hass.data[integration.ARTIFACT_HASS_KEY] = integration.ArtifactLedger(hass)
    save = ledger.async_set_resource

    async def switch_mode(record):
        await save(record)
        hass.data["lovelace"].resource_mode = "yaml"

    monkeypatch.setattr(ledger, "async_set_resource", switch_mode)
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items() == []


async def test_resource_commit_failure_does_not_adopt_or_duplicate(fallback, monkeypatch, caplog):
    hass, source, _ = fallback
    hass.data["lovelace"] = MockLovelace()
    resources = hass.data["lovelace"].resources
    ledger = hass.data[integration.ARTIFACT_HASS_KEY] = integration.ArtifactLedger(hass)
    save = ledger._store.async_save
    calls = 0

    async def fail_final(data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("commit failed")
        await save(data)

    monkeypatch.setattr(ledger._store, "async_save", fail_final)
    await integration._async_register_lovelace_resource(hass)
    item, = resources.async_items()
    assert "manual review required" in caplog.text
    hass.data.pop(integration.ARTIFACT_HASS_KEY)
    source.write_bytes(b"new")
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items() == [item]
    assert hass.data[integration.ARTIFACT_HASS_KEY].resource is None


async def test_resource_cancellation_waits_for_commit(fallback, monkeypatch):
    hass, _, _ = fallback
    hass.data["lovelace"] = MockLovelace()
    resources = hass.data["lovelace"].resources
    ledger = hass.data[integration.ARTIFACT_HASS_KEY] = integration.ArtifactLedger(hass)
    save = ledger._store.async_save
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_save(data):
        if data["resource"] is not None:
            started.set()
            await release.wait()
        await save(data)

    monkeypatch.setattr(ledger._store, "async_save", blocked_save)
    task = asyncio.create_task(integration._async_register_lovelace_resource(hass))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    item, = resources.async_items()
    assert ledger.resource == item
    hass.data.pop(integration.ARTIFACT_HASS_KEY)
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items() == [item]


async def test_owned_resource_update_failure_is_not_adopted(fallback, monkeypatch, caplog):
    hass, source, _ = fallback
    hass.data["lovelace"] = MockLovelace()
    resources = hass.data["lovelace"].resources
    await integration._async_register_lovelace_resource(hass)
    original, = resources.async_items()
    source.write_bytes(b"second")

    async def fail(*args):
        raise OSError("update failed")

    monkeypatch.setattr(resources, "async_update_item", fail)
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items() == [original]
    assert hass.data[integration.ARTIFACT_HASS_KEY].resource is None
    assert "update failed" in caplog.text
    await integration._async_register_lovelace_resource(hass)
    assert resources.async_items() == [original]


@pytest.mark.parametrize("owned_url", [
    "/junie_remote/junie-remote-card.js", "/junie_remote/junie-remote-card.js?v=old"
])
async def test_proven_old_resource_is_updated_without_touching_s3(fallback, owned_url):
    hass, _, _ = fallback
    hass.data["lovelace"] = MockLovelace()
    resources = hass.data["lovelace"].resources
    owned = await resources.async_create_item({"res_type": "module", "url": owned_url})
    s3 = await resources.async_create_item({
        "res_type": "module", "url": "https://bucket.example/key?X-Amz-Signature=abc"
    })
    ledger = hass.data[integration.ARTIFACT_HASS_KEY] = integration.ArtifactLedger(hass)
    await ledger.async_load()
    await ledger.async_set_resource(owned)
    await integration._async_register_lovelace_resource(hass)
    updated, untouched = resources.async_items()
    assert updated["id"] == owned["id"]
    assert updated["url"].startswith("/junie_remote/junie-remote-card.js?v=")
    assert untouched == s3


async def test_unsupported_resource_api_does_not_mutate(fallback, caplog):
    hass, _, _ = fallback
    lovelace = MockLovelace()
    lovelace.resources = [{"url": "/local/junie-remote-card.js", "type": "module"}]
    hass.data["lovelace"] = lovelace
    await integration._async_register_lovelace_resource(hass)
    assert lovelace.resources == [{"url": "/local/junie-remote-card.js", "type": "module"}]
    assert "Unsupported Lovelace resource collection" in caplog.text


async def test_fallback_equal_mtimes_restart_and_modified_file(fallback):
    hass, source, target = fallback
    await integration._register_static_path(hass)
    source.write_bytes(b"second")
    os.utime(source, ns=(target.stat().st_mtime_ns, target.stat().st_mtime_ns))
    hass.data.pop(integration.ARTIFACT_HASS_KEY)
    await integration._register_static_path(hass)
    assert target.read_bytes() == b"second"
    target.write_bytes(b"manual edit")
    source.write_bytes(b"third")
    await integration._register_static_path(hass)
    assert target.read_bytes() == b"manual edit"


async def test_fallback_identical_legacy_adopted_on_content_change(fallback):
    """Legacy file matching source is skipped; adopted when source changes."""
    hass, source, target = fallback
    target.write_bytes(b"first")
    await integration._async_sync_fallback(hass, source, target)
    # Content matches source — early return, no adoption.
    assert target.read_bytes() == b"first"
    assert hass.data[integration.ARTIFACT_HASS_KEY].file is None
    source.write_bytes(b"second")
    await integration._async_sync_fallback(hass, source, target)
    # Source differs — unowned file is adopted and updated.
    assert target.read_bytes() == b"second"
    assert hass.data[integration.ARTIFACT_HASS_KEY].file is not None


async def test_fallback_creation_does_not_replace_racing_file(fallback, monkeypatch):
    hass, source, target = fallback
    link = integration.os.link

    def competing_create(src, dst, **kwargs):
        target.write_bytes(b"manual")
        return link(src, dst, **kwargs)

    monkeypatch.setattr(integration.os, "link", competing_create)
    with pytest.raises(FileExistsError):
        await integration._async_sync_fallback(hass, source, target)
    assert target.read_bytes() == b"manual"


async def test_fallback_preserves_symlink_and_missing_paths(fallback, caplog):
    hass, source, target = fallback
    other = target.parent / "other"
    other.write_bytes(b"user")
    target.symlink_to(other)
    with caplog.at_level(logging.WARNING):
        await integration._register_static_path(hass)
    assert target.is_symlink() and other.read_bytes() == b"user"
    assert "manual review" in caplog.text
    target.unlink()
    source.unlink()
    await integration._register_static_path(hass)
    assert not target.exists()
    other.unlink()
    target.parent.rmdir()
    source.write_bytes(b"first")
    await integration._register_static_path(hass)
    assert not target.parent.exists()


async def test_fallback_failed_atomic_replace_preserves_old_copy(fallback, monkeypatch, caplog):
    hass, source, target = fallback
    await integration._register_static_path(hass)
    source.write_bytes(b"second")

    def fail_replace(*args):
        raise OSError("disk error")

    monkeypatch.setattr(integration, "_exchange_fallback", fail_replace)
    with caplog.at_level(logging.WARNING):
        await integration._register_static_path(hass)
    assert target.read_bytes() == b"first"
    assert "disk error" in caplog.text
    assert list(target.parent.iterdir()) == [target]
    monkeypatch.undo()
    await integration._async_sync_fallback(hass, source, target)
    assert target.read_bytes() == b"second"


@pytest.mark.parametrize("failure", ["exchange", "temp_create", "write", "recheck"])
async def test_fallback_pre_mutation_failure_restores_ownership_and_retries(
    fallback, monkeypatch, failure
):
    hass, source, target = fallback
    await integration._async_sync_fallback(hass, source, target)
    record = hass.data[integration.ARTIFACT_HASS_KEY].file
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
            await integration._async_sync_fallback(hass, source, target)
    assert target.read_bytes() == b"first"
    assert hass.data[integration.ARTIFACT_HASS_KEY].file == record
    hass.data.pop(integration.ARTIFACT_HASS_KEY)
    await integration._async_sync_fallback(hass, source, target)
    assert target.read_bytes() == b"second"


async def test_fallback_failed_initial_creation_remains_unowned(fallback, monkeypatch):
    hass, source, target = fallback

    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, "no space")

    with monkeypatch.context() as patch:
        patch.setattr(integration.tempfile, "mkstemp", fail)
        with pytest.raises(OSError):
            await integration._async_sync_fallback(hass, source, target)
    assert not target.exists()
    assert hass.data[integration.ARTIFACT_HASS_KEY].file is None
    await integration._async_sync_fallback(hass, source, target)
    assert target.read_bytes() == b"first"


async def test_fallback_post_exchange_failure_does_not_restore_ownership(fallback, monkeypatch):
    hass, source, target = fallback
    await integration._async_sync_fallback(hass, source, target)
    source.write_bytes(b"second")
    identity = integration._fallback_identity

    def fail_displaced(path):
        result = identity(path)
        if path.name.startswith(".junie-card-") and result and result[4] == (
            "a7937b64b8caa58f03721bb6bacf5c78cb235febe0e70b1b84cd99541461a08e"
        ):
            raise OSError("cannot verify displaced file")
        return result

    monkeypatch.setattr(integration, "_fallback_identity", fail_displaced)
    with pytest.raises(OSError):
        await integration._async_sync_fallback(hass, source, target)
    assert target.read_bytes() == b"first"
    assert hass.data[integration.ARTIFACT_HASS_KEY].file is None


async def test_fallback_preserves_external_replacement_during_update(fallback, monkeypatch):
    hass, source, target = fallback
    await integration._async_sync_fallback(hass, source, target)
    source.write_bytes(b"second")
    snapshot = integration._fallback_snapshot

    def replace_after_check(src, dst):
        result = snapshot(src, dst)
        if src == dst == target:
            replacement = dst.parent / "replacement"
            replacement.write_bytes(b"manual")
            os.replace(replacement, dst)
        return result

    monkeypatch.setattr(integration, "_fallback_snapshot", replace_after_check)
    with pytest.raises(OSError):
        await integration._async_sync_fallback(hass, source, target)
    assert target.read_bytes() == b"manual"
    assert hass.data[integration.ARTIFACT_HASS_KEY].file is None


async def test_fallback_pre_exchange_replacement_is_not_reowned(fallback, monkeypatch):
    hass, source, target = fallback
    await integration._async_sync_fallback(hass, source, target)
    source.write_bytes(b"second")
    snapshot = integration._fallback_snapshot

    def replace_before_check(src, dst):
        if src == dst == target:
            target.write_bytes(b"manual")
        return snapshot(src, dst)

    monkeypatch.setattr(integration, "_fallback_snapshot", replace_before_check)
    with pytest.raises(OSError):
        await integration._async_sync_fallback(hass, source, target)
    assert target.read_bytes() == b"manual"
    assert hass.data[integration.ARTIFACT_HASS_KEY].file is None


async def test_fallback_failed_recovery_identity_check_leaves_record_empty(fallback, monkeypatch):
    hass, source, target = fallback
    await integration._async_sync_fallback(hass, source, target)
    source.write_bytes(b"second")
    snapshot = integration._fallback_snapshot

    def replace_before_check(src, dst):
        if src == dst == target:
            target.unlink()
            target.symlink_to(source)
        return snapshot(src, dst)

    monkeypatch.setattr(integration, "_fallback_snapshot", replace_before_check)
    with pytest.raises(OSError):
        await integration._async_sync_fallback(hass, source, target)
    assert target.is_symlink()
    assert hass.data[integration.ARTIFACT_HASS_KEY].file is None


async def test_fallback_directory_swap_cannot_write_into_symlink(fallback, monkeypatch):
    hass, source, target = fallback
    await integration._async_sync_fallback(hass, source, target)
    source.write_bytes(b"second")
    evil = target.parent.parent / "elsewhere"
    evil.mkdir()
    (evil / target.name).write_bytes(b"manual")
    snapshot = integration._fallback_snapshot

    def replace_parent_after_check(src, dst):
        result = snapshot(src, dst)
        if src == dst == target:
            old_dir = target.parent.with_name("old-www")
            target.parent.rename(old_dir)
            for temp in old_dir.glob(".junie-card-*"):
                (evil / temp.name).write_bytes(b"fake temp")
            target.parent.symlink_to(evil, target_is_directory=True)
        return result

    monkeypatch.setattr(integration, "_fallback_snapshot", replace_parent_after_check)
    with pytest.raises(OSError):
        await integration._async_sync_fallback(hass, source, target)
    assert (evil / target.name).read_bytes() == b"manual"
    assert next(evil.glob(".junie-card-*")).read_bytes() == b"fake temp"
    assert hass.data[integration.ARTIFACT_HASS_KEY].file is None


async def test_fallback_preserves_replacement_during_rollback(fallback, monkeypatch):
    hass, source, target = fallback
    await integration._async_sync_fallback(hass, source, target)
    source.write_bytes(b"second")
    snapshot = integration._fallback_snapshot
    exchange = integration._exchange_fallback
    count = 0

    def replace_after_check(src, dst):
        result = snapshot(src, dst)
        if src == dst == target:
            replacement = dst.parent / "replacement"
            replacement.write_bytes(b"manual one")
            os.replace(replacement, dst)
        return result

    def replace_during_rollback(first, second):
        nonlocal count
        count += 1
        if count == 2:
            replacement = target.parent / "replacement"
            replacement.write_bytes(b"manual two")
            os.replace(replacement, target)
        exchange(first, second)

    monkeypatch.setattr(integration, "_fallback_snapshot", replace_after_check)
    monkeypatch.setattr(integration, "_exchange_fallback", replace_during_rollback)
    with pytest.raises(OSError):
        await integration._async_sync_fallback(hass, source, target)
    assert target.read_bytes() == b"manual one"
    assert [p.read_bytes() for p in target.parent.glob(".junie-card-*")] == [b"manual two"]


async def test_fallback_cancellation_waits_for_worker_and_serializes(fallback, monkeypatch):
    hass, source, target = fallback
    started = threading.Event()
    release = threading.Event()
    original = integration._publish_fallback

    def blocked(*args):
        started.set()
        assert release.wait(5)
        original(*args)

    monkeypatch.setattr(integration, "_publish_fallback", blocked)
    first = asyncio.create_task(integration._async_sync_fallback(hass, source, target))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        first.cancel()
        second = asyncio.create_task(integration._async_sync_fallback(hass, source, target))
        await asyncio.sleep(0)
        assert not first.done() and not second.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    await second
    assert target.read_bytes() == b"first"


def test_url_constants():
    """Verify base API URL constants."""
    assert BASE_URL == "https://junie.jetbrains.com"
    assert API_BASE_PATH == "/api/public"


def test_config_constants():
    """Verify configuration key constants."""
    assert CONF_COOKIE_HEADER == "cookie_header"
    assert CONF_STORAGE_STATE == "storage_state"
    assert CONF_STORAGE_TYPE == "storage_type"
    assert CONF_LOCAL_STORAGE_PATH == "local_storage_path"
    assert CONF_S3_ENDPOINT == "s3_endpoint"
    assert CONF_S3_BUCKET == "s3_bucket"
    assert CONF_S3_ACCESS_KEY == "s3_access_key"
    assert CONF_S3_SECRET_KEY == "s3_secret_key"
    assert CONF_S3_REGION == "s3_region"
    assert CONF_S3_PUBLIC_URL_BASE == "s3_public_url_base"


def test_storage_and_service_constants():
    """Verify storage types, defaults, and service names."""
    assert STORAGE_TYPE_LOCAL == "local"
    assert STORAGE_TYPE_S3 == "s3"
    assert DEFAULT_STORAGE_TYPE == STORAGE_TYPE_LOCAL
    assert DEFAULT_LOCAL_STORAGE_PATH == "junie_remote/transcripts"
    assert DEFAULT_POLL_INTERVAL == 10

    assert SERVICE_SEND_PROMPT == "send_prompt"
    assert SERVICE_SEND_PLAN_PROMPT == "send_plan_prompt"
    assert SERVICE_CONFIRM_PLAN == "confirm_plan"
    assert SERVICE_CANCEL_TASK == "cancel_task"
    assert SERVICE_CANCEL == "cancel"
    assert SERVICE_TOGGLE_BRAVE_MODE == "toggle_brave_mode"
    assert SERVICE_SELECT_MODEL == "select_model"
    assert SERVICE_RESPOND == "respond"
    assert SERVICE_RESPOND_REQUEST == "respond_request"
    assert SERVICE_KICK_CLIENT == "kick_client"
