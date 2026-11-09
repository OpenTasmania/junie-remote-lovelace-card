# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Durable, integration-wide ownership for shared frontend artifacts."""

from __future__ import annotations

import asyncio
import copy
import re
from pathlib import Path
from typing import Any

from .durable_store import DurableStore, read_store_envelope

ARTIFACT_STORE_KEY = "junie_remote_artifact_ownership"
ARTIFACT_STORE_VERSION = 1
ARTIFACT_HASS_KEY = "junie_remote_artifact_ledger"


class ArtifactLedgerError(Exception):
    """The artifact ledger cannot establish durable ownership."""


def _read_envelope(path: str) -> Any:
    return read_store_envelope(
        path, ARTIFACT_STORE_KEY, ARTIFACT_STORE_VERSION, ArtifactLedgerError
    )


def _validate(data: Any) -> dict[str, Any]:
    if data is None:
        return {"file": None, "resource": None}
    if not isinstance(data, dict) or set(data) != {"file", "resource"}:
        raise ArtifactLedgerError("Invalid artifact ownership data")
    file = data["file"]
    if file is not None and (
        not isinstance(file, dict)
        or set(file) != {"path", "sha256"}
        or not isinstance(file["path"], str)
        or not Path(file["path"]).is_absolute()
        or not isinstance(file["sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", file["sha256"])
    ):
        raise ArtifactLedgerError("Invalid artifact file identity")
    resource = data["resource"]
    if resource is not None and (
        not isinstance(resource, dict)
        or set(resource) != {"id", "type", "url"}
        or not all(isinstance(value, str) and value for value in resource.values())
    ):
        raise ArtifactLedgerError("Invalid artifact resource identity")
    return copy.deepcopy(data)


class ArtifactLedger:
    """The file slot is invalidated before changing the corresponding file."""

    def __init__(self, hass: Any) -> None:
        self._store = DurableStore(
            hass, ARTIFACT_STORE_VERSION, ARTIFACT_STORE_KEY, ArtifactLedgerError,
            "Artifact store is read-only", _read_envelope,
        )
        self._data: dict[str, Any] | None = None
        self._lock = asyncio.Lock()
        self.operation_lock = asyncio.Lock()

    async def async_load(self) -> None:
        async with self._lock:
            if self._data is not None:
                return
            try:
                self._data = _validate(await self._store.async_load())
            except Exception as err:
                raise ArtifactLedgerError("Artifact ledger could not be loaded") from err

    @property
    def file(self) -> dict[str, str] | None:
        if self._data is None:
            raise ArtifactLedgerError("Artifact ledger is not loaded")
        return copy.deepcopy(self._data["file"])

    @property
    def resource(self) -> dict[str, str] | None:
        if self._data is None:
            raise ArtifactLedgerError("Artifact ledger is not loaded")
        return copy.deepcopy(self._data["resource"])

    async def async_set_file(self, record: dict[str, str] | None) -> None:
        await self._async_set("file", record)

    async def async_set_resource(self, record: dict[str, str] | None) -> None:
        await self._async_set("resource", record)

    async def _async_set(self, slot: str, record: dict[str, str] | None) -> None:
        async with self._lock:
            if self._data is None:
                raise ArtifactLedgerError("Artifact ledger is not loaded")
            snapshot = copy.deepcopy(self._data)
            snapshot[slot] = copy.deepcopy(record)
            _validate(snapshot)
            task = asyncio.create_task(self._store.async_save(snapshot))
            cancelled = False
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled = True
                except Exception:
                    break
            try:
                task.result()
            except Exception as err:
                self._data = None
                raise ArtifactLedgerError("Artifact ledger could not be saved") from err
            self._data = snapshot
            if cancelled:
                raise asyncio.CancelledError
