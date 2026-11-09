# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Unit tests for transcript storage driver (local & S3)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from custom_components.junie_remote.const import (
    CONF_LOCAL_STORAGE_PATH,
    CONF_S3_ACCESS_KEY,
    CONF_S3_BUCKET,
    CONF_S3_ENDPOINT,
    CONF_S3_PUBLIC_URL_BASE,
    CONF_S3_REGION,
    CONF_S3_SECRET_KEY,
    CONF_STORAGE_TYPE,
    DOMAIN,
    STORAGE_TYPE_LOCAL,
    STORAGE_TYPE_S3,
)
from custom_components.junie_remote.ha_compat import (
    ConfigEntry,
    HomeAssistant,
    HomeAssistantError,
    Store,
)
from custom_components.junie_remote.models import (
    ChatSessionState,
    ModelOption,
    ModelSelectionState,
    PlanProposal,
    TunnelInfo,
    TunnelMetadata,
)
from custom_components.junie_remote.storage import (
    LocalTranscriptStorage,
    S3TranscriptStorage,
    TranscriptDocument,
    TranscriptNotFoundError,
    TranscriptOwnershipError,
    TranscriptPublicPathError,
    TranscriptResult,
    TranscriptStorageError,
    _delete_owned_local_file,
    async_cleanup_entry_transcripts,
    create_storage_driver,
)
from custom_components.junie_remote.transcript_inventory import (
    TranscriptInventory,
    TranscriptInventoryError,
)


def _create_sample_doc(
    host_key: str = "alice_linux_repo",
    tunnel_id: str = "tun-123",
    status: str = "connected",
) -> TranscriptDocument:
    """Helper to build a sample TranscriptDocument with rich content."""
    meta = TunnelMetadata(
        user_name="alice",
        os_name="Linux",
        current_directory="/home/alice/repo",
        git_repo_url="git@gitlab.com:opentasmania/repo.git",
        git_branch="feature/stage-3",
    )
    tunnel = TunnelInfo(tunnel_id=tunnel_id, connected_clients=1, metadata=meta)

    model_sel = ModelSelectionState(
        current_model_id="claude-3-7-sonnet",
        current_effort_id="high",
        models=[
            ModelOption(
                id="claude-3-7-sonnet",
                name="Claude 3.7 Sonnet",
                supported_efforts=[{"id": "high", "name": "High"}],
            ),
            ModelOption(
                id="gpt-4o",
                name="GPT-4o",
                supported_efforts=[],
            ),
        ],
    )

    plan = PlanProposal(
        seq=5,
        ready_for_review=True,
        show_actions=True,
        plan_file_path="/home/alice/repo/PLAN.md",
        sections=[
            {
                "title": "Architecture Overview",
                "description": "Implement storage driver",
                "tasks": [
                    {"title": "Implement LocalTranscriptStorage", "completed": True},
                    {"title": "Implement S3TranscriptStorage", "completed": False},
                ],
            }
        ],
        delivery_steps=[
            {
                "name": "Stage 3",
                "description": "Storage driver and tests",
                "status": "in-progress",
            }
        ],
    )

    chat_state = ChatSessionState(
        title="Develop Stage 3 Storage",
        git_branch="feature/stage-3",
        working_dir="/home/alice/repo",
        session_status="idle",
        can_send_prompt=True,
        brave_mode=True,
        has_plan=True,
        plan_proposal=plan,
        model_selection=model_sel,
        history=[
            {"type": "user-prompt", "prompt": "Please implement Stage 3"},
            {
                "type": "user-response",
                "displayText": "Approved plan proposal",
                "response": {"method": "approve"},
            },
            {
                "type": "step",
                "name": "Create file",
                "status": "success",
                "text": "Wrote storage.py",
                "result": "File created with 400 lines",
                "changesSummary": "diff --git a/storage.py b/storage.py\n+new file",
            },
            {
                "type": "step",
                "name": "Format code",
                "status": "success",
                "text": "Ran ruff check",
                "result": {"passed": True},
                "changesSummary": [
                    {
                        "filePath": "custom_components/junie_remote/storage.py",
                        "diff": "@@ -1,5 +1,5 @@",
                    }
                ],
            },
            {"type": "system-message", "text": "Junie agent initialized"},
            {"type": "skills-status", "status": "Ready", "skills": "python, bash"},
        ],
        progressing_steps=[
            {"name": "pytest", "text": "Running tests/test_storage.py"}
        ],
        active_requests=[
            {"type": "confirmation", "message": "Confirm git commit"}
        ],
    )

    return TranscriptDocument.build(
        host_key=host_key,
        tunnel=tunnel,
        chat_state=chat_state,
        connection_status=status,
        updated_at="2026-11-07T00:00:00Z",
    )


def test_transcript_result_dataclass() -> None:
    """Test TranscriptResult dataclass initialization and attributes."""
    res = TranscriptResult(
        json_url="/local/junie_remote/host/latest.json?t=1000",
        md_url="/local/junie_remote/host/latest.md?t=1000",
        updated_at="2026-11-07T00:00:00Z",
        last_step_preview="User: Hello",
    )
    assert res.json_url == "/local/junie_remote/host/latest.json?t=1000"
    assert res.md_url == "/local/junie_remote/host/latest.md?t=1000"
    assert res.updated_at == "2026-11-07T00:00:00Z"
    assert res.last_step_preview == "User: Hello"


def test_transcript_document_empty() -> None:
    """Test minimal TranscriptDocument with default/empty state."""
    tunnel = TunnelInfo(tunnel_id="tun-empty")
    chat_state = ChatSessionState()
    doc = TranscriptDocument(
        host_key="empty_host",
        tunnel=tunnel,
        chat_state=chat_state,
        connection_status="disconnected",
        updated_at="2026-11-07T00:00:00Z",
    )

    data = doc.to_dict()
    assert data["host_key"] == "empty_host"
    assert data["tunnel_id"] == "tun-empty"
    assert data["updated_at"] == "2026-11-07T00:00:00Z"
    assert data["connection_status"] == "disconnected"
    assert data["session_status"] == "idle"
    assert data["can_send_prompt"] is True
    assert data["brave_mode"] is False
    assert data["has_plan"] is False
    assert data["metadata"]["title"] == ""
    assert data["metadata"]["git_repo"] == ""
    assert data["metadata"]["git_branch"] == ""
    assert data["metadata"]["working_dir"] == ""
    assert data["metadata"]["user_name"] == ""
    assert data["metadata"]["os_name"] == ""
    assert data["history"] == []
    assert data["progressing_steps"] == []
    assert data["plan_proposal"] is None
    assert data["active_requests"] == []

    # Test Markdown rendering
    md = doc.render_markdown()
    assert "# Junie Session Transcript: Host: empty_host" in md
    assert "- **Host Key:** `empty_host`" in md
    assert "- **Tunnel ID:** `tun-empty`" in md
    assert "*No history recorded.*" in md

    # Test preview
    preview = doc.extract_last_step_preview()
    assert preview == "No activity recorded"


