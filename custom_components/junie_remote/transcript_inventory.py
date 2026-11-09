# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Durable ownership inventory for transcript files written by this integration.

The inventory is an HA ``Store`` (version 1, key ``junie_remote_transcript_ownership``)::

    {"entries": {entry_id: {"local": [{"path", "sha256"}],
                            "s3": [{"endpoint", "bucket", "key", "version_id", "etag"}],
                            "paused": false}}}

Only objects the integration wrote after this inventory existed are recorded.
Nothing here is ever inferred from a path or prefix, and credentials are never stored.
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any

from .durable_store import DurableStore, read_store_envelope

INVENTORY_STORE_KEY = "junie_remote_transcript_ownership"
INVENTORY_STORE_VERSION = 1
INVENTORY_HASS_KEY = "junie_remote_transcript_inventory"
MAX_S3_VERSIONS_PER_KEY = 1


class TranscriptInventoryError(Exception):
    """The inventory cannot be loaded or persisted; callers must fail closed."""


def _read_envelope(path: str) -> Any:
    return read_store_envelope(
        path, INVENTORY_STORE_KEY, INVENTORY_STORE_VERSION, TranscriptInventoryError
    )


def _new_entry() -> dict[str, Any]:
    return {"local": [], "s3": [], "paused": False}


def _clean_s3_record(rec: dict[str, Any]) -> dict[str, Any]:
    etag = rec.get("etag")
    if isinstance(etag, str):
        etag = etag.strip().strip('"') or None
    else:
        etag = None
    version_id = rec.get("version_id")
    if isinstance(version_id, str):
        version_id = version_id.strip() or None
        if version_id == "null":
            version_id = None
    else:
        version_id = None
    endpoint = rec.get("endpoint")
    if isinstance(endpoint, str):
        endpoint = endpoint.strip() or None
    else:
        endpoint = None
    return {
        "endpoint": endpoint,
        "bucket": rec["bucket"],
        "key": rec["key"],
        "version_id": version_id,
        "etag": etag,
    }


def _unversioned_key(rec: dict[str, Any]) -> tuple[Any, str, str]:
    return rec.get("endpoint"), rec["bucket"], rec["key"]


def _validate(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {"entries": {}}
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), dict):
        raise TranscriptInventoryError("Transcript ownership inventory is corrupt")
    for entry in raw["entries"].values():
        if not isinstance(entry, dict):
            raise TranscriptInventoryError("Transcript ownership inventory is corrupt")
        if not isinstance(entry.get("local"), list) or not isinstance(entry.get("s3"), list):
            raise TranscriptInventoryError("Transcript ownership inventory is corrupt")
        for rec in entry["local"]:
            if (
                not isinstance(rec, dict)
                or not isinstance(rec.get("path"), str)
                or not isinstance(rec.get("sha256"), str)
            ):
                raise TranscriptInventoryError("Transcript ownership inventory is corrupt")
        for rec in entry["s3"]:
            if (
                not isinstance(rec, dict)
                or not isinstance(rec.get("bucket"), str)
                or not isinstance(rec.get("key"), str)
                or not (rec.get("endpoint") is None or isinstance(rec.get("endpoint"), str))
                or not (rec.get("version_id") is None or isinstance(rec.get("version_id"), str))
                or not (rec.get("etag") is None or isinstance(rec.get("etag"), str))
            ):
                raise TranscriptInventoryError("Transcript ownership inventory is corrupt")
        entry["paused"] = bool(entry.get("paused", False))
    return raw


