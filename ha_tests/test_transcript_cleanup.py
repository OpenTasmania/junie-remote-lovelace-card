# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Real Home Assistant proof of transcript cleanup and pause/resume services."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.junie_remote import _async_register_services
from custom_components.junie_remote.const import (
    CONF_S3_ACCESS_KEY,
    CONF_S3_BUCKET,
    CONF_S3_ENDPOINT,
    CONF_S3_SECRET_KEY,
    CONF_STORAGE_TYPE,
    DOMAIN,
    SERVICE_CLEANUP_TRANSCRIPTS,
    SERVICE_RESUME_TRANSCRIPTS,
    STORAGE_TYPE_S3,
)
from custom_components.junie_remote.coordinator import JunieRemoteCoordinator
from custom_components.junie_remote.models import (
    ChatSessionState,
    TunnelInfo,
    TunnelMetadata,
)
from custom_components.junie_remote.storage import (
    LocalTranscriptStorage,
    S3TranscriptStorage,
    TranscriptDocument,
    TranscriptStorageError,
)
from custom_components.junie_remote.transcript_inventory import (
    INVENTORY_HASS_KEY,
    TranscriptInventory,
)


def make_doc(host_key: str, label: str) -> TranscriptDocument:
    tunnel = TunnelInfo(
        tunnel_id=f"tunnel-{label}",
        connected_clients=1,
        metadata=TunnelMetadata(user_name=label, os_name="linux"),
    )
    state = ChatSessionState(
        title=f"Plan {label}",
        history=[{"type": "user-prompt", "prompt": f"Task {label}"}],
    )
    return TranscriptDocument.build(
        host_key, tunnel, state, "connected", "2026-01-01T00:00:00Z"
    )


@pytest.fixture
async def cleanup_env(hass, hass_admin_user, hass_read_only_user, tmp_path):
    assert await async_setup_component(hass, "auth", {})
    _async_register_services(hass)

    inventory = hass.data[INVENTORY_HASS_KEY] = TranscriptInventory(hass)
    await inventory.async_load()

    entry_a = MockConfigEntry(domain=DOMAIN, entry_id="entry_alpha_123")
    entry_b = MockConfigEntry(domain=DOMAIN, entry_id="entry_beta_456")
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)

    root = tmp_path / "transcripts"
    root.mkdir()
    www = tmp_path / "www"
    www.mkdir()

    storage_a = LocalTranscriptStorage(
        base_dir=root, entry_id=entry_a.entry_id, inventory=inventory, public_roots=[www]
    )
    storage_b = LocalTranscriptStorage(
        base_dir=root, entry_id=entry_b.entry_id, inventory=inventory, public_roots=[www]
    )

    coord_a = JunieRemoteCoordinator(hass, MagicMock(), storage_a, auto_connect=False)
    coord_b = JunieRemoteCoordinator(hass, MagicMock(), storage_b, auto_connect=False)

    hass.data.setdefault(DOMAIN, {})[entry_a.entry_id] = coord_a
    hass.data[DOMAIN][entry_b.entry_id] = coord_b

    # Save docs for both entries
    doc_a1 = make_doc("host-a1", "a1")
    doc_a2 = make_doc("host-a2", "a2")
    doc_b1 = make_doc("host-b1", "b1")

    await storage_a.async_save_transcript(doc_a1)
    await storage_a.async_save_transcript(doc_a2)
    await storage_b.async_save_transcript(doc_b1)

    admin_context = Context(user_id=hass_admin_user.id)
    non_admin_context = Context(user_id=hass_read_only_user.id)

    return SimpleNamespace(
        hass=hass,
        inventory=inventory,
        entry_a=entry_a,
        entry_b=entry_b,
        storage_a=storage_a,
        storage_b=storage_b,
        coord_a=coord_a,
        coord_b=coord_b,
        root=root,
        admin_context=admin_context,
        non_admin_context=non_admin_context,
    )