def test_transcript_document_rich_to_dict_and_markdown() -> None:
    """Test rich TranscriptDocument serialization and Markdown rendering."""
    doc = _create_sample_doc()

    # 1. to_dict & to_json
    data = doc.to_dict()
    assert data["host_key"] == "alice_linux_repo"
    assert data["tunnel_id"] == "tun-123"
    assert data["updated_at"] == "2026-11-07T00:00:00Z"
    assert data["connection_status"] == "connected"
    assert data["session_status"] == "idle"
    assert data["can_send_prompt"] is True
    assert data["brave_mode"] is True
    assert data["has_plan"] is True

    # Metadata
    meta = data["metadata"]
    assert meta["title"] == "Develop Stage 3 Storage"
    assert meta["git_repo"] == "git@gitlab.com:opentasmania/repo.git"
    assert meta["git_branch"] == "feature/stage-3"
    assert meta["working_dir"] == "/home/alice/repo"
    assert meta["user_name"] == "alice"
    assert meta["os_name"] == "Linux"

    # Model Selection
    model_sel = data["model_selection"]
    assert model_sel["current_model_id"] == "claude-3-7-sonnet"
    assert model_sel["current_effort_id"] == "high"
    assert len(model_sel["options"]) == 2
    assert model_sel["options"][0]["value"] == "claude-3-7-sonnet:high"

    # Plan proposal
    assert data["plan_proposal"] is not None
    assert data["plan_proposal"]["seq"] == 5
    assert len(data["plan_proposal"]["sections"]) == 1
    assert len(data["plan_proposal"]["deliverySteps"]) == 1

    # History & steps
    assert len(data["history"]) == 6
    assert len(data["progressing_steps"]) == 1
    assert len(data["active_requests"]) == 1

    # JSON serialization roundtrip
    raw_json = doc.to_json()
    loaded = json.loads(raw_json)
    assert loaded["host_key"] == "alice_linux_repo"
    assert loaded["metadata"]["title"] == "Develop Stage 3 Storage"

    # 2. render_markdown
    md = doc.render_markdown()
    assert "# Junie Session Transcript: Develop Stage 3 Storage" in md
    assert "- **Host Key:** `alice_linux_repo`" in md
    assert "- **Tunnel ID:** `tun-123`" in md
    assert "- **Connection Status:** `connected`" in md
    assert "- **Session Status:** `idle`" in md
    assert "- **User:** `alice`" in md
    assert "- **OS:** `Linux`" in md
    assert "- **Repository:** `git@gitlab.com:opentasmania/repo.git`" in md
    assert "- **Branch:** `feature/stage-3`" in md
    assert "- **Working Directory:** `/home/alice/repo`" in md
    assert "- **Model:** `claude-3-7-sonnet (high)`" in md
    assert "- **Brave Mode:** `Enabled`" in md
    assert "- **Can Send Prompt:** `Yes`" in md

    # Plan Proposal in MD
    assert "## 📋 Plan Proposal" in md
    assert "- **Plan File:** `/home/alice/repo/PLAN.md`" in md
    assert "- **Ready for Review:** `Yes`" in md
    assert "#### Architecture Overview" in md
    assert "- [x] Implement LocalTranscriptStorage" in md
    assert "- [ ] Implement S3TranscriptStorage" in md
    assert "### Delivery Steps" in md
    assert "1. **Stage 3** (in-progress): Storage driver and tests" in md

    # History in MD
    assert "## 💬 Conversation History" in md
    assert "### 👤 User Prompt" in md
    assert "Please implement Stage 3" in md
    assert "### 💬 User Response" in md
    assert "Approved plan proposal" in md
    assert "### ⚙️ Create file" in md
    assert "*Status: success*" in md
    assert "Wrote storage.py" in md
    assert "File created with 400 lines" in md
    assert "```diff\ndiff --git a/storage.py b/storage.py\n+new file\n```" in md
    assert "### ⚙️ Format code" in md
    assert "custom_components/junie_remote/storage.py" in md
    assert "> ℹ️ **System**: Junie agent initialized" in md
    assert "> 🛠️ **Skills Status**: Ready" in md

    # Progressing Steps & Active Requests in MD
    assert "## ⏳ Progressing Steps" in md
    assert "- **pytest**: Running tests/test_storage.py" in md
    assert "## ❓ Active Requests" in md
    assert "- **confirmation**: Confirm git commit" in md


def test_extract_last_step_preview_variations() -> None:
    """Test extract_last_step_preview across various history and step types."""
    tunnel = TunnelInfo(tunnel_id="tun-test")

    # 1. Progressing step priority
    state1 = ChatSessionState(
        history=[{"type": "user-prompt", "prompt": "Previous prompt"}],
        progressing_steps=[{"name": "ruff check", "text": "Analyzing storage.py"}],
    )
    doc1 = TranscriptDocument("h1", tunnel, state1, "connected")
    assert doc1.extract_last_step_preview() == "[In Progress] ruff check: Analyzing storage.py"

    # 2. User prompt in history
    state2 = ChatSessionState(
        history=[{"type": "user-prompt", "prompt": "Fix bug in storage"}],
    )
    doc2 = TranscriptDocument("h2", tunnel, state2, "connected")
    assert doc2.extract_last_step_preview() == "User: Fix bug in storage"

    # 3. User response in history
    state3 = ChatSessionState(
        history=[{"type": "user-response", "displayText": "Confirmed action"}],
    )
    doc3 = TranscriptDocument("h3", tunnel, state3, "connected")
    assert doc3.extract_last_step_preview() == "User response: Confirmed action"

    # 4. System message
    state4 = ChatSessionState(
        history=[{"type": "system-message", "text": "Session timed out"}],
    )
    doc4 = TranscriptDocument("h4", tunnel, state4, "disconnected")
    assert doc4.extract_last_step_preview() == "System: Session timed out"

    # 5. Skills status
    state5 = ChatSessionState(
        history=[{"type": "skills-status", "status": "All tools enabled"}],
    )
    doc5 = TranscriptDocument("h5", tunnel, state5, "connected")
    assert doc5.extract_last_step_preview() == "Skills: All tools enabled"

    # 6. Step with name and result
    state6 = ChatSessionState(
        history=[{"type": "step", "name": "Build", "result": "Success"}],
    )
    doc6 = TranscriptDocument("h6", tunnel, state6, "connected")
    assert doc6.extract_last_step_preview() == "Build: Success"

    # 7. Truncation to 200 characters
    long_msg = "X" * 300
    state7 = ChatSessionState(
        history=[{"type": "user-prompt", "prompt": long_msg}],
    )
    doc7 = TranscriptDocument("h7", tunnel, state7, "connected")
    preview = doc7.extract_last_step_preview()
    assert len(preview) == 200
    assert preview.endswith("...")
    assert preview.startswith("User: XXXX")


def _local_storage(
    tmp_path: Path, entry_id: str = "entry-a", inventory: TranscriptInventory | None = None,
    public_roots: list[Path] | None = None, base: Path | None = None,
) -> LocalTranscriptStorage:
    return LocalTranscriptStorage(
        base_dir=base or tmp_path / "private",
        entry_id=entry_id,
        inventory=inventory or TranscriptInventory(HomeAssistant()),
        public_roots=public_roots if public_roots is not None else [tmp_path / "www"],
    )


@pytest.mark.asyncio
async def test_local_transcript_storage(tmp_path: Path) -> None:
    """Local transcripts are private, owned, and exposed only via the API URL."""
    doc = _create_sample_doc(host_key="my_local_host", tunnel_id="tun-abc-456")
    storage = _local_storage(tmp_path)

    result = await storage.async_save_transcript(doc)

    host_dir = tmp_path / "private" / "entry-a" / "my_local_host"
    assert host_dir.is_dir()
    latest_json_path = host_dir / "latest.json"
    latest_md_path = host_dir / "latest.md"
    tunnel_json_path = host_dir / "tunnel-tun-abc-456.json"
    assert latest_json_path.is_file()
    assert latest_md_path.is_file()
    assert tunnel_json_path.is_file()
    assert oct(latest_json_path.stat().st_mode & 0o777) == "0o600"
    assert not list(host_dir.glob("*.tmp"))

    assert json.loads(latest_json_path.read_text(encoding="utf-8")) == doc.to_dict()
    assert latest_md_path.read_text(encoding="utf-8") == doc.render_markdown()
    assert json.loads(tunnel_json_path.read_text(encoding="utf-8")) == doc.to_dict()

    prefix = "/api/junie_remote/transcripts/entry-a/my_local_host"
    assert result.json_url.startswith(f"{prefix}/json?t=")
    assert result.md_url.startswith(f"{prefix}/md?t=")
    assert "/local/" not in result.json_url + result.md_url
    assert "authSig" not in result.json_url + result.md_url
    assert result.updated_at == "2026-11-07T00:00:00Z"
    assert result.last_step_preview == "[In Progress] pytest: Running tests/test_storage.py"

    records = storage.inventory.local_records("entry-a")
    assert sorted(r["path"] for r in records) == sorted(
        str(p.resolve()) for p in (latest_json_path, latest_md_path, tunnel_json_path)
    )
    assert await storage.async_read_transcript("my_local_host", "json") == (
        doc.to_json().encode()
    )
    assert await storage.async_read_transcript("my_local_host", "md") == (
        doc.render_markdown().encode()
    )


@pytest.mark.asyncio
async def test_local_storage_refreshes_owned_files_and_prunes_old_digests(
    tmp_path: Path,
) -> None:
    storage = _local_storage(tmp_path)
    first = _create_sample_doc(host_key="h", tunnel_id="t")
    await storage.async_save_transcript(first)
    second = _create_sample_doc(host_key="h", tunnel_id="t", status="disconnected")
    await storage.async_save_transcript(second)
    assert len(storage.inventory.local_records("entry-a")) == 3
    assert await storage.async_read_transcript("h", "json") == second.to_json().encode()


@pytest.mark.asyncio
async def test_local_save_prepares_all_three_files_before_replace_with_two_inventory_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _local_storage(tmp_path)
    await storage.inventory.async_load()
    original_save = storage.inventory._store.async_save
    original_write = LocalTranscriptStorage._write_owned
    writes = 0
    first_write_records = []

    async def counted_save(data: Any) -> None:
        nonlocal writes
        writes += 1
        await original_save(data)

    def first_write(*args: Any) -> Path:
        if not first_write_records:
            first_write_records.extend(storage.inventory.local_records("entry-a"))
        return original_write(*args)

    monkeypatch.setattr(storage.inventory._store, "async_save", counted_save)
    monkeypatch.setattr(LocalTranscriptStorage, "_write_owned", staticmethod(first_write))
    await storage.async_save_transcript(_create_sample_doc(host_key="h", tunnel_id="t"))

    assert len(first_write_records) == 3
    assert writes == 1
    first_write_records.clear()
    writes = 0
    await storage.async_save_transcript(
        _create_sample_doc(host_key="h", tunnel_id="t", status="disconnected")
    )
    assert len(first_write_records) == 6  # old and new intents until replacements
    assert writes == 2
    assert len(storage.inventory.local_records("entry-a")) == 3