class TranscriptInventory:
    """Serialized, persistent record of exact transcript files owned per entry."""

    def __init__(self, hass: Any) -> None:
        self._store = DurableStore(
            hass, INVENTORY_STORE_VERSION, INVENTORY_STORE_KEY, TranscriptInventoryError,
            "Transcript ownership inventory is read-only", _read_envelope,
        )
        self._data: dict[str, Any] | None = None
        self._lock = asyncio.Lock()
        self._op_locks: dict[str, asyncio.Lock] = {}
        self._entry_write_locks: dict[str, asyncio.Lock] = {}
        self.s3_operation_lock = asyncio.Lock()

    async def async_load(self) -> None:
        """Load the inventory once; unreadable or unknown data fails closed."""
        async with self._lock:
            if self._data is not None:
                return
            try:
                raw = await self._store.async_load()
            except Exception as err:
                raise TranscriptInventoryError(
                    "Transcript ownership inventory could not be loaded"
                ) from err
            self._data = _validate(raw)

    def _require(self) -> dict[str, Any]:
        if self._data is None:
            raise TranscriptInventoryError("Transcript ownership inventory is not loaded")
        return self._data

    async def _async_save(self, snapshot: dict[str, Any]) -> None:
        task = asyncio.create_task(self._store.async_save(snapshot))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # The executor may still replace the inventory after cancellation.
                # Hold the lock until its outcome is known, even after repeat cancels.
                cancelled = True
            except Exception:
                # Inspect and wrap the completed task's error below.
                break
        try:
            task.result()
        except Exception as err:
            raise TranscriptInventoryError(
                "Transcript ownership inventory could not be saved"
            ) from err
        self._data = snapshot
        if cancelled:
            raise asyncio.CancelledError

    def is_paused(self, entry_id: str) -> bool:
        """Return True if transcript writes are paused for entry_id."""
        entry = self._require()["entries"].get(entry_id)
        return bool(entry.get("paused", False)) if entry else False

    def has_entry(self, entry_id: str) -> bool:
        """Return True if the inventory has a record for entry_id."""
        return entry_id in self._require()["entries"]

    async def async_entry_op_lock(self, entry_id: str) -> asyncio.Lock:
        """Return the per-entry lock that serializes cleanup and resume."""
        async with self._lock:
            return self._op_locks.setdefault(entry_id, asyncio.Lock())

    async def async_entry_write_lock(self, entry_id: str) -> asyncio.Lock:
        """Return the per-entry lock that serializes local saves and cleanup."""
        async with self._lock:
            return self._entry_write_locks.setdefault(entry_id, asyncio.Lock())

    async def async_pause(self, entry_id: str) -> None:
        """Persistently pause transcript writes for entry_id."""
        async with self._lock:
            data = self._require()
            snapshot = copy.deepcopy(data)
            entry = snapshot["entries"].setdefault(entry_id, _new_entry())
            entry["paused"] = True
            if snapshot != data:
                await self._async_save(snapshot)

    async def async_resume(self, entry_id: str) -> None:
        """Persistently resume transcript writes for entry_id."""
        op_lock = await self.async_entry_op_lock(entry_id)
        async with op_lock:
            async with self._lock:
                data = self._require()
                snapshot = copy.deepcopy(data)
                entry = snapshot["entries"].get(entry_id)
                if entry and entry.get("paused"):
                    entry["paused"] = False
                    await self._async_save(snapshot)

    def s3_records(self, entry_id: str) -> list[dict[str, Any]]:
        """Return a copy of an entry's S3 ownership records."""
        entry = self._require()["entries"].get(entry_id)
        return copy.deepcopy(entry["s3"]) if entry else []

    def s3_shared_keys(self, entry_id: str) -> set[tuple[str, str, str]]:
        """Return keys claimed by other entries, including removed entries."""
        return {
            ((rec.get("endpoint") or "").strip().rstrip("/"), rec["bucket"], rec["key"])
            for other_id, entry in self._require()["entries"].items()
            if other_id != entry_id
            for rec in entry["s3"]
        }

    async def async_record_s3(
        self, entry_id: str, records: list[dict[str, Any]]
    ) -> None:
        """Atomically record S3 object ownership for an entry."""
        async with self._lock:
            data = self._require()
            snapshot = copy.deepcopy(data)
            entry = snapshot["entries"].setdefault(entry_id, _new_entry())
            for rec in records:
                cleaned = _clean_s3_record(rec)
                if cleaned["version_id"]:
                    key = _unversioned_key(cleaned)
                    entry["s3"] = [
                        existing
                        for existing in entry["s3"]
                        if existing.get("version_id") in (None, "", "null")
                        or _unversioned_key(existing) != key
                        or existing.get("version_id") != cleaned["version_id"]
                    ]
                    entry["s3"].append(cleaned)
                    versioned = [
                        existing
                        for existing in entry["s3"]
                        if existing.get("version_id") not in (None, "", "null")
                        and _unversioned_key(existing) == key
                    ]
                    if len(versioned) > MAX_S3_VERSIONS_PER_KEY:
                        keep = {
                            id(existing)
                            for existing in versioned[-MAX_S3_VERSIONS_PER_KEY:]
                        }
                        entry["s3"] = [
                            existing
                            for existing in entry["s3"]
                            if existing.get("version_id") in (None, "", "null")
                            or _unversioned_key(existing) != key
                            or id(existing) in keep
                        ]
                    continue
                key = _unversioned_key(cleaned)
                entry["s3"] = [
                    existing
                    for existing in entry["s3"]
                    if existing.get("version_id") not in (None, "", "null")
                    or _unversioned_key(existing) != key
                ]
                entry["s3"].append(cleaned)
            if snapshot != data:
                await self._async_save(snapshot)

    async def async_remove_s3_records(
        self, entry_id: str, removed: list[dict[str, Any]]
    ) -> None:
        """Prune specific S3 records from an entry's inventory."""
        async with self._lock:
            data = self._require()
            snapshot = copy.deepcopy(data)
            entry = snapshot["entries"].get(entry_id)
            if not entry:
                return
            entry["s3"] = [
                r
                for r in entry["s3"]
                if not any(
                    r.get("endpoint") == rem.get("endpoint")
                    and r.get("bucket") == rem.get("bucket")
                    and r.get("key") == rem.get("key")
                    and r.get("version_id") == rem.get("version_id")
                    and r.get("etag") == rem.get("etag")
                    for rem in removed
                )
            ]
            if snapshot != data:
                await self._async_save(snapshot)

    async def async_remove_local_records(
        self, entry_id: str, records: list[dict[str, str]]
    ) -> None:
        """Prune exact local (path, sha256) records from an entry's inventory."""
        async with self._lock:
            data = self._require()
            snapshot = copy.deepcopy(data)
            entry = snapshot["entries"].get(entry_id)
            if not entry:
                return
            removed = {(r["path"], r["sha256"]) for r in records}
            entry["local"] = [
                r for r in entry["local"] if (r["path"], r["sha256"]) not in removed
            ]
            if snapshot != data:
                await self._async_save(snapshot)

    async def async_clear_entry(self, entry_id: str) -> None:
        """Clear all records for an entry while retaining pause state."""
        async with self._lock:
            data = self._require()
            snapshot = copy.deepcopy(data)
            entry = snapshot["entries"].get(entry_id)
            if entry:
                entry["local"] = []
                entry["s3"] = []
                if snapshot != data:
                    await self._async_save(snapshot)

    def local_shas(self, entry_id: str, path: str) -> set[str]:
        """Return digests recorded as owned for an exact local path."""
        entry = self._require()["entries"].get(entry_id)
        if not entry:
            return set()
        return {r["sha256"] for r in entry["local"] if r["path"] == path}

    def local_records(self, entry_id: str) -> list[dict[str, str]]:
        """Return a copy of an entry's local ownership records."""
        entry = self._require()["entries"].get(entry_id)
        return copy.deepcopy(entry["local"]) if entry else []

    async def async_prepare_locals(
        self, entry_id: str, files: list[tuple[str, str]]
    ) -> dict[str, set[str]]:
        """Atomically record all new digests before any destination is replaced."""
        async with self._lock:
            data = self._require()
            snapshot = copy.deepcopy(data)
            entry = snapshot["entries"].setdefault(entry_id, _new_entry())
            prior = {
                path: {r["sha256"] for r in entry["local"] if r["path"] == path}
                for path, _ in files
            }
            for path, sha256 in files:
                record = {"path": path, "sha256": sha256}
                if record not in entry["local"]:
                    entry["local"].append(record)
            if snapshot != data:
                await self._async_save(snapshot)
            return prior

    async def async_commit_locals(
        self, entry_id: str, files: list[tuple[str, str]]
    ) -> None:
        """Prune superseded digests after all replacements have succeeded."""
        async with self._lock:
            data = self._require()
            snapshot = copy.deepcopy(data)
            selected = dict(files)
            entry = snapshot["entries"].get(entry_id)
            if not entry:
                return
            entry["local"] = [
                r for r in entry["local"]
                if r["path"] not in selected or r["sha256"] == selected[r["path"]]
            ]
            if snapshot != data:
                await self._async_save(snapshot)

    async def async_discard_locals(
        self, entry_id: str, files: list[tuple[str, str]]
    ) -> None:
        """Discard only newly prepared intents for writes that were refused."""
        async with self._lock:
            data = self._require()
            snapshot = copy.deepcopy(data)
            entry = snapshot["entries"].get(entry_id)
            if not entry:
                return
            rejected = set(files)
            entry["local"] = [
                r for r in entry["local"]
                if (r["path"], r["sha256"]) not in rejected
            ]
            if snapshot != data:
                await self._async_save(snapshot)

    async def async_prepare_local(self, entry_id: str, path: str, sha256: str) -> None:
        """Persist intent to write ``sha256`` at ``path`` before touching the file."""
        await self.async_prepare_locals(entry_id, [(path, sha256)])

    async def async_commit_local(self, entry_id: str, path: str, sha256: str) -> None:
        """After a successful replace, drop superseded digests for the path."""
        await self.async_commit_locals(entry_id, [(path, sha256)])

    async def async_discard_local(self, entry_id: str, path: str, sha256: str) -> None:
        """Remove a pending record whose write was refused before any replace."""
        await self.async_discard_locals(entry_id, [(path, sha256)])