async def test_cleanup_and_resume_admin_boundary(cleanup_env):
    hass = cleanup_env.hass
    entry_id = cleanup_env.entry_a.entry_id

    # 1. No context
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEANUP_TRANSCRIPTS,
            {"entry_id": entry_id, "confirm": True},
            blocking=True,
        )

    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_RESUME_TRANSCRIPTS,
            {"entry_id": entry_id},
            blocking=True,
        )

    # 2. Non-admin context
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEANUP_TRANSCRIPTS,
            {"entry_id": entry_id, "confirm": True},
            context=cleanup_env.non_admin_context,
            blocking=True,
        )

    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_RESUME_TRANSCRIPTS,
            {"entry_id": entry_id},
            context=cleanup_env.non_admin_context,
            blocking=True,
        )


async def test_cleanup_requires_confirm_and_valid_entry(cleanup_env):
    hass = cleanup_env.hass
    admin = cleanup_env.admin_context
    entry_id = cleanup_env.entry_a.entry_id

    # Missing confirm
    with pytest.raises(HomeAssistantError, match="requires explicit confirmation"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEANUP_TRANSCRIPTS,
            {"entry_id": entry_id},
            context=admin,
            blocking=True,
        )

    # confirm: false
    with pytest.raises(HomeAssistantError, match="requires explicit confirmation"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEANUP_TRANSCRIPTS,
            {"entry_id": entry_id, "confirm": False},
            context=admin,
            blocking=True,
        )

    # Missing entry_id
    with pytest.raises(HomeAssistantError, match="entry_id.*is required"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEANUP_TRANSCRIPTS,
            {"confirm": True},
            context=admin,
            blocking=True,
        )

    # Unknown entry_id
    with pytest.raises(HomeAssistantError, match="not found"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEANUP_TRANSCRIPTS,
            {"entry_id": "nonexistent_entry_id", "confirm": True},
            context=admin,
            blocking=True,
        )


async def test_cleanup_deletes_exact_local_files_and_preserves_other_entry(cleanup_env):
    hass = cleanup_env.hass
    admin = cleanup_env.admin_context
    inv = cleanup_env.inventory
    root = cleanup_env.root
    entry_a = cleanup_env.entry_a.entry_id
    entry_b = cleanup_env.entry_b.entry_id

    # Verify initial state: 6 files for entry A, 3 files for entry B
    assert len(inv.local_records(entry_a)) == 6
    assert len(inv.local_records(entry_b)) == 3
    assert (root / entry_a / "host-a1" / "latest.json").is_file()
    assert (root / entry_b / "host-b1" / "latest.json").is_file()

    # Perform cleanup for entry A
    await hass.services.async_call(
        DOMAIN,
        SERVICE_CLEANUP_TRANSCRIPTS,
        {"entry_id": entry_a, "confirm": True},
        context=admin,
        blocking=True,
    )

    # Entry A's records and files are removed
    assert inv.local_records(entry_a) == []
    assert inv.is_paused(entry_a) is True
    assert not (root / entry_a).exists()

    # Entry B's records and files are completely intact
    assert len(inv.local_records(entry_b)) == 3
    assert inv.is_paused(entry_b) is False
    assert (root / entry_b / "host-b1" / "latest.json").is_file()


async def test_cleanup_preserves_unrelated_modified_and_symlinked_files(cleanup_env):
    hass = cleanup_env.hass
    admin = cleanup_env.admin_context
    inv = cleanup_env.inventory
    root = cleanup_env.root
    entry_a = cleanup_env.entry_a.entry_id

    host_dir = root / entry_a / "host-a1"
    unrelated_file = host_dir / "unrelated.txt"
    unrelated_file.write_text("user data")

    # Modify latest.json (digest mismatch)
    latest_json = host_dir / "latest.json"
    latest_json.write_text('{"modified": true}')

    # Replace latest.md with a symlink
    latest_md = host_dir / "latest.md"
    target_file = root / "target.md"
    target_file.write_text("target")
    latest_md.unlink()
    latest_md.symlink_to(target_file)

    # Cleanup must report partial failure
    with pytest.raises(HomeAssistantError, match="partially failed"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEANUP_TRANSCRIPTS,
            {"entry_id": entry_a, "confirm": True},
            context=admin,
            blocking=True,
        )

    # Unrelated, modified, and symlinked files were preserved
    assert unrelated_file.is_file()
    assert latest_json.is_file()
    assert latest_md.is_symlink()

    # Unmodified files (e.g. tunnel-a1.json, host-a2 files) WERE deleted
    assert not (host_dir / "tunnel-a1.json").exists()
    assert not (root / entry_a / "host-a2").exists()

    # Inventory only retained records for the files that could not be deleted
    recs = inv.local_records(entry_a)
    assert len(recs) == 2
    paths = {r["path"] for r in recs}
    assert str(latest_json) in paths
    assert str(latest_md) in paths