@pytest.mark.asyncio
async def test_local_storage_inventory_survives_restart(tmp_path: Path) -> None:
    hass = HomeAssistant()
    first = _local_storage(tmp_path, inventory=TranscriptInventory(hass))
    doc = _create_sample_doc(host_key="h", tunnel_id="t")
    await first.async_save_transcript(doc)
    restarted = _local_storage(tmp_path, inventory=TranscriptInventory(hass))
    assert await restarted.async_read_transcript("h", "md") == doc.render_markdown().encode()
    await restarted.async_save_transcript(_create_sample_doc(host_key="h", tunnel_id="t"))


@pytest.mark.asyncio
async def test_local_storage_unowned_or_modified_destination_fails_closed(
    tmp_path: Path,
) -> None:
    storage = _local_storage(tmp_path)
    doc = _create_sample_doc(host_key="h", tunnel_id="t")
    await storage.async_save_transcript(doc)
    target = tmp_path / "private" / "entry-a" / "h" / "latest.md"
    target.write_text("someone else's data")
    with pytest.raises(TranscriptOwnershipError):
        await storage.async_save_transcript(doc)
    assert target.read_text() == "someone else's data"
    with pytest.raises(TranscriptNotFoundError):
        await storage.async_read_transcript("h", "md")

    other = _local_storage(tmp_path, entry_id="entry-b")
    foreign = tmp_path / "private" / "entry-b" / "h"
    foreign.mkdir(parents=True)
    (foreign / "latest.json").write_text("preexisting")
    with pytest.raises(TranscriptOwnershipError):
        await other.async_save_transcript(doc)
    assert (foreign / "latest.json").read_text() == "preexisting"
    assert other.inventory.local_records("entry-b") == []


@pytest.mark.asyncio
async def test_existing_identical_but_unowned_transcript_is_not_adopted(tmp_path: Path) -> None:
    doc = _create_sample_doc(host_key="h", tunnel_id="t")
    target = tmp_path / "private" / "entry-a" / "h" / "latest.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(doc.to_json().encode())
    storage = _local_storage(tmp_path)
    with pytest.raises(TranscriptOwnershipError):
        await storage.async_save_transcript(doc)
    assert target.read_bytes() == doc.to_json().encode()
    assert storage.inventory.local_records("entry-a") == []


@pytest.mark.asyncio
async def test_existing_unowned_tunnel_is_rejected_before_preparing_any_file(
    tmp_path: Path,
) -> None:
    doc = _create_sample_doc(host_key="h", tunnel_id="t")
    tunnel = tmp_path / "private" / "entry-a" / "h" / "tunnel-t.json"
    tunnel.parent.mkdir(parents=True)
    tunnel.write_bytes(doc.to_json().encode())
    storage = _local_storage(tmp_path)
    with pytest.raises(TranscriptOwnershipError):
        await storage.async_save_transcript(doc)
    assert not (tunnel.parent / "latest.json").exists()
    assert storage.inventory.local_records("entry-a") == []


@pytest.mark.asyncio
async def test_local_storage_refuses_symlinks(tmp_path: Path) -> None:
    storage = _local_storage(tmp_path)
    doc = _create_sample_doc(host_key="h", tunnel_id="t")
    await storage.async_save_transcript(doc)
    host_dir = tmp_path / "private" / "entry-a" / "h"
    secret = tmp_path / "secret.md"
    secret.write_text("secret")
    (host_dir / "latest.md").unlink()
    (host_dir / "latest.md").symlink_to(secret)
    with pytest.raises(TranscriptStorageError):
        await storage.async_save_transcript(doc)
    assert secret.read_text() == "secret"
    with pytest.raises(TranscriptNotFoundError):
        await storage.async_read_transcript("h", "md")

    # Host directory symlinked outside the entry root
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "private" / "entry-a" / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(TranscriptStorageError):
        await storage.async_save_transcript(_create_sample_doc(host_key="linked", tunnel_id="t"))
    assert list(outside.iterdir()) == []
    with pytest.raises(TranscriptNotFoundError):
        await storage.async_read_transcript("linked", "json")


@pytest.mark.asyncio
async def test_local_storage_rejects_public_roots_including_symlinks(tmp_path: Path) -> None:
    www = tmp_path / "www"
    (www / "junie_remote").mkdir(parents=True)
    doc = _create_sample_doc(host_key="h", tunnel_id="t")
    with pytest.raises(TranscriptPublicPathError):
        await _local_storage(tmp_path, base=www / "junie_remote").async_save_transcript(doc)
    link = tmp_path / "innocent"
    link.symlink_to(www, target_is_directory=True)
    with pytest.raises(TranscriptPublicPathError):
        await _local_storage(tmp_path, base=link).async_save_transcript(doc)
    assert list(www.rglob("*.json")) == []


@pytest.mark.asyncio
async def test_local_storage_identifiers_cannot_traverse(tmp_path: Path) -> None:
    storage = _local_storage(tmp_path)
    nasty = _create_sample_doc(host_key="../../escape", tunnel_id="../../tunnel/x")
    await storage.async_save_transcript(nasty)
    created = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert all((tmp_path / "private" / "entry-a") in p.parents for p in created)
    assert all(".." not in p.relative_to(tmp_path).parts for p in created)
    assert await storage.async_read_transcript("../../escape", "json")
    with pytest.raises(TranscriptNotFoundError):
        await storage.async_read_transcript("..", "json")
    with pytest.raises(TranscriptNotFoundError):
        await storage.async_read_transcript("h", "txt")


@pytest.mark.asyncio
async def test_local_storage_entries_are_isolated(tmp_path: Path) -> None:
    hass = HomeAssistant()
    inventory = TranscriptInventory(hass)
    a = _local_storage(tmp_path, "entry-a", inventory)
    b = _local_storage(tmp_path, "entry-b", inventory)
    await a.async_save_transcript(_create_sample_doc(host_key="host-a", tunnel_id="t"))
    with pytest.raises(TranscriptNotFoundError):
        await b.async_read_transcript("host-a", "json")
    assert inventory.local_records("entry-b") == []


@pytest.mark.asyncio
async def test_local_storage_fails_closed_when_inventory_unavailable(tmp_path: Path) -> None:
    class BrokenStore:
        async def async_load(self) -> Any:
            raise OSError("boom")

        async def async_save(self, data: Any) -> None:
            raise OSError("boom")

    inventory = TranscriptInventory(HomeAssistant())
    inventory._store = BrokenStore()  # type: ignore[assignment]
    storage = _local_storage(tmp_path, inventory=inventory)
    with pytest.raises(TranscriptInventoryError):
        await storage.async_save_transcript(_create_sample_doc())
    assert not (tmp_path / "private").exists()

    # Loadable but unwritable: no file is written
    inventory2 = TranscriptInventory(HomeAssistant())
    await inventory2.async_load()
    inventory2._store = BrokenStore()  # type: ignore[assignment]
    storage2 = _local_storage(tmp_path, inventory=inventory2)
    with pytest.raises(TranscriptInventoryError):
        await storage2.async_save_transcript(_create_sample_doc())
    assert not list((tmp_path / "private").rglob("latest.*"))
    assert inventory2.local_records("entry-a") == []


@pytest.mark.asyncio
async def test_inventory_corrupt_store_fails_closed() -> None:
    hass = HomeAssistant()
    await Store(hass, 1, "junie_remote_transcript_ownership").async_save({"entries": []})
    with pytest.raises(TranscriptInventoryError):
        await TranscriptInventory(hass).async_load()


@pytest.mark.asyncio
async def test_inventory_schema_has_s3_and_pause_slots() -> None:
    hass = HomeAssistant()
    inventory = TranscriptInventory(hass)
    await inventory.async_load()
    await inventory.async_prepare_local("e", "/p", "abc")
    saved = await Store(hass, 1, "junie_remote_transcript_ownership").async_load()
    assert saved == {
        "entries": {
            "e": {"local": [{"path": "/p", "sha256": "abc"}], "s3": [], "paused": False}
        }
    }


