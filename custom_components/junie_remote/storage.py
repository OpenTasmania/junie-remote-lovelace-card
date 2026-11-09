# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Hybrid transcript storage driver for JetBrains Junie Remote.

Supports persisting transcripts and session state to private local storage
and S3-compatible object storage (AWS S3, MinIO, Garage, Ceph, Cloudflare R2).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import stat
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import boto3

from .const import (
    CONF_LOCAL_STORAGE_PATH,
    CONF_S3_ACCESS_KEY,
    CONF_S3_BUCKET,
    CONF_S3_ENDPOINT,
    CONF_S3_PUBLIC_URL_BASE,
    CONF_S3_REGION,
    CONF_S3_SECRET_KEY,
    CONF_STORAGE_TYPE,
    DEFAULT_STORAGE_TYPE,
    DOMAIN,
    STORAGE_TYPE_S3,
)
from .ha_compat import HomeAssistantError
from .models import ChatSessionState, TunnelInfo
from .transcript_inventory import TranscriptInventory

_LOGGER = logging.getLogger(__name__)


async def _await_uncancelled_operation(coro: Any) -> Any:
    """Keep operation locks until thread-backed work finishes, even if cancelled."""
    task = asyncio.create_task(coro)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


@dataclass
class TranscriptResult:
    """Result of saving a transcript document."""

    json_url: str
    md_url: str
    updated_at: str
    last_step_preview: str