async def test_writer_pause_persists_and_resumes(cleanup_env, hass):
    admin = cleanup_env.admin_context
    inv = cleanup_env.inventory
    storage_a = cleanup_env.storage_a
    entry_a = cleanup_env.entry_a.entry_id

    # Clean up entry A
    await hass.services.async_call(
        DOMAIN,
        SERVICE_CLEANUP_TRANSCRIPTS,
        {"entry_id": entry_a, "confirm": True},
        context=admin,
        blocking=True,
    )
    assert inv.is_paused(entry_a) is True

    # Writing while paused fails
    doc = make_doc("host-a1", "a1")
    with pytest.raises(TranscriptStorageError, match="writes are paused"):
        await storage_a.async_save_transcript(doc)

    # Simulate restart: create new inventory instance loading same store
    fresh_inv = TranscriptInventory(hass)
    await fresh_inv.async_load()
    assert fresh_inv.is_paused(entry_a) is True

    # Resume entry A
    await hass.services.async_call(
        DOMAIN,
        SERVICE_RESUME_TRANSCRIPTS,
        {"entry_id": entry_a},
        context=admin,
        blocking=True,
    )
    assert inv.is_paused(entry_a) is False

    # Writes succeed again
    res = await storage_a.async_save_transcript(doc)
    assert res.json_url.startswith("/api/junie_remote/transcripts/")


def _s3_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "DeleteObject")


async def test_s3_cleanup_versioned_and_unversioned_replacement(
    hass, hass_admin_user
):
    assert await async_setup_component(hass, "auth", {})
    _async_register_services(hass)

    inv = hass.data[INVENTORY_HASS_KEY] = TranscriptInventory(hass)
    await inv.async_load()

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_s3_789",
        data={CONF_STORAGE_TYPE: STORAGE_TYPE_S3},
    )
    entry.add_to_hass(hass)

    mock_s3 = MagicMock()
    mock_s3.meta.endpoint_url = None
    mock_s3.put_object.return_value = {"ETag": '"abc123etag"', "VersionId": "v1"}
    mock_s3.generate_presigned_url.return_value = "https://s3.example.com/item"

    storage = S3TranscriptStorage(
        bucket="mybucket",
        s3_client=mock_s3,
        entry_id=entry.entry_id,
        inventory=inv,
    )
    coord = JunieRemoteCoordinator(hass, MagicMock(), storage, auto_connect=False)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord

    doc = make_doc("host-s3", "s3")
    await storage.async_save_transcript(doc)

    s3_recs = inv.s3_records(entry.entry_id)
    assert len(s3_recs) == 3
    assert s3_recs[0]["etag"] == "abc123etag"
    assert s3_recs[0]["version_id"] == "v1"

    admin = Context(user_id=hass_admin_user.id)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_CLEANUP_TRANSCRIPTS,
        {"entry_id": entry.entry_id, "confirm": True},
        context=admin,
        blocking=True,
    )

    assert mock_s3.head_object.call_count == 0
    assert mock_s3.delete_object.call_count == 3
    for call in mock_s3.delete_object.call_args_list:
        assert call.kwargs["VersionId"] == "v1"
        assert "IfMatch" not in call.kwargs
    assert inv.s3_records(entry.entry_id) == []
    assert inv.is_paused(entry.entry_id) is True

    await inv.async_resume(entry.entry_id)
    mock_s3.put_object.return_value = {"ETag": '"old-etag"'}
    await storage.async_save_transcript(doc)
    assert len(inv.s3_records(entry.entry_id)) == 3
    assert all(r["version_id"] is None for r in inv.s3_records(entry.entry_id))

    mock_s3.delete_object.reset_mock()
    with pytest.raises(HomeAssistantError, match="partially failed.*manual review"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEANUP_TRANSCRIPTS,
            {"entry_id": entry.entry_id, "confirm": True},
            context=admin,
            blocking=True,
        )

    mock_s3.delete_object.assert_not_called()
    assert len(inv.s3_records(entry.entry_id)) == 3