@pytest.mark.asyncio
async def test_s3_transcript_storage_presigned_urls() -> None:
    """Test S3TranscriptStorage uploads and presigned URL generation."""
    mock_s3 = MagicMock()
    mock_s3.generate_presigned_url.side_effect = (
        lambda method, Params, ExpiresIn: (
            f"https://s3.amazonaws.com/{Params['Bucket']}/{Params['Key']}?exp={ExpiresIn}"
        )
    )

    storage = S3TranscriptStorage(
        bucket="junie-transcripts-bucket",
        key_prefix="remote_sessions",
        presign_expiration=7200,
        s3_client=mock_s3,
    )

    doc = _create_sample_doc(host_key="s3_host_1", tunnel_id="tun-s3-1")
    result = await storage.async_save_transcript(doc)

    # Verify 3 objects uploaded
    assert mock_s3.put_object.call_count == 3
    put_calls = mock_s3.put_object.call_args_list

    # 1. latest.json
    call1 = put_calls[0].kwargs
    assert call1["Bucket"] == "junie-transcripts-bucket"
    assert call1["Key"] == "remote_sessions/s3_host_1/latest.json"
    assert call1["ContentType"] == "application/json"
    assert call1["Body"] == doc.to_json().encode("utf-8")

    # 2. latest.md
    call2 = put_calls[1].kwargs
    assert call2["Bucket"] == "junie-transcripts-bucket"
    assert call2["Key"] == "remote_sessions/s3_host_1/latest.md"
    assert call2["ContentType"] == "text/markdown; charset=utf-8"
    assert call2["Body"] == doc.render_markdown().encode("utf-8")

    # 3. <tunnel_id>.json
    call3 = put_calls[2].kwargs
    assert call3["Bucket"] == "junie-transcripts-bucket"
    assert call3["Key"] == "remote_sessions/s3_host_1/tun-s3-1.json"
    assert call3["ContentType"] == "application/json"
    assert call3["Body"] == doc.to_json().encode("utf-8")

    # Verify presigned URL calls
    assert mock_s3.generate_presigned_url.call_count == 2
    presign_calls = mock_s3.generate_presigned_url.call_args_list

    assert presign_calls[0].kwargs["ExpiresIn"] == 7200
    assert (
        presign_calls[0].kwargs["Params"]["Key"]
        == "remote_sessions/s3_host_1/latest.json"
    )
    assert (
        presign_calls[1].kwargs["Params"]["Key"]
        == "remote_sessions/s3_host_1/latest.md"
    )

    assert result.json_url == (
        "https://s3.amazonaws.com/junie-transcripts-bucket/remote_sessions/s3_host_1/latest.json?exp=7200"
    )
    assert result.md_url == (
        "https://s3.amazonaws.com/junie-transcripts-bucket/remote_sessions/s3_host_1/latest.md?exp=7200"
    )


@pytest.mark.asyncio
async def test_s3_transcript_storage_public_url_base() -> None:
    """Test S3TranscriptStorage with public CDN URL base without presigning."""
    mock_s3 = MagicMock()

    storage = S3TranscriptStorage(
        bucket="my-bucket",
        key_prefix="",  # empty prefix
        public_url_base="https://cdn.example.com/transcripts/",
        s3_client=mock_s3,
    )

    doc = _create_sample_doc(host_key="cdn_host", tunnel_id="tun-cdn")
    result = await storage.async_save_transcript(doc)

    # Presigned URLs should not be generated
    mock_s3.generate_presigned_url.assert_not_called()

    # Public URLs with cache busting
    assert result.json_url.startswith("https://cdn.example.com/transcripts/cdn_host/latest.json?t=")
    assert result.md_url.startswith("https://cdn.example.com/transcripts/cdn_host/latest.md?t=")


def test_s3_transcript_storage_boto3_client_initialization() -> None:
    """Test that S3TranscriptStorage properly configures boto3 client when not injected."""
    with patch("boto3.session.Session") as mock_session_cls:
        mock_session_instance = MagicMock()
        mock_session_cls.return_value = mock_session_instance

        S3TranscriptStorage(
            bucket="boto-test",
            endpoint_url="https://minio.local:9000",
            region_name="eu-central-1",
            aws_access_key_id="minio_admin",
            aws_secret_access_key="minio_secret",
        )

        mock_session_cls.assert_called_once()
        mock_session_instance.client.assert_called_once_with(
            service_name="s3",
            region_name="eu-central-1",
            endpoint_url="https://minio.local:9000",
            aws_access_key_id="minio_admin",
            aws_secret_access_key="minio_secret",
        )


def test_create_storage_driver_factory(tmp_path: Path) -> None:
    """Test create_storage_driver factory helper for both local and s3 configs."""
    default_dir = tmp_path / "default_dir"
    config_dir = tmp_path / "config"
    public = [config_dir / "www"]
    inv = TranscriptInventory(HomeAssistant())
    kw = {"entry_id": "e1", "inventory": inv, "public_roots": public, "config_dir": config_dir}

    # 1. Default fallback to local storage
    driver1 = create_storage_driver({}, default_dir, **kw)
    assert isinstance(driver1, LocalTranscriptStorage)
    assert driver1.base_dir == default_dir

    # 2. Explicit local storage with custom absolute path
    custom_dir = tmp_path / "custom_dir"
    driver2 = create_storage_driver(
        {CONF_STORAGE_TYPE: STORAGE_TYPE_LOCAL, CONF_LOCAL_STORAGE_PATH: str(custom_dir)},
        default_dir, **kw,
    )
    assert isinstance(driver2, LocalTranscriptStorage)
    assert driver2.base_dir == custom_dir

    # 3. Relative custom path is relative to the config directory
    driver3 = create_storage_driver(
        {CONF_STORAGE_TYPE: STORAGE_TYPE_LOCAL, CONF_LOCAL_STORAGE_PATH: "subfolder"},
        default_dir, **kw,
    )
    assert driver3.base_dir == config_dir / "subfolder"

    # 3b. Legacy/public paths (including via symlink) fall back to the private default
    (config_dir / "www").mkdir(parents=True)
    (tmp_path / "sneaky").symlink_to(config_dir / "www", target_is_directory=True)
    for bad in ("www/junie_remote", "www", str(config_dir / "www" / "x"), str(tmp_path / "sneaky")):
        driver = create_storage_driver(
            {CONF_STORAGE_TYPE: STORAGE_TYPE_LOCAL, CONF_LOCAL_STORAGE_PATH: bad},
            default_dir, **kw,
        )
        assert driver.base_dir == default_dir
        assert driver.public_path_fallback == bad

    # 3c. Local storage needs entry identity and inventory
    with pytest.raises(ValueError):
        create_storage_driver({}, default_dir)

    # 4. S3 storage configuration
    with patch("boto3.session.Session"):
        driver4 = create_storage_driver(
            {
                CONF_STORAGE_TYPE: STORAGE_TYPE_S3,
                CONF_S3_BUCKET: "my-s3-bucket",
                CONF_S3_ENDPOINT: "https://r2.cloudflarestorage.com",
                CONF_S3_REGION: "auto",
                CONF_S3_ACCESS_KEY: "cf-key",
                CONF_S3_SECRET_KEY: "cf-secret",
                CONF_S3_PUBLIC_URL_BASE: "https://pub.domain.org",
            },
            default_dir,
        )
        assert isinstance(driver4, S3TranscriptStorage)
        assert driver4.bucket == "my-s3-bucket"
        assert driver4.endpoint_url == "https://r2.cloudflarestorage.com"
        assert driver4.region_name == "auto"
        assert driver4.aws_access_key_id == "cf-key"
        assert driver4.aws_secret_access_key == "cf-secret"
        assert driver4.public_url_base == "https://pub.domain.org"


@pytest.mark.asyncio
async def test_local_storage_mid_batch_failure_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _local_storage(tmp_path)
    await storage.inventory.async_load()

    doc1 = _create_sample_doc(host_key="h", tunnel_id="t1")
    await storage.async_save_transcript(doc1)
    host_dir = tmp_path / "private" / "entry-a" / "h"
    latest_json = host_dir / "latest.json"
    latest_md = host_dir / "latest.md"
    tunnel1 = host_dir / "tunnel-t1.json"
    tunnel2 = host_dir / "tunnel-t2.json"

    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    doc1_json = doc1.to_json().encode("utf-8")
    doc1_md = doc1.render_markdown().encode("utf-8")
    assert latest_json.read_bytes() == tunnel1.read_bytes() == doc1_json
    assert latest_md.read_bytes() == doc1_md

    original_write = LocalTranscriptStorage._write_owned
    call_count = 0

    def failing_write(*args: Any) -> Path:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("Simulated write failure")
        return original_write(*args)

    monkeypatch.setattr(LocalTranscriptStorage, "_write_owned", staticmethod(failing_write))

    doc2 = _create_sample_doc(host_key="h", tunnel_id="t2", status="disconnected")
    doc2_json = doc2.to_json().encode("utf-8")
    doc2_md = doc2.render_markdown().encode("utf-8")
    with pytest.raises(OSError, match="Simulated write failure"):
        await storage.async_save_transcript(doc2)

    assert latest_json.read_bytes() == doc2_json
    assert latest_md.read_bytes() == doc1_md
    assert tunnel1.read_bytes() == doc1_json
    assert not tunnel2.exists()
    # The successful JSON write retains both digests until a full commit;
    # unwritten Markdown and tunnel intents are discarded.
    assert {(r["path"], r["sha256"]) for r in storage.inventory.local_records("entry-a")} == {
        (str(latest_json), digest(doc1_json)),
        (str(latest_json), digest(doc2_json)),
        (str(latest_md), digest(doc1_md)),
        (str(tunnel1), digest(doc1_json)),
    }
    assert digest(doc1_md) != digest(doc2_md)

    monkeypatch.setattr(LocalTranscriptStorage, "_write_owned", staticmethod(original_write))
    await storage.async_save_transcript(doc2)
    assert latest_json.read_bytes() == tunnel2.read_bytes() == doc2_json
    assert latest_md.read_bytes() == doc2_md
    assert tunnel1.read_bytes() == doc1_json
    assert {(r["path"], r["sha256"]) for r in storage.inventory.local_records("entry-a")} == {
        (str(latest_json), digest(latest_json.read_bytes())),
        (str(latest_md), digest(latest_md.read_bytes())),
        (str(tunnel1), digest(tunnel1.read_bytes())),
        (str(tunnel2), digest(tunnel2.read_bytes())),
    }