@dataclass
class TranscriptDocument:
    """Structured transcript document and renderer for an active Junie CLI remote session."""

    host_key: str
    tunnel: TunnelInfo
    chat_state: ChatSessionState
    connection_status: str
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def build(
        cls,
        host_key: str,
        tunnel: TunnelInfo,
        chat_state: ChatSessionState,
        connection_status: str,
        updated_at: str | None = None,
    ) -> TranscriptDocument:
        """Construct a TranscriptDocument instance."""
        return cls(
            host_key=host_key,
            tunnel=tunnel,
            chat_state=chat_state,
            connection_status=connection_status,
            updated_at=updated_at or datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert transcript document to serializable dictionary."""
        options = [
            {
                "id": val,
                "value": val,
                "name": label,
                "label": label,
            }
            for val, label in self.chat_state.model_selection.get_selectable_options()
        ]

        metadata = {
            "title": self.chat_state.title,
            "git_repo": self.tunnel.metadata.git_repo_url or "",
            "git_branch": self.chat_state.git_branch
            or self.tunnel.metadata.git_branch
            or "",
            "working_dir": self.chat_state.working_dir
            or self.tunnel.metadata.current_directory
            or "",
            "user_name": self.tunnel.metadata.user_name or "",
            "os_name": self.tunnel.metadata.os_name or "",
        }

        return {
            "host_key": self.host_key,
            "tunnel_id": self.tunnel.tunnel_id,
            "updated_at": self.updated_at,
            "connection_status": self.connection_status,
            "metadata": metadata,
            "session_status": self.chat_state.session_status,
            "can_send_prompt": self.chat_state.can_send_prompt,
            "brave_mode": self.chat_state.brave_mode,
            "has_plan": self.chat_state.has_plan,
            "model_selection": {
                "current_model_id": self.chat_state.model_selection.current_model_id,
                "current_effort_id": self.chat_state.model_selection.current_effort_id,
                "options": options,
            },
            "history": self.chat_state.history,
            "progressing_steps": self.chat_state.progressing_steps,
            "plan_proposal": (
                self.chat_state.plan_proposal.to_dict()
                if self.chat_state.plan_proposal
                else None
            ),
            "active_requests": self.chat_state.active_requests,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert transcript document to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def extract_last_step_preview(self) -> str:
        """Return a concise summary (<= 200 chars) of the most recent step or prompt."""
        candidate: dict[str, Any] | None = None
        prefix = ""

        if self.chat_state.progressing_steps:
            candidate = self.chat_state.progressing_steps[-1]
            prefix = "[In Progress] "
        elif self.chat_state.history:
            candidate = self.chat_state.history[-1]

        if not candidate or not isinstance(candidate, dict):
            fallback = self.chat_state.title or "No activity recorded"
            return fallback[:200]

        step_type = str(candidate.get("type", ""))

        if step_type == "user-prompt":
            raw = candidate.get("prompt") or candidate.get("text") or ""
            msg = f"User: {raw}" if raw else "User Prompt"
        elif step_type == "user-response":
            raw = candidate.get("displayText") or candidate.get("text") or ""
            msg = f"User response: {raw}" if raw else "User Response"
        elif step_type == "system-message":
            raw = candidate.get("text") or candidate.get("message") or ""
            msg = f"System: {raw}" if raw else "System Message"
        elif step_type == "skills-status":
            raw = candidate.get("status") or candidate.get("text") or ""
            msg = f"Skills: {raw}" if raw else "Skills Status"
        else:
            name = candidate.get("name") or candidate.get("title")
            text = candidate.get("text") or candidate.get("result")
            if name and text:
                msg = f"{name}: {text}"
            elif text:
                msg = str(text)
            elif name:
                msg = str(name)
            elif candidate.get("changesSummary"):
                msg = f"Changes: {candidate['changesSummary']}"
            else:
                msg = str(
                    candidate.get("prompt")
                    or candidate.get("displayText")
                    or step_type
                    or "Step"
                )

        full = f"{prefix}{msg}".strip()
        clean = " ".join(full.split())
        if len(clean) > 200:
            return clean[:197] + "..."
        return clean or "No activity recorded"

    def render_markdown(self) -> str:
        """Render a clean, human-readable Markdown transcript."""
        title = self.chat_state.title or f"Host: {self.host_key}"
        user_name = self.tunnel.metadata.user_name or "N/A"
        os_name = self.tunnel.metadata.os_name or "N/A"
        git_repo = self.tunnel.metadata.git_repo_url or "N/A"
        git_branch = (
            self.chat_state.git_branch or self.tunnel.metadata.git_branch or "N/A"
        )
        working_dir = (
            self.chat_state.working_dir
            or self.tunnel.metadata.current_directory
            or "N/A"
        )
        cur_model = self.chat_state.model_selection.current_model_id or "default"
        cur_effort = self.chat_state.model_selection.current_effort_id
        model_str = f"{cur_model} ({cur_effort})" if cur_effort else cur_model
        brave_str = "Enabled" if self.chat_state.brave_mode else "Disabled"
        can_prompt_str = "Yes" if self.chat_state.can_send_prompt else "No"

        lines: list[str] = [
            f"# Junie Session Transcript: {title}",
            "",
            f"- **Host Key:** `{self.host_key}`",
            f"- **Tunnel ID:** `{self.tunnel.tunnel_id}`",
            f"- **Connection Status:** `{self.connection_status}`",
            f"- **Session Status:** `{self.chat_state.session_status}`",
            f"- **Updated At:** `{self.updated_at}`",
            f"- **User:** `{user_name}`",
            f"- **OS:** `{os_name}`",
            f"- **Repository:** `{git_repo}`",
            f"- **Branch:** `{git_branch}`",
            f"- **Working Directory:** `{working_dir}`",
            f"- **Model:** `{model_str}`",
            f"- **Brave Mode:** `{brave_str}`",
            f"- **Can Send Prompt:** `{can_prompt_str}`",
        ]

        # Plan proposal section
        if self.chat_state.plan_proposal:
            lines.extend(["", "---", "", "## 📋 Plan Proposal"])
            plan = self.chat_state.plan_proposal
            if plan.plan_file_path:
                lines.append(f"- **Plan File:** `{plan.plan_file_path}`")
            lines.append(
                f"- **Ready for Review:** `{'Yes' if plan.ready_for_review else 'No'}`"
            )

            if plan.sections:
                lines.extend(["", "### Plan Sections"])
                for idx, sec in enumerate(plan.sections, 1):
                    sec_title = (
                        sec.get("title") or sec.get("name") or f"Section {idx}"
                    )
                    lines.append(f"#### {sec_title}")
                    sec_desc = sec.get("description") or sec.get("content")
                    if sec_desc:
                        lines.append(str(sec_desc))
                    tasks = sec.get("tasks") or sec.get("subtasks")
                    if isinstance(tasks, list):
                        for task in tasks:
                            if isinstance(task, dict):
                                done = task.get("completed") or task.get("done")
                                mark = "x" if done else " "
                                t_text = task.get("title") or task.get("text") or str(task)
                                lines.append(f"- [{mark}] {t_text}")
                            else:
                                lines.append(f"- [ ] {task}")

            if plan.delivery_steps:
                lines.extend(["", "### Delivery Steps"])
                for idx, step in enumerate(plan.delivery_steps, 1):
                    s_name = (
                        step.get("name") or step.get("title") or f"Step {idx}"
                    )
                    s_desc = step.get("description") or step.get("text") or ""
                    s_status = f" ({step['status']})" if "status" in step else ""
                    lines.append(f"{idx}. **{s_name}**{s_status}: {s_desc}")

        # Conversation history section
        lines.extend(["", "---", "", "## 💬 Conversation History"])
        if not self.chat_state.history:
            lines.append("*No history recorded.*")
        else:
            for item in self.chat_state.history:
                if not isinstance(item, dict):
                    lines.extend(["", str(item)])
                    continue

                item_type = item.get("type", "step")

                if item_type == "user-prompt":
                    prompt_text = item.get("prompt") or item.get("text") or ""
                    lines.extend(["", "### 👤 User Prompt", "", prompt_text])

                elif item_type == "user-response":
                    resp_text = item.get("displayText") or item.get("text") or ""
                    lines.extend(["", "### 💬 User Response", "", resp_text])

                elif item_type == "system-message":
                    sys_msg = item.get("text") or item.get("message") or ""
                    lines.extend(["", f"> ℹ️ **System**: {sys_msg}"])

                elif item_type == "skills-status":
                    status_val = item.get("status")
                    skills_val = item.get("skills")
                    if status_val and skills_val and status_val != skills_val:
                        skills_str = f"{status_val} ({skills_val})"
                    else:
                        skills_str = str(status_val or skills_val or item.get("text") or "")
                    lines.extend(["", f"> 🛠️ **Skills Status**: {skills_str}"])

                else:
                    # Agent step
                    step_name = item.get("name") or item.get("title") or "Step"
                    lines.extend(["", f"### ⚙️ {step_name}"])

                    status = item.get("status")
                    if status:
                        lines.append(f"*Status: {status}*")

                    text = item.get("text")
                    if text:
                        lines.extend(["", str(text)])

                    result = item.get("result")
                    if result:
                        lines.extend(["", "**Result:**"])
                        if isinstance(result, str):
                            lines.extend(["```", result, "```"])
                        else:
                            lines.extend([
                                "```json",
                                json.dumps(result, indent=2, ensure_ascii=False),
                                "```",
                            ])

                    changes = item.get("changesSummary")
                    if changes:
                        lines.extend(["", "#### Changes Summary"])
                        if isinstance(changes, str):
                            lines.extend(["```diff", changes, "```"])
                        elif isinstance(changes, list):
                            for ch in changes:
                                if isinstance(ch, dict):
                                    path = (
                                        ch.get("filePath")
                                        or ch.get("file")
                                        or ch.get("path")
                                        or "File"
                                    )
                                    diff = ch.get("diff")
                                    lines.append(f"**{path}:**")
                                    if diff:
                                        lines.extend(["```diff", str(diff), "```"])
                                else:
                                    lines.append(f"- {ch}")
                        else:
                            lines.extend([
                                "```json",
                                json.dumps(changes, indent=2, ensure_ascii=False),
                                "```",
                            ])

        # Progressing steps section
        if self.chat_state.progressing_steps:
            lines.extend(["", "---", "", "## ⏳ Progressing Steps"])
            for p_step in self.chat_state.progressing_steps:
                if isinstance(p_step, dict):
                    p_name = p_step.get("name") or p_step.get("type") or "Step"
                    p_text = p_step.get("text") or p_step.get("description") or ""
                    lines.append(f"- **{p_name}**: {p_text}")
                else:
                    lines.append(f"- {p_step}")

        # Active requests section
        if self.chat_state.active_requests:
            lines.extend(["", "---", "", "## ❓ Active Requests"])
            for req in self.chat_state.active_requests:
                if isinstance(req, dict):
                    req_type = req.get("type") or req.get("method") or "Request"
                    req_msg = (
                        req.get("message")
                        or req.get("prompt")
                        or req.get("displayText")
                        or str(req)
                    )
                    lines.append(f"- **{req_type}**: {req_msg}")
                else:
                    lines.append(f"- {req}")

        lines.append("")
        return "\n".join(lines)


class TranscriptStorageDriver(ABC):
    """Abstract driver interface for saving transcript documents."""

    @abstractmethod
    async def async_save_transcript(self, doc: TranscriptDocument) -> TranscriptResult:
        """Save a transcript document and return its result URLs."""


class TranscriptStorageError(Exception):
    """Local transcript storage failed closed."""


class TranscriptNotFoundError(TranscriptStorageError):
    """No provably owned transcript exists for the requested identifiers."""


class TranscriptOwnershipError(TranscriptStorageError):
    """A destination exists but is not provably owned and unmodified."""


class TranscriptPublicPathError(TranscriptStorageError):
    """The configured local path resolves inside a publicly served directory."""


TRANSCRIPT_API_PREFIX = "/api/junie_remote/transcripts"
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FILE_NAMES = {"json": "latest.json", "md": "latest.md"}


def known_public_roots(config_dir: Path) -> list[Path]:
    """Roots published by HA /local and this integration's static card route."""
    return [config_dir / "www", Path(__file__).parent / "frontend"]


def safe_component(value: str) -> str:
    """Map an identifier to one filesystem-safe path component (deterministic)."""
    if _SAFE_COMPONENT.match(value) and not value.endswith("."):
        return value
    return "h-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def is_public_path(path: Path | str, public_roots: Iterable[Path | str]) -> bool:
    """Return True if the resolved path equals or is inside a public root."""
    resolved = Path(path).resolve()
    for root in public_roots:
        root_resolved = Path(root).resolve()
        if resolved == root_resolved or resolved.is_relative_to(root_resolved):
            return True
    return False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ensure_private_dir(directory: Path, parent: Path) -> None:
    """Create (if needed) a real directory directly beneath ``parent``."""
    if directory.is_symlink():
        raise TranscriptOwnershipError("Transcript directory is a symlink")
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.resolve() != parent / directory.name:
        raise TranscriptOwnershipError("Transcript directory escapes its root")


_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _read_nofollow(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise TranscriptOwnershipError("Transcript is not a regular file")
        return _read_from_fd(fd)
    finally:
        os.close(fd)


def _read_from_fd(fd: int) -> bytes:
    chunks: list[bytes] = []
    while chunk := os.read(fd, 1 << 20):
        chunks.append(chunk)
    return b"".join(chunks)


def _normalize_endpoint(endpoint: Any) -> str:
    if not isinstance(endpoint, str):
        return ""
    return endpoint.strip().rstrip("/")


def _s3_etag(resp: Any) -> str | None:
    if not isinstance(resp, dict):
        return None
    raw = resp.get("ETag")
    if not raw:
        return None
    etag = str(raw).strip().strip('"')
    return etag or None


def _s3_version(resp: Any) -> str | None:
    if not isinstance(resp, dict):
        return None
    raw = resp.get("VersionId")
    if not raw:
        return None
    version_id = str(raw).strip()
    return version_id if version_id and version_id != "null" else None


def _s3_error_code(err: Exception) -> str:
    resp = getattr(err, "response", None)
    if isinstance(resp, dict):
        code = resp.get("Error", {}).get("Code", "")
        if code:
            return str(code)
    return ""


def _s3_is_not_found(err: Exception) -> bool:
    code = _s3_error_code(err)
    text = str(err).lower()
    return code in {"404", "NoSuchKey", "NotFound", "NoSuchVersion"} or (
        "nosuchkey" in text or "not found" in text or "404" in text
    )


def _endpoint_from_client(client: Any) -> str | None:
    meta = getattr(client, "meta", None)
    url = getattr(meta, "endpoint_url", None)
    return url if isinstance(url, str) else None


def _open_directory_nofollow(path: Path) -> int:
    """Open every component without following symlinks."""
    if not path.is_absolute() or not _O_NOFOLLOW or ".." in path.parts:
        raise OSError("Unsafe directory path or O_NOFOLLOW unavailable")
    flags = os.O_RDONLY | os.O_DIRECTORY | _O_CLOEXEC | _O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _rmdir_empty(path: Path) -> None:
    try:
        parent_fd = _open_directory_nofollow(path.parent)
    except OSError:
        return
    try:
        os.rmdir(path.name, dir_fd=parent_fd)
    except OSError:
        pass
    finally:
        os.close(parent_fd)


def _delete_owned_local_file(
    path_str: str, expected_sha: str
) -> tuple[str | None, bool, bool]:
    """Delete one owned file via dirfd quarantine and report actual unlinking."""
    path = Path(path_str)
    name = path.name
    if (
        not name
        or name in {".", ".."}
        or os.sep in name
        or (os.altsep and os.altsep in name)
    ):
        return f"Refusing unsafe path '{path_str}'", False, False
    try:
        dirfd = _open_directory_nofollow(path.parent)
    except FileNotFoundError:
        return None, False, False
    except OSError as err:
        return (
            f"Cannot open parent directory of '{path_str}': {err}; "
            "retained for manual review",
            False,
            False,
        )
    quarantine: str | None = None
    renamed = False
    try:
        orphans = sorted(n for n in os.listdir(dirfd) if n.startswith(".junie-remote-cleanup-"))
        if orphans:
            return (
                f"quarantine file '{path.parent / orphans[0]}' retained for manual review",
                False,
                False,
            )
        try:
            st = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        except FileNotFoundError:
            return None, False, False
        if stat.S_ISLNK(st.st_mode):
            return f"Refusing to delete symlink '{path_str}'", False, False
        if not stat.S_ISREG(st.st_mode):
            return f"Refusing to delete non-regular file '{path_str}'", False, False
        fd = os.open(name, os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC, dir_fd=dirfd)
        try:
            initial = os.fstat(fd)
            if not stat.S_ISREG(initial.st_mode):
                return f"Refusing to delete non-regular file '{path_str}'", False, False
            content = _read_from_fd(fd)
            if _sha256(content) != expected_sha:
                return (
                    f"Refusing to delete modified file '{path_str}' "
                    "(SHA-256 mismatch)",
                    False,
                    False,
                )
            quarantine = f".junie-remote-cleanup-{uuid.uuid4().hex}"
            os.rename(name, quarantine, src_dir_fd=dirfd, dst_dir_fd=dirfd)
            renamed = True
            fd2 = os.open(
                quarantine, os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC, dir_fd=dirfd
            )
            try:
                quarantined = os.fstat(fd2)
                content2 = _read_from_fd(fd2)
            finally:
                os.close(fd2)
            if (
                (initial.st_dev, initial.st_ino) != (quarantined.st_dev, quarantined.st_ino)
                or not stat.S_ISREG(quarantined.st_mode)
                or _sha256(content2) != expected_sha
            ):
                return (
                    f"Refusing to delete '{path_str}' after quarantine identity mismatch; "
                    f"'{path.parent / quarantine}' retained for manual review",
                    False,
                    True,
                )
            os.unlink(quarantine, dir_fd=dirfd)
            quarantine = None
            return None, True, True
        finally:
            os.close(fd)
    except OSError as err:
        note = ""
        if quarantine is not None and renamed:
            note = f"; quarantine '{path.parent / quarantine}' retained for manual review"
        elif quarantine is not None:
            note = (
                f"; rename to quarantine name '{path.parent / quarantine}' was attempted "
                f"and may not have completed; verify '{path_str}' manually"
            )
        return f"Failed to delete '{path_str}': {err}{note}", False, quarantine is not None
    finally:
        os.close(dirfd)


class LocalTranscriptStorage(TranscriptStorageDriver):
    """Private per-entry storage outside the configured, known public roots."""

    def __init__(
        self,
        base_dir: Path | str,
        entry_id: str,
        inventory: TranscriptInventory,
        public_roots: Iterable[Path | str] = (),
    ) -> None:
        """Initialize local transcript storage."""
        self.base_dir = Path(base_dir)
        self.entry_id = entry_id
        self.inventory = inventory
        self.public_roots = [Path(r) for r in public_roots]
        self.public_path_fallback: str | None = None

    def _resolve_root(self, create: bool) -> Path:
        base = self.base_dir
        if create:
            base.mkdir(mode=0o700, parents=True, exist_ok=True)
        base_real = base.resolve()
        if is_public_path(base_real, self.public_roots):
            raise TranscriptPublicPathError(
                "Local transcript path is inside a publicly served directory"
            )
        entry_dir = base_real / safe_component(self.entry_id)
        if create:
            _ensure_private_dir(entry_dir, base_real)
        elif entry_dir.is_symlink() or (
            entry_dir.exists() and entry_dir.resolve() != entry_dir
        ):
            raise TranscriptOwnershipError("Transcript directory escapes its root")
        return entry_dir

    @staticmethod
    def _check_owned(root: Path, host_dir_name: str, name: str, owned: set[str]) -> None:
        """Reject pre-existing destinations without pre-save ownership proof."""
        host_dir = root / host_dir_name
        _ensure_private_dir(host_dir, root)
        target = host_dir / name
        try:
            existing = os.lstat(target)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not stat.S_ISREG(existing.st_mode):
                raise TranscriptOwnershipError("Transcript destination is not a regular file")
            try:
                current = _read_nofollow(target)
            except OSError as err:
                raise TranscriptOwnershipError("Transcript destination is unreadable") from err
            if _sha256(current) not in owned:
                raise TranscriptOwnershipError(
                    "Transcript destination is not provably owned"
                )

    @staticmethod
    def _write_owned(
        root: Path, host_dir_name: str, name: str, data: bytes, owned: set[str]
    ) -> Path:
        LocalTranscriptStorage._check_owned(root, host_dir_name, name, owned)
        host_dir = root / host_dir_name
        target = host_dir / name
        tmp = host_dir / f".{name}.{uuid.uuid4().hex}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        return target

    async def async_save_transcript(self, doc: TranscriptDocument) -> TranscriptResult:
        """Save transcript privately and return authenticated-view URLs."""
        await self.inventory.async_load()
        return await _await_uncancelled_operation(self._async_save_serialized(doc))

    async def _async_save_serialized(self, doc: TranscriptDocument) -> TranscriptResult:
        write_lock = await self.inventory.async_entry_write_lock(self.entry_id)
        async with write_lock:
            return await self._async_save_locked(doc)

    async def _async_save_locked(self, doc: TranscriptDocument) -> TranscriptResult:
        if self.inventory.is_paused(self.entry_id):
            raise TranscriptStorageError(
                f"Transcript writes are paused for entry '{self.entry_id}'"
            )
        host_dir_name = safe_component(doc.host_key)
        tunnel_name = f"tunnel-{safe_component(doc.tunnel.tunnel_id or 'default')}.json"
        json_bytes = doc.to_json().encode("utf-8")
        md_bytes = doc.render_markdown().encode("utf-8")
        files = [
            ("latest.json", json_bytes),
            ("latest.md", md_bytes),
            (tunnel_name, json_bytes),
        ]
        root = await asyncio.to_thread(self._resolve_root, True)

        prepared = [
            (str(root / host_dir_name / name), _sha256(data)) for name, data in files
        ]
        for name, _ in files:
            path = str(root / host_dir_name / name)
            await asyncio.to_thread(
                self._check_owned, root, host_dir_name, name,
                self.inventory.local_shas(self.entry_id, path),
            )
        prior = await self.inventory.async_prepare_locals(self.entry_id, prepared)
        for index, (name, data) in enumerate(files):
            path, digest = prepared[index]
            try:
                await asyncio.to_thread(
                    self._write_owned, root, host_dir_name, name, data,
                    prior[path],
                )
            except Exception:
                await self.inventory.async_discard_locals(
                    self.entry_id,
                    [item for item in prepared[index:] if item[1] not in prior[item[0]]],
                )
                raise
        await self.inventory.async_commit_locals(self.entry_id, prepared)

        ts_ms = int(time.time() * 1000)
        base = f"{TRANSCRIPT_API_PREFIX}/{self.entry_id}/{quote(doc.host_key, safe='')}"
        return TranscriptResult(
            json_url=f"{base}/json?t={ts_ms}",
            md_url=f"{base}/md?t={ts_ms}",
            updated_at=doc.updated_at,
            last_step_preview=doc.extract_last_step_preview(),
        )

    async def async_read_transcript(self, host_key: str, file_format: str) -> bytes:
        """Return one provably owned, unmodified latest transcript."""
        name = _FILE_NAMES.get(file_format)
        if name is None:
            raise TranscriptNotFoundError("Unknown transcript format")
        await self.inventory.async_load()

        def _read() -> bytes:
            root = self._resolve_root(False)
            host_dir = root / safe_component(host_key)
            if host_dir.is_symlink() or not host_dir.is_dir():
                raise TranscriptNotFoundError("Transcript not found")
            if host_dir.resolve() != host_dir:
                raise TranscriptNotFoundError("Transcript not found")
            path = host_dir / name
            owned = self.inventory.local_shas(self.entry_id, str(path))
            if not owned:
                raise TranscriptNotFoundError("Transcript not found")
            try:
                data = _read_nofollow(path)
            except FileNotFoundError as err:
                raise TranscriptNotFoundError("Transcript not found") from err
            except OSError as err:
                raise TranscriptNotFoundError("Transcript not readable") from err
            if _sha256(data) not in owned:
                raise TranscriptNotFoundError("Transcript is not provably owned")
            return data

        return await asyncio.to_thread(_read)


class S3TranscriptStorage(TranscriptStorageDriver):
    """S3-compatible object storage driver with presigned or CDN URLs."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        region_name: str = "us-east-1",
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        public_url_base: str | None = None,
        key_prefix: str = "junie_remote",
        presign_expiration: int = 3600,
        s3_client: Any | None = None,
        entry_id: str | None = None,
        inventory: TranscriptInventory | None = None,
    ) -> None:
        """Initialize S3 transcript storage."""
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.region_name = region_name
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.public_url_base = public_url_base
        self.key_prefix = key_prefix
        self.presign_expiration = presign_expiration
        self.entry_id = entry_id
        self.inventory = inventory

        if s3_client is not None:
            self._client = s3_client
        else:
            client_kwargs: dict[str, Any] = {
                "service_name": "s3",
                "region_name": self.region_name,
            }
            if self.endpoint_url:
                client_kwargs["endpoint_url"] = self.endpoint_url
            if self.aws_access_key_id:
                client_kwargs["aws_access_key_id"] = self.aws_access_key_id
            if self.aws_secret_access_key:
                client_kwargs["aws_secret_access_key"] = self.aws_secret_access_key

            session = boto3.session.Session()
            self._client = session.client(**client_kwargs)

    @property
    def s3_client(self) -> Any:
        """Return the S3 client used by this driver."""
        return self._client

    async def async_save_transcript(self, doc: TranscriptDocument) -> TranscriptResult:
        """Upload transcript objects to S3 and return public or presigned URLs."""
        if self.inventory and self.entry_id:
            return await _await_uncancelled_operation(self._async_save_serialized(doc))
        return await self._async_save_transcript(doc)

    async def _async_save_serialized(self, doc: TranscriptDocument) -> TranscriptResult:
        async with self.inventory.s3_operation_lock:
            return await self._async_save_transcript(doc)

    async def _async_save_transcript(self, doc: TranscriptDocument) -> TranscriptResult:
        if self.inventory and self.entry_id:
            await self.inventory.async_load()
            if self.inventory.is_paused(self.entry_id):
                raise TranscriptStorageError(
                    f"Transcript writes are paused for entry '{self.entry_id}'"
                )

        prefix = self.key_prefix.strip("/")
        tunnel_id = doc.tunnel.tunnel_id or "default"

        if prefix:
            latest_json_key = f"{prefix}/{doc.host_key}/latest.json"
            latest_md_key = f"{prefix}/{doc.host_key}/latest.md"
            tunnel_json_key = f"{prefix}/{doc.host_key}/{tunnel_id}.json"
        else:
            latest_json_key = f"{doc.host_key}/latest.json"
            latest_md_key = f"{doc.host_key}/latest.md"
            tunnel_json_key = f"{doc.host_key}/{tunnel_id}.json"

        json_bytes = doc.to_json().encode("utf-8")
        md_bytes = doc.render_markdown().encode("utf-8")
        ts_ms = int(time.time() * 1000)

        def _sync_save() -> tuple[str, str, list[dict[str, Any]]]:
            resp_j = self._client.put_object(
                Bucket=self.bucket,
                Key=latest_json_key,
                Body=json_bytes,
                ContentType="application/json",
            )
            resp_m = self._client.put_object(
                Bucket=self.bucket,
                Key=latest_md_key,
                Body=md_bytes,
                ContentType="text/markdown; charset=utf-8",
            )
            resp_t = self._client.put_object(
                Bucket=self.bucket,
                Key=tunnel_json_key,
                Body=json_bytes,
                ContentType="application/json",
            )

            records = [
                {
                    "endpoint": self.endpoint_url,
                    "bucket": self.bucket,
                    "key": latest_json_key,
                    "version_id": _s3_version(resp_j),
                    "etag": _s3_etag(resp_j),
                },
                {
                    "endpoint": self.endpoint_url,
                    "bucket": self.bucket,
                    "key": latest_md_key,
                    "version_id": _s3_version(resp_m),
                    "etag": _s3_etag(resp_m),
                },
                {
                    "endpoint": self.endpoint_url,
                    "bucket": self.bucket,
                    "key": tunnel_json_key,
                    "version_id": _s3_version(resp_t),
                    "etag": _s3_etag(resp_t),
                },
            ]

            if self.public_url_base:
                base = self.public_url_base.rstrip("/")
                j_url = f"{base}/{latest_json_key}?t={ts_ms}"
                m_url = f"{base}/{latest_md_key}?t={ts_ms}"
            else:
                j_url = self._client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": latest_json_key},
                    ExpiresIn=self.presign_expiration,
                )
                m_url = self._client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": latest_md_key},
                    ExpiresIn=self.presign_expiration,
                )
            return j_url, m_url, records

        json_url, md_url, s3_records = await asyncio.to_thread(_sync_save)

        if self.inventory and self.entry_id:
            await self.inventory.async_record_s3(self.entry_id, s3_records)

        return TranscriptResult(
            json_url=json_url,
            md_url=md_url,
            updated_at=doc.updated_at,
            last_step_preview=doc.extract_last_step_preview(),
        )


def create_storage_driver(
    config: dict[str, Any],
    default_local_dir: Path | str,
    *,
    entry_id: str | None = None,
    inventory: TranscriptInventory | None = None,
    public_roots: Iterable[Path | str] = (),
    config_dir: Path | str | None = None,
) -> TranscriptStorageDriver:
    """Create a transcript storage driver based on configuration."""
    storage_type = config.get(CONF_STORAGE_TYPE, DEFAULT_STORAGE_TYPE)

    if storage_type == STORAGE_TYPE_S3:
        bucket = str(config.get(CONF_S3_BUCKET, ""))
        endpoint_url = config.get(CONF_S3_ENDPOINT) or None
        region_name = config.get(CONF_S3_REGION) or "us-east-1"
        aws_access_key_id = config.get(CONF_S3_ACCESS_KEY) or None
        aws_secret_access_key = config.get(CONF_S3_SECRET_KEY) or None
        public_url_base = config.get(CONF_S3_PUBLIC_URL_BASE) or None
        return S3TranscriptStorage(
            bucket=bucket,
            endpoint_url=endpoint_url,
            region_name=region_name,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            public_url_base=public_url_base,
            entry_id=entry_id,
            inventory=inventory,
        )

    # Local storage driver (always private; never a publicly served directory)
    if not entry_id or inventory is None:
        raise ValueError("Local transcript storage requires entry_id and inventory")
    roots = [Path(r) for r in public_roots]
    default_dir = Path(default_local_dir)
    fallback: str | None = None
    local_path = config.get(CONF_LOCAL_STORAGE_PATH)
    base_dir = default_dir
    if local_path:
        p = Path(str(local_path))
        if not p.is_absolute():
            p = Path(config_dir if config_dir is not None else default_dir) / p
        if is_public_path(p, roots):
            fallback = str(local_path)
            _LOGGER.warning(
                "Configured local transcript path '%s' is publicly served; "
                "using the private default instead",
                local_path,
            )
        else:
            base_dir = p

    driver = LocalTranscriptStorage(
        base_dir=base_dir, entry_id=entry_id, inventory=inventory, public_roots=roots
    )
    driver.public_path_fallback = fallback
    return driver


def _s3_storage_from_entry(
    entry: Any,
    entry_id: str,
    inventory: TranscriptInventory,
) -> S3TranscriptStorage | None:
    cfg = {**getattr(entry, "data", {}), **getattr(entry, "options", {})}
    if cfg.get(CONF_STORAGE_TYPE) != STORAGE_TYPE_S3:
        return None
    return S3TranscriptStorage(
        bucket=str(cfg.get(CONF_S3_BUCKET, "")),
        endpoint_url=cfg.get(CONF_S3_ENDPOINT) or None,
        region_name=cfg.get(CONF_S3_REGION) or "us-east-1",
        aws_access_key_id=cfg.get(CONF_S3_ACCESS_KEY) or None,
        aws_secret_access_key=cfg.get(CONF_S3_SECRET_KEY) or None,
        public_url_base=cfg.get(CONF_S3_PUBLIC_URL_BASE) or None,
        entry_id=entry_id,
        inventory=inventory,
    )


def _resolve_s3_cleanup_target(
    hass: Any,
    entry_id: str,
    coord: Any,
    s3_client: Any,
    inventory: TranscriptInventory,
) -> tuple[Any | None, str | None, str | None]:
    """Return (client, endpoint, error)."""
    if s3_client is not None:
        return s3_client, _endpoint_from_client(s3_client), None
    storage = getattr(coord, "storage", None) if coord is not None else None
    if isinstance(storage, S3TranscriptStorage):
        return storage.s3_client, storage.endpoint_url, None
    if hasattr(hass, "config_entries"):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None:
            try:
                built = _s3_storage_from_entry(entry, entry_id, inventory)
            except Exception as err:
                return None, None, f"Could not initialize S3 client: {err}"
            if built is not None:
                return built.s3_client, built.endpoint_url, None
    return None, None, None


def _delete_one_s3_record(
    client: Any, rec: dict[str, Any], client_endpoint: str | None
) -> str | None:
    """Delete one S3 record. None means deleted or already gone."""
    bucket = rec["bucket"]
    key = rec["key"]
    version_id = rec.get("version_id") or None
    if isinstance(version_id, str):
        version_id = version_id.strip() or None
    rec_endpoint = _normalize_endpoint(rec.get("endpoint"))
    live_endpoint = _normalize_endpoint(client_endpoint)
    if rec_endpoint != live_endpoint:
        return (
            f"S3 object '{bucket}/{key}' was recorded at a different endpoint; "
            "retained for manual review"
        )
    if version_id and version_id != "null":
        try:
            client.delete_object(Bucket=bucket, Key=key, VersionId=version_id)
            return None
        except Exception as err:
            if _s3_is_not_found(err):
                return None
            return f"Failed to delete S3 object '{bucket}/{key}': {err}"
    return (
        f"Unversioned S3 object '{bucket}/{key}' cannot be safely deleted; "
        "retained for manual review"
    )


async def async_cleanup_entry_transcripts(
    hass: Any,
    entry_id: str,
    inventory: TranscriptInventory,
    *,
    s3_client: Any = None,
) -> dict[str, Any]:
    """Drain, pause writers, and delete provably owned transcript files and S3 objects."""
    await inventory.async_load()
    return await _await_uncancelled_operation(
        _async_cleanup_entry_serialized(hass, entry_id, inventory, s3_client=s3_client)
    )


async def _async_cleanup_entry_serialized(
    hass: Any, entry_id: str, inventory: TranscriptInventory, *, s3_client: Any
) -> dict[str, Any]:
    op_lock = await inventory.async_entry_op_lock(entry_id)
    async with op_lock:
        return await _async_cleanup_entry_locked(
            hass, entry_id, inventory, s3_client=s3_client
        )


async def _async_cleanup_entry_locked(
    hass: Any,
    entry_id: str,
    inventory: TranscriptInventory,
    *,
    s3_client: Any = None,
) -> dict[str, Any]:
    await inventory.async_pause(entry_id)

    coordinators = (
        hass.data.get(DOMAIN, {})
        if hasattr(hass, "data") and isinstance(hass.data, dict)
        else {}
    )
    coord = coordinators.get(entry_id) if isinstance(coordinators, dict) else None
    if coord and hasattr(coord, "async_drain_saves"):
        await coord.async_drain_saves()

    def _delete_local_records(
        records: list[dict[str, str]],
    ) -> tuple[list[dict[str, str]], int, list[str]]:
        pruned: list[dict[str, str]] = []
        deleted_count = 0
        errors: list[str] = []
        for rec in records:
            path_str = rec["path"]
            expected_sha = rec["sha256"]
            err, unlinked, _ = _delete_owned_local_file(path_str, expected_sha)
            if err:
                errors.append(err)
            else:
                pruned.append({"path": path_str, "sha256": expected_sha})
                deleted_count += int(unlinked)
        parents = sorted(
            {Path(item["path"]).parent for item in pruned},
            key=lambda item: len(item.parts),
            reverse=True,
        )
        for parent in parents:
            _rmdir_empty(parent)
            _rmdir_empty(parent.parent)
        return pruned, deleted_count, errors

    write_lock = await inventory.async_entry_write_lock(entry_id)
    async with write_lock:
        local_recs = inventory.local_records(entry_id)
        pruned_locals, deleted_local_count, local_errors = await asyncio.to_thread(
            _delete_local_records, local_recs
        )
        if pruned_locals:
            await inventory.async_remove_local_records(entry_id, pruned_locals)

    deleted_s3: list[dict[str, Any]] = []
    s3_errors: list[str] = []

    async with inventory.s3_operation_lock:
        deleted_s3, s3_errors = await _async_cleanup_s3(
            hass, entry_id, inventory, coord, s3_client
        )

    if not inventory.local_records(entry_id) and not inventory.s3_records(entry_id):
        await inventory.async_clear_entry(entry_id)

    all_errors = local_errors + s3_errors
    deleted_total = deleted_local_count + len(deleted_s3)
    if all_errors:
        raise HomeAssistantError(
            f"Transcript cleanup partially failed for entry '{entry_id}' "
            f"({deleted_total} deleted). "
            f"The following {len(all_errors)} items were retained for manual review: "
            + "; ".join(all_errors)
        )

    return {
        "deleted_local": deleted_local_count,
        "deleted_s3": len(deleted_s3),
        "errors": [],
    }


async def _async_cleanup_s3(
    hass: Any, entry_id: str, inventory: TranscriptInventory, coord: Any, s3_client: Any
) -> tuple[list[dict[str, Any]], list[str]]:
    s3_recs = inventory.s3_records(entry_id)
    shared = inventory.s3_shared_keys(entry_id)
    deleted_s3: list[dict[str, Any]] = []
    s3_errors: list[str] = []

    if s3_recs:
        client, endpoint, client_error = _resolve_s3_cleanup_target(
            hass, entry_id, coord, s3_client, inventory
        )
        if client_error:
            s3_errors.append(client_error)
        elif client is None:
            s3_errors.append(
                f"Cannot delete S3 objects for entry '{entry_id}': "
                "S3 client not configured or unavailable"
            )
        else:

            def _delete_s3_records() -> tuple[list[dict[str, Any]], list[str]]:
                del_records: list[dict[str, Any]] = []
                errs: list[str] = []
                for rec in s3_recs:
                    key = (_normalize_endpoint(rec.get("endpoint")), rec["bucket"], rec["key"])
                    if key in shared:
                        errs.append(
                            f"S3 object '{rec['bucket']}/{rec['key']}' is shared; "
                            "retained for manual review"
                        )
                        continue
                    err = _delete_one_s3_record(client, rec, endpoint)
                    if err:
                        errs.append(err)
                    else:
                        del_records.append(rec)
                return del_records, errs

            deleted_s3, s3_delete_errors = await asyncio.to_thread(
                _delete_s3_records
            )
            s3_errors.extend(s3_delete_errors)
            if deleted_s3:
                await inventory.async_remove_s3_records(entry_id, deleted_s3)

    return deleted_s3, s3_errors