async def test_s3_cleanup_missing_etag_and_endpoint_mismatch(
    hass, hass_admin_user
):
    assert await async_setup_component(hass, "auth", {})
    _async_register_services(hass)

    inv = hass.data[INVENTORY_HASS_KEY] = TranscriptInventory(hass)
    await inv.async_load()
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_s3_identity",
        data={CONF_STORAGE_TYPE: STORAGE_TYPE_S3},
    )
    entry.add_to_hass(hass)
    admin = Context(user_id=hass_admin_user.id)

    mock_s3 = MagicMock()
    mock_s3.meta.endpoint_url = "https://minio-b.example"
    storage = S3TranscriptStorage(
        bucket="mybucket",
        endpoint_url="https://minio-b.example",
        s3_client=mock_s3,
        entry_id=entry.entry_id,
        inventory=inv,
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = JunieRemoteCoordinator(
        hass, MagicMock(), storage, auto_connect=False
    )

    await inv.async_record_s3(
        entry.entry_id,
        [
            {
                "endpoint": "https://minio-b.example",
                "bucket": "mybucket",
                "key": "missing-etag.json",
                "version_id": None,
                "etag": "",
            },
            {
                "endpoint": "https://minio-a.example",
                "bucket": "mybucket",
                "key": "other-endpoint.json",
                "version_id": None,
                "etag": "abc",
            },
        ],
    )

    with pytest.raises(HomeAssistantError, match="manual review"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEANUP_TRANSCRIPTS,
            {"entry_id": entry.entry_id, "confirm": True},
            context=admin,
            blocking=True,
        )
    assert mock_s3.delete_object.call_count == 0
    assert len(inv.s3_records(entry.entry_id)) == 2


async def test_s3_cleanup_without_loaded_coordinator(hass, hass_admin_user):
    assert await async_setup_component(hass, "auth", {})
    _async_register_services(hass)

    inv = hass.data[INVENTORY_HASS_KEY] = TranscriptInventory(hass)
    await inv.async_load()
    endpoint = "https://minio.example"
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_unloaded_s3",
        data={
            CONF_STORAGE_TYPE: STORAGE_TYPE_S3,
            CONF_S3_BUCKET: "b",
            CONF_S3_ENDPOINT: endpoint,
            CONF_S3_ACCESS_KEY: "ak",
            CONF_S3_SECRET_KEY: "sk",
        },
    )
    entry.add_to_hass(hass)
    await inv.async_record_s3(
        entry.entry_id,
        [
            {
                "endpoint": endpoint,
                "bucket": "b",
                "key": "k.json",
                "version_id": "v1",
                "etag": "abc",
            }
        ],
    )
    mock_s3 = MagicMock()
    mock_s3.meta.endpoint_url = endpoint
    admin = Context(user_id=hass_admin_user.id)

    with pytest.MonkeyPatch.context() as mp:
        session = MagicMock()
        session.client.return_value = mock_s3
        mp.setattr(
            "custom_components.junie_remote.storage.boto3.session.Session",
            MagicMock(return_value=session),
        )
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEANUP_TRANSCRIPTS,
            {"entry_id": entry.entry_id, "confirm": True},
            context=admin,
            blocking=True,
        )

    mock_s3.delete_object.assert_called_once_with(
        Bucket="b", Key="k.json", VersionId="v1"
    )
    assert inv.s3_records(entry.entry_id) == []
    assert entry.entry_id not in hass.data.get(DOMAIN, {})