@pytest.mark.asyncio
async def test_inventory_s3_and_pause_lifecycle(tmp_path: Path) -> None:
    """Test S3 recording, removal, pause/resume, and validation in TranscriptInventory."""
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()

    assert inv.is_paused("entry-1") is False
    await inv.async_pause("entry-1")
    assert inv.is_paused("entry-1") is True
    await inv.async_resume("entry-1")
    assert inv.is_paused("entry-1") is False

    s3_recs = [
        {
            "endpoint": "https://s3.example.com",
            "bucket": "b1",
            "key": "k1",
            "version_id": "v1",
            "etag": "e1",
        },
        {"endpoint": None, "bucket": "b1", "key": "k2", "version_id": None, "etag": "e2"},
    ]
    await inv.async_record_s3("entry-1", s3_recs)
    assert inv.s3_records("entry-1") == s3_recs

    # Deduplication
    await inv.async_record_s3("entry-1", s3_recs[:1])
    assert len(inv.s3_records("entry-1")) == 2

    # Remove single S3 record
    await inv.async_remove_s3_records("entry-1", [s3_recs[0]])
    assert inv.s3_records("entry-1") == [s3_recs[1]]

    # Clear entry
    await inv.async_pause("entry-1")
    await inv.async_clear_entry("entry-1")
    assert inv.s3_records("entry-1") == []
    assert inv.is_paused("entry-1") is True


@pytest.mark.asyncio
async def test_s3_storage_paused_and_inventory(tmp_path: Path) -> None:
    """S3 storage records object ownership and fails closed when paused."""
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()

    mock_client = MagicMock()
    mock_client.put_object.return_value = {"ETag": '"etag123"', "VersionId": "ver-1"}
    mock_client.generate_presigned_url.return_value = "https://s3.example.com/presigned"

    storage = S3TranscriptStorage(
        bucket="test-bucket",
        s3_client=mock_client,
        entry_id="entry-s3",
        inventory=inv,
    )

    doc = _create_sample_doc(host_key="my_host", tunnel_id="tun-s3")
    res = await storage.async_save_transcript(doc)
    assert res.json_url == "https://s3.example.com/presigned"

    recs = inv.s3_records("entry-s3")
    assert len(recs) == 3
    assert recs[0]["bucket"] == "test-bucket"
    assert recs[0]["etag"] == "etag123"
    assert recs[0]["version_id"] == "ver-1"

    # Pause entry
    await inv.async_pause("entry-s3")
    with pytest.raises(TranscriptStorageError, match="writes are paused"):
        await storage.async_save_transcript(doc)


@pytest.mark.asyncio
async def test_local_storage_paused(tmp_path: Path) -> None:
    """Local storage fails closed when entry is paused."""
    storage = _local_storage(tmp_path)
    await storage.inventory.async_load()

    doc = _create_sample_doc(host_key="my_host", tunnel_id="tun-loc")
    await storage.async_save_transcript(doc)

    await storage.inventory.async_pause("entry-a")
    with pytest.raises(TranscriptStorageError, match="writes are paused"):
        await storage.async_save_transcript(doc)


def _s3_error(code: str, op: str = "DeleteObject") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, op)


def _s3_mock(*, endpoint: str | None = None) -> MagicMock:
    client = MagicMock()
    client.meta.endpoint_url = endpoint
    client.generate_presigned_url.return_value = "https://s3.example.com/presigned"
    return client


async def _cleanup(
    inventory: TranscriptInventory,
    entry_id: str,
    *,
    hass: HomeAssistant | None = None,
    s3_client: Any = None,
) -> dict[str, Any]:
    return await async_cleanup_entry_transcripts(
        hass or HomeAssistant(),
        entry_id,
        inventory,
        s3_client=s3_client,
    )


@pytest.mark.asyncio
async def test_s3_unversioned_records_replace_per_key() -> None:
    """Unversioned saves keep one record per (endpoint, bucket, key)."""
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    client = _s3_mock()
    n = 0

    def put_object(**_kwargs: Any) -> dict[str, str]:
        nonlocal n
        n += 1
        return {"ETag": f'"etag-{n}"'}

    client.put_object.side_effect = put_object
    storage = S3TranscriptStorage(
        bucket="b1",
        endpoint_url="https://minio.example",
        s3_client=client,
        entry_id="e1",
        inventory=inv,
    )
    doc = _create_sample_doc(host_key="h", tunnel_id="t")
    for _ in range(10):
        await storage.async_save_transcript(doc)
    recs = inv.s3_records("e1")
    assert len(recs) == 3
    keys = {r["key"] for r in recs}
    assert len(keys) == 3
    assert all(r["version_id"] is None for r in recs)
    assert {r["etag"] for r in recs} == {"etag-28", "etag-29", "etag-30"}


@pytest.mark.asyncio
async def test_s3_versioned_records_are_bounded_per_object_key() -> None:
    """Versioned writes retain only the latest ownership record per object key."""
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    for version in range(50):
        await inv.async_record_s3(
            "e1",
            [
                {
                    "endpoint": "https://s3.example",
                    "bucket": "b",
                    "key": f"k-{key_index}",
                    "version_id": f"v{version}",
                    "etag": f"e{version}",
                }
                for key_index in range(3)
            ],
        )

    records = inv.s3_records("e1")
    assert len(records) == 3
    assert {rec["key"] for rec in records} == {"k-0", "k-1", "k-2"}
    assert {rec["version_id"] for rec in records} == {"v49"}


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [None, "null"])
async def test_s3_unsafe_unversioned_provider_never_receives_delete(version: str | None) -> None:
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    rec = {"endpoint": "https://minio.example", "bucket": "b", "key": "k",
           "version_id": version, "etag": "old"}
    await inv.async_record_s3("a", [rec])
    objects = {"k": b"replacement"}
    client = _s3_mock(endpoint="https://minio.example")
    client.delete_object.side_effect = lambda **kwargs: objects.pop(kwargs["Key"])
    with pytest.raises(HomeAssistantError, match="manual review"):
        await _cleanup(inv, "a", hass=hass, s3_client=client)
    assert objects == {"k": b"replacement"}
    assert len(inv.s3_records("a")) == 1


@pytest.mark.asyncio
async def test_s3_cleanup_retains_cross_entry_shared_key() -> None:
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    rec = {"endpoint": "https://minio.example", "bucket": "b", "key": "k",
           "version_id": "v1", "etag": "a"}
    await inv.async_record_s3("a", [rec])
    await inv.async_record_s3("b", [{**rec, "version_id": "v2"}])
    client = _s3_mock(endpoint="https://minio.example")
    with pytest.raises(HomeAssistantError, match="shared"):
        await _cleanup(inv, "a", hass=hass, s3_client=client)
    client.delete_object.assert_not_called()
    assert inv.s3_records("a") == [rec]
    assert len(inv.s3_records("b")) == 1


@pytest.mark.asyncio
async def test_s3_prune_matches_endpoint() -> None:
    inv = TranscriptInventory(HomeAssistant())
    await inv.async_load()
    rec = {"endpoint": "https://a.example", "bucket": "b", "key": "k",
           "version_id": "v", "etag": "a"}
    other = {**rec, "endpoint": "https://b.example"}
    await inv.async_record_s3("a", [rec, other])
    await inv.async_remove_s3_records("a", [rec])
    assert inv.s3_records("a") == [other]


@pytest.mark.asyncio
async def test_s3_legacy_null_record_is_retained_and_null_upload_is_bounded() -> None:
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    rec = {"endpoint": "https://minio.example", "bucket": "b", "key": "k",
           "version_id": "null", "etag": "a"}
    await inv._store.async_save({"entries": {"a": {"local": [], "s3": [rec], "paused": False}}})
    await inv.async_load()
    client = _s3_mock(endpoint="https://minio.example")
    with pytest.raises(HomeAssistantError, match="manual review"):
        await _cleanup(inv, "a", hass=hass, s3_client=client)
    client.delete_object.assert_not_called()
    await inv.async_record_s3("a", [{**rec, "etag": "b"}])
    assert inv.s3_records("a") == [{**rec, "version_id": None, "etag": "b"}]


@pytest.mark.asyncio
async def test_s3_cleanup_waits_for_other_entry_upload_and_inventory() -> None:
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    client = _s3_mock(endpoint="https://minio.example")
    client.put_object.return_value = {"ETag": '"a"', "VersionId": "v2"}
    storage = S3TranscriptStorage(bucket="b", endpoint_url="https://minio.example",
                                  s3_client=client, entry_id="b", inventory=inv)
    rec = {"endpoint": "https://minio.example", "bucket": "b",
           "key": "junie_remote/h/latest.json", "version_id": "v1", "etag": "a"}
    await inv.async_record_s3("a", [rec])
    started, release = asyncio.Event(), asyncio.Event()
    orig = asyncio.to_thread

    async def blocked(fn: Any, *args: Any, **kwargs: Any) -> Any:
        if getattr(fn, "__name__", "") == "_sync_save":
            started.set()
            await release.wait()
        return await orig(fn, *args, **kwargs)

    with patch("custom_components.junie_remote.storage.asyncio.to_thread", blocked):
        save = asyncio.create_task(storage.async_save_transcript(_create_sample_doc("h", "t")))
        await started.wait()
        cleanup = asyncio.create_task(_cleanup(inv, "a", hass=hass, s3_client=client))
        await asyncio.sleep(0)
        assert not cleanup.done()
        release.set()
        await save
        with pytest.raises(HomeAssistantError, match="shared"):
            await cleanup
    client.delete_object.assert_not_called()
    assert inv.s3_records("a") == [rec]


@pytest.mark.asyncio
async def test_cleanup_rejects_intermediate_symlink(tmp_path: Path) -> None:
    storage = _local_storage(tmp_path)
    await storage.inventory.async_load()
    await storage.async_save_transcript(_create_sample_doc(host_key="h", tunnel_id="t"))
    entry_dir = tmp_path / "private" / "entry-a"
    moved = tmp_path / "moved"
    entry_dir.rename(moved)
    entry_dir.symlink_to(moved, target_is_directory=True)
    with pytest.raises(HomeAssistantError, match="manual review"):
        await _cleanup(storage.inventory, "entry-a")
    assert (moved / "h" / "latest.json").exists()


@pytest.mark.asyncio
async def test_cleanup_rollback_never_overwrites_recreated_file(tmp_path: Path) -> None:
    storage = _local_storage(tmp_path)
    inv = storage.inventory
    await inv.async_load()
    await storage.async_save_transcript(_create_sample_doc(host_key="h", tunnel_id="t"))
    target = tmp_path / "private" / "entry-a" / "h" / "latest.json"
    real_rename = os.rename

    def replace_before_quarantine(src: Any, dst: Any, **kwargs: Any) -> None:
        if src == "latest.json" and str(dst).startswith(".junie-remote-cleanup-"):
            target.write_bytes(b"other file")
            real_rename(src, dst, **kwargs)
            target.write_bytes(b"recreated")
        else:
            real_rename(src, dst, **kwargs)

    with patch(
        "custom_components.junie_remote.storage.os.rename",
        side_effect=replace_before_quarantine,
    ):
        with pytest.raises(HomeAssistantError, match="quarantine"):
            await _cleanup(inv, "entry-a")
    assert target.read_bytes() == b"recreated"
    quarantined = list(target.parent.glob(".junie-remote-cleanup-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"other file"
    with pytest.raises(HomeAssistantError, match="quarantine"):
        await _cleanup(inv, "entry-a")
    assert quarantined[0].exists()
    assert any(r["path"] == str(target) for r in inv.local_records("entry-a"))


@pytest.mark.asyncio
async def test_cleanup_retains_byte_identical_replacement(tmp_path: Path) -> None:
    storage = _local_storage(tmp_path)
    inv = storage.inventory
    await inv.async_load()
    await storage.async_save_transcript(_create_sample_doc(host_key="h", tunnel_id="t"))
    target = tmp_path / "private" / "entry-a" / "h" / "latest.json"
    replacement = target.with_name("user-file")
    replacement_content = target.read_bytes()
    replacement.write_bytes(replacement_content)
    real_rename = os.rename

    def replace_before_quarantine(src: Any, dst: Any, **kwargs: Any) -> None:
        if src == "latest.json" and str(dst).startswith(".junie-remote-cleanup-"):
            os.replace(replacement, target)
        real_rename(src, dst, **kwargs)

    with patch(
        "custom_components.junie_remote.storage.os.rename",
        side_effect=replace_before_quarantine,
    ):
        with pytest.raises(HomeAssistantError, match="quarantine"):
            await _cleanup(inv, "entry-a")
    quarantined = list(target.parent.glob(".junie-remote-cleanup-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == replacement_content
    assert any(r["path"] == str(target) for r in inv.local_records("entry-a"))


@pytest.mark.asyncio
async def test_cleanup_reports_crash_orphan_before_pruning_missing_file(tmp_path: Path) -> None:
    storage = _local_storage(tmp_path)
    inv = storage.inventory
    await inv.async_load()
    await storage.async_save_transcript(_create_sample_doc(host_key="h", tunnel_id="t"))
    target = tmp_path / "private" / "entry-a" / "h" / "latest.json"
    orphan = target.with_name(".junie-remote-cleanup-crash")
    target.rename(orphan)
    with pytest.raises(HomeAssistantError, match="quarantine") as err:
        await _cleanup(inv, "entry-a")
    assert str(orphan) in str(err.value)
    assert orphan.exists()
    assert any(r["path"] == str(target) for r in inv.local_records("entry-a"))


def test_owned_file_delete_reports_preexisting_orphan_without_touching_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "junie-remote-card.js"
    target.write_bytes(b"owned")
    orphan = tmp_path / ".junie-remote-cleanup-crash"
    orphan.write_bytes(b"manual review")

    error, unlinked, was_quarantined = _delete_owned_local_file(
        str(target), hashlib.sha256(b"owned").hexdigest()
    )

    assert error is not None
    assert (unlinked, was_quarantined) == (False, False)
    assert target.read_bytes() == b"owned"
    assert orphan.read_bytes() == b"manual review"


def test_owned_file_delete_reports_modified_file_without_quarantining(tmp_path: Path) -> None:
    target = tmp_path / "junie-remote-card.js"
    target.write_bytes(b"modified")

    error, unlinked, was_quarantined = _delete_owned_local_file(
        str(target), hashlib.sha256(b"owned").hexdigest()
    )

    assert error is not None
    assert (unlinked, was_quarantined) == (False, False)
    assert target.read_bytes() == b"modified"


def test_owned_file_delete_reports_symlink_without_quarantining(tmp_path: Path) -> None:
    actual = tmp_path / "user-file.js"
    actual.write_bytes(b"owned")
    target = tmp_path / "junie-remote-card.js"
    target.symlink_to(actual)

    error, unlinked, was_quarantined = _delete_owned_local_file(
        str(target), hashlib.sha256(b"owned").hexdigest()
    )

    assert error is not None
    assert (unlinked, was_quarantined) == (False, False)
    assert target.is_symlink()
    assert actual.read_bytes() == b"owned"


def test_owned_file_delete_reports_attempted_rename_as_quarantined(
    tmp_path: Path,
) -> None:
    target = tmp_path / "junie-remote-card.js"
    target.write_bytes(b"owned")

    with patch(
        "custom_components.junie_remote.storage.os.rename",
        side_effect=OSError("rename failed"),
    ):
        error, unlinked, was_quarantined = _delete_owned_local_file(
            str(target), hashlib.sha256(b"owned").hexdigest()
        )

    assert error is not None
    assert (unlinked, was_quarantined) == (False, True)
    assert target.read_bytes() == b"owned"
    assert not list(tmp_path.glob(".junie-remote-cleanup-*"))


def test_owned_file_delete_reports_unlink_failure_after_quarantine(
    tmp_path: Path,
) -> None:
    target = tmp_path / "junie-remote-card.js"
    target.write_bytes(b"owned")

    with patch(
        "custom_components.junie_remote.storage.os.unlink",
        side_effect=OSError("unlink failed"),
    ):
        error, unlinked, was_quarantined = _delete_owned_local_file(
            str(target), hashlib.sha256(b"owned").hexdigest()
        )

    assert error is not None
    assert (unlinked, was_quarantined) == (False, True)
    assert not target.exists()
    quarantined, = tmp_path.glob(".junie-remote-cleanup-*")
    assert quarantined.read_bytes() == b"owned"


def test_owned_file_delete_reports_identity_mismatch_after_quarantine(
    tmp_path: Path,
) -> None:
    target = tmp_path / "junie-remote-card.js"
    target.write_bytes(b"owned")
    real_fstat = os.fstat
    calls = 0

    def mismatched_fstat(fd: int) -> Any:
        nonlocal calls
        calls += 1
        result = real_fstat(fd)
        if calls == 2:
            return type("Stat", (), {
                "st_dev": result.st_dev,
                "st_ino": result.st_ino + 1,
                "st_mode": result.st_mode,
            })()
        return result

    with patch(
        "custom_components.junie_remote.storage.os.fstat",
        side_effect=mismatched_fstat,
    ):
        error, unlinked, was_quarantined = _delete_owned_local_file(
            str(target), hashlib.sha256(b"owned").hexdigest()
        )

    assert error is not None
    assert (unlinked, was_quarantined) == (False, True)
    assert not target.exists()
    quarantined, = tmp_path.glob(".junie-remote-cleanup-*")
    assert quarantined.read_bytes() == b"owned"


@pytest.mark.asyncio
async def test_s3_cleanup_missing_etag_is_retained() -> None:
    """No VersionId and no ETag means the object is kept for manual review."""
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    rec = {
        "endpoint": "https://minio.example",
        "bucket": "b",
        "key": "k.json",
        "version_id": None,
        "etag": "",
    }
    await inv.async_record_s3("e1", [rec])
    client = _s3_mock(endpoint="https://minio.example")
    client.head_object.return_value = {"ETag": '"someone-elses-object"'}
    with pytest.raises(HomeAssistantError, match="manual review"):
        await _cleanup(inv, "e1", hass=hass, s3_client=client)
    assert client.delete_object.call_count == 0
    remaining = inv.s3_records("e1")
    assert len(remaining) == 1
    assert remaining[0]["key"] == "k.json"


@pytest.mark.asyncio
async def test_s3_cleanup_endpoint_mismatch_is_retained() -> None:
    """Objects recorded against a different endpoint are never deleted."""
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    await inv.async_record_s3(
        "e1",
        [
            {
                "endpoint": "https://minio-a.example",
                "bucket": "b",
                "key": "k.json",
                "version_id": None,
                "etag": "abc",
            }
        ],
    )
    client = _s3_mock(endpoint="https://minio-b.example")
    with pytest.raises(HomeAssistantError, match="different endpoint"):
        await _cleanup(inv, "e1", hass=hass, s3_client=client)
    assert client.delete_object.call_count == 0
    assert len(inv.s3_records("e1")) == 1


@pytest.mark.asyncio
async def test_s3_cleanup_unversioned_is_retained_even_with_etag() -> None:
    """A provider may silently ignore conditional deletes, so do not call it."""
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    await inv.async_record_s3(
        "e1",
        [
            {
                "endpoint": "https://minio.example",
                "bucket": "b",
                "key": "k.json",
                "version_id": None,
                "etag": "abc123",
            }
        ],
    )
    client = _s3_mock(endpoint="https://minio.example")
    with pytest.raises(HomeAssistantError, match="manual review"):
        await _cleanup(inv, "e1", hass=hass, s3_client=client)
    client.head_object.assert_not_called()
    client.delete_object.assert_not_called()
    assert len(inv.s3_records("e1")) == 1


@pytest.mark.asyncio
async def test_s3_cleanup_unversioned_replacement_is_retained() -> None:
    """A replaced unversioned object is not sent to any delete API."""
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    await inv.async_record_s3(
        "e1",
        [
            {
                "endpoint": "https://minio.example",
                "bucket": "b",
                "key": "k.json",
                "version_id": None,
                "etag": "old-etag",
            }
        ],
    )
    client = _s3_mock(endpoint="https://minio.example")
    client.delete_object.side_effect = _s3_error("PreconditionFailed")
    with pytest.raises(HomeAssistantError, match="manual review"):
        await _cleanup(inv, "e1", hass=hass, s3_client=client)
    client.delete_object.assert_not_called()
    assert len(inv.s3_records("e1")) == 1


@pytest.mark.asyncio
async def test_s3_cleanup_version_delete_failure_is_retained() -> None:
    """A failed immutable-version deletion retains the inventory for retry."""
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    await inv.async_record_s3(
        "e1",
        [
            {
                "endpoint": "https://minio.example",
                "bucket": "b",
                "key": "k.json",
                "version_id": "v1",
                "etag": "abc",
            }
        ],
    )
    client = _s3_mock(endpoint="https://minio.example")
    client.delete_object.side_effect = _s3_error("InvalidArgument")
    with pytest.raises(HomeAssistantError, match="Failed to delete"):
        await _cleanup(inv, "e1", hass=hass, s3_client=client)
    client.delete_object.assert_called_once_with(Bucket="b", Key="k.json", VersionId="v1")
    assert len(inv.s3_records("e1")) == 1
    client.delete_object.side_effect = None
    result = await _cleanup(inv, "e1", hass=hass, s3_client=client)
    assert result["deleted_s3"] == 1
    assert inv.s3_records("e1") == []


@pytest.mark.asyncio
async def test_s3_cleanup_versioned_deletes_by_version_id() -> None:
    """Versioned objects are deleted by immutable VersionId only."""
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    await inv.async_record_s3(
        "e1",
        [
            {
                "endpoint": "https://minio.example",
                "bucket": "b",
                "key": "k.json",
                "version_id": "v1",
                "etag": "abc",
            }
        ],
    )
    client = _s3_mock(endpoint="https://minio.example")
    result = await _cleanup(inv, "e1", hass=hass, s3_client=client)
    assert result["deleted_s3"] == 1
    client.head_object.assert_not_called()
    client.delete_object.assert_called_once_with(
        Bucket="b", Key="k.json", VersionId="v1"
    )


@pytest.mark.asyncio
async def test_remove_local_records_by_path_and_digest() -> None:
    """Inventory prune is exact (path, sha256), never path-only."""
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    await inv.async_prepare_locals("e1", [("p", "aaa"), ("p", "bbb")])
    await inv.async_remove_local_records("e1", [{"path": "p", "sha256": "aaa"}])
    assert inv.local_records("e1") == [{"path": "p", "sha256": "bbb"}]


@pytest.mark.asyncio
async def test_cleanup_custom_local_path(tmp_path: Path) -> None:
    """Cleanup deletes owned files under a custom base, not unrelated paths."""
    custom = tmp_path / "custom-transcripts"
    unrelated = tmp_path / "other" / "keep.txt"
    unrelated.parent.mkdir()
    unrelated.write_text("keep")
    storage = _local_storage(tmp_path, base=custom)
    await storage.inventory.async_load()
    await storage.async_save_transcript(_create_sample_doc(host_key="h", tunnel_id="t"))
    owned = custom / "entry-a" / "h" / "latest.json"
    assert owned.is_file()
    result = await _cleanup(storage.inventory, "entry-a")
    assert result["deleted_local"] == 3
    assert not owned.exists()
    assert unrelated.read_text() == "keep"


@pytest.mark.asyncio
async def test_cleanup_retains_when_parent_is_symlink(tmp_path: Path) -> None:
    """A symlink parent is not followed; the target files are kept."""
    storage = _local_storage(tmp_path)
    await storage.inventory.async_load()
    await storage.async_save_transcript(_create_sample_doc(host_key="h", tunnel_id="t"))
    host_dir = tmp_path / "private" / "entry-a" / "h"
    real = tmp_path / "real-host"
    host_dir.rename(real)
    host_dir.symlink_to(real)
    with pytest.raises(HomeAssistantError, match="manual review|parent"):
        await _cleanup(storage.inventory, "entry-a")
    assert (real / "latest.json").is_file()
    assert (real / "latest.md").is_file()


@pytest.mark.asyncio
async def test_cleanup_partial_failure_retry_converges(tmp_path: Path) -> None:
    """A later retry deletes remaining owned files after a partial failure."""
    storage = _local_storage(tmp_path)
    await storage.inventory.async_load()
    await storage.async_save_transcript(_create_sample_doc(host_key="h", tunnel_id="t"))
    latest = tmp_path / "private" / "entry-a" / "h" / "latest.json"
    original = latest.read_bytes()
    latest.write_text("tampered")
    with pytest.raises(HomeAssistantError, match="partially failed"):
        await _cleanup(storage.inventory, "entry-a")
    assert latest.is_file()
    recs = storage.inventory.local_records("entry-a")
    assert len(recs) == 1
    assert recs[0]["path"] == str(latest)
    latest.write_bytes(original)
    result = await _cleanup(storage.inventory, "entry-a")
    assert result["deleted_local"] == 1
    assert not latest.exists()
    assert storage.inventory.local_records("entry-a") == []


@pytest.mark.asyncio
async def test_cleanup_and_resume_are_serialized(tmp_path: Path) -> None:
    """Resume waits for in-flight cleanup and cannot unpause writers mid-delete."""
    storage = _local_storage(tmp_path)
    inv = storage.inventory
    await inv.async_load()
    await storage.async_save_transcript(_create_sample_doc(host_key="h", tunnel_id="t"))
    started = asyncio.Event()
    release = asyncio.Event()
    orig = asyncio.to_thread

    async def wrapped(fn: Any, *args: Any, **kwargs: Any) -> Any:
        if getattr(fn, "__name__", "") == "_delete_local_records":
            started.set()
            await release.wait()
        return await orig(fn, *args, **kwargs)

    with patch(
        "custom_components.junie_remote.storage.asyncio.to_thread", wrapped
    ):
        cleanup_task = asyncio.create_task(_cleanup(inv, "entry-a"))
        await started.wait()
        resume_task = asyncio.create_task(inv.async_resume("entry-a"))
        await asyncio.sleep(0.05)
        assert not resume_task.done()
        assert inv.is_paused("entry-a") is True
        release.set()
        await cleanup_task
        await resume_task
    assert inv.is_paused("entry-a") is False


@pytest.mark.asyncio
async def test_cancelled_cleanup_keeps_lock_until_delete_finishes(tmp_path: Path) -> None:
    storage = _local_storage(tmp_path)
    inv = storage.inventory
    await inv.async_load()
    await storage.async_save_transcript(_create_sample_doc(host_key="h", tunnel_id="t"))
    started, release = asyncio.Event(), asyncio.Event()
    orig = asyncio.to_thread

    async def blocked(fn: Any, *args: Any, **kwargs: Any) -> Any:
        if getattr(fn, "__name__", "") == "_delete_local_records":
            started.set()
            await release.wait()
        return await orig(fn, *args, **kwargs)

    with patch("custom_components.junie_remote.storage.asyncio.to_thread", blocked):
        cleanup = asyncio.create_task(_cleanup(inv, "entry-a"))
        await started.wait()
        cleanup.cancel()
        resume = asyncio.create_task(inv.async_resume("entry-a"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not cleanup.done()
        assert not resume.done()
        assert inv.is_paused("entry-a")
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await cleanup
        await resume
    assert not inv.is_paused("entry-a")
    assert not inv.local_records("entry-a")


@pytest.mark.asyncio
async def test_cleanup_rejects_concurrent_writers(tmp_path: Path) -> None:
    """Saves attempted while cleanup holds the entry stay paused."""
    storage = _local_storage(tmp_path)
    await storage.inventory.async_load()
    doc = _create_sample_doc(host_key="h", tunnel_id="t")
    await storage.async_save_transcript(doc)
    started = asyncio.Event()
    release = asyncio.Event()
    orig = asyncio.to_thread

    async def wrapped(fn: Any, *args: Any, **kwargs: Any) -> Any:
        if getattr(fn, "__name__", "") == "_delete_local_records":
            started.set()
            await release.wait()
        return await orig(fn, *args, **kwargs)

    with patch(
        "custom_components.junie_remote.storage.asyncio.to_thread", wrapped
    ):
        cleanup_task = asyncio.create_task(_cleanup(storage.inventory, "entry-a"))
        await started.wait()
        save_task = asyncio.create_task(storage.async_save_transcript(doc))
        await asyncio.sleep(0)
        assert not save_task.done()
        release.set()
        await cleanup_task
        with pytest.raises(TranscriptStorageError, match="writes are paused"):
            await save_task
    assert storage.inventory.local_records("entry-a") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_writer", [False, True])
async def test_cleanup_waits_for_local_writer_without_registered_coordinator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel_writer: bool,
) -> None:
    """Cleanup cannot prune intents for a thread-backed save absent from hass.data."""
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    storage = _local_storage(tmp_path, inventory=inv)
    await inv.async_load()
    host_dir = tmp_path / "private" / "entry-a" / "h"
    host_dir.mkdir(parents=True)
    sentinel = host_dir / "unrelated.txt"
    sentinel.write_text("keep", encoding="utf-8")

    write_started = threading.Event()
    release_write = threading.Event()
    pause_persisted = asyncio.Event()
    loop = asyncio.get_running_loop()
    original_write = LocalTranscriptStorage._write_owned
    original_pause = inv.async_pause

    def blocked_write(*args: Any) -> Path:
        loop.call_soon_threadsafe(write_started.set)
        if not release_write.wait(timeout=5):
            raise TimeoutError("test did not release blocked transcript writer")
        return original_write(*args)

    async def tracked_pause(entry_id: str) -> None:
        await original_pause(entry_id)
        pause_persisted.set()

    monkeypatch.setattr(LocalTranscriptStorage, "_write_owned", staticmethod(blocked_write))
    monkeypatch.setattr(inv, "async_pause", tracked_pause)

    save_task = asyncio.create_task(
        storage.async_save_transcript(_create_sample_doc(host_key="h", tunnel_id="t"))
    )
    await asyncio.wait_for(asyncio.to_thread(write_started.wait), timeout=2)
    assert not hass.data.get(DOMAIN, {}).get("entry-a")
    if cancel_writer:
        save_task.cancel()
        await asyncio.sleep(0)
        assert not save_task.done()

    cleanup_task = asyncio.create_task(_cleanup(inv, "entry-a", hass=hass))
    try:
        await asyncio.wait_for(pause_persisted.wait(), timeout=2)
        completed, _ = await asyncio.wait({cleanup_task}, timeout=0.05)
        assert not completed
    finally:
        release_write.set()

    if cancel_writer:
        with pytest.raises(asyncio.CancelledError):
            await save_task
    else:
        await save_task
    result = await cleanup_task

    assert result["deleted_local"] == 3
    assert inv.local_records("entry-a") == []
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert sorted(path.name for path in host_dir.iterdir()) == ["unrelated.txt"]


@pytest.mark.asyncio
async def test_cleanup_counts_only_local_files_that_were_unlinked(tmp_path: Path) -> None:
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    await inv.async_prepare_local(
        "entry-a", str(tmp_path / "missing" / "latest.json"), "not-on-disk"
    )

    result = await _cleanup(inv, "entry-a", hass=hass)

    assert result["deleted_local"] == 0
    assert inv.local_records("entry-a") == []


@pytest.mark.asyncio
async def test_cleanup_s3_without_coordinator_uses_entry_config() -> None:
    """Unloaded entries still clean S3 using the config-built client endpoint."""
    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    endpoint = "https://minio.example"
    await inv.async_record_s3(
        "entry-unloaded",
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
    entry = ConfigEntry(
        entry_id="entry-unloaded",
        data={
            CONF_STORAGE_TYPE: STORAGE_TYPE_S3,
            CONF_S3_BUCKET: "b",
            CONF_S3_ENDPOINT: endpoint,
            CONF_S3_ACCESS_KEY: "ak",
            CONF_S3_SECRET_KEY: "sk",
        },
    )
    hass.config_entries.entries["entry-unloaded"] = entry
    mock_client = _s3_mock(endpoint=endpoint)

    with patch(
        "custom_components.junie_remote.storage.boto3"
    ) as boto:
        boto.session.Session.return_value.client.return_value = mock_client
        result = await async_cleanup_entry_transcripts(
            hass, "entry-unloaded", inv
        )
    assert result["deleted_s3"] == 1
    mock_client.delete_object.assert_called_once_with(
        Bucket="b", Key="k.json", VersionId="v1"
    )
    assert DOMAIN not in hass.data or "entry-unloaded" not in hass.data.get(
        DOMAIN, {}
    )


@pytest.mark.asyncio
async def test_paused_save_is_not_logged_as_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Paused writers must not emit a full traceback on every event."""
    from custom_components.junie_remote.coordinator import JunieRemoteCoordinator
    from custom_components.junie_remote.models import TunnelInfo, TunnelMetadata

    hass = HomeAssistant()
    inv = TranscriptInventory(hass)
    await inv.async_load()
    storage = LocalTranscriptStorage(
        base_dir=Path("/tmp/unused"),
        entry_id="e1",
        inventory=inv,
    )
    await inv.async_pause("e1")
    coord = JunieRemoteCoordinator(hass, MagicMock(), storage, auto_connect=False)
    tunnel = TunnelInfo(
        tunnel_id="t",
        metadata=TunnelMetadata(user_name="a", os_name="linux"),
    )
    from custom_components.junie_remote.coordinator import HostBridgeState

    coord.hosts["h"] = HostBridgeState(host_key="h", tunnel=tunnel)
    with caplog.at_level(logging.ERROR):
        await coord._async_save_and_notify("h")
    assert "Failed to save transcript" not in caplog.text
