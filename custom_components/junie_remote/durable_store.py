# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Fail-closed HA Store reads and writes for durable ownership records."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .ha_compat import Store

_USES_HOMEASSISTANT_STORE = Store.__module__.startswith("homeassistant.")
UNSUPPORTED_STORE_MESSAGE = (
    "Home Assistant Store internals are unsupported; durable ownership cannot be written"
)


def read_store_envelope(
    path: str, key: str, version: int, error_type: type[Exception]
) -> Any:
    """Return the data of a version-1 HA Store file, or None if it does not exist.

    Corrupt, unknown-version or mismatched files raise error_type and are left
    untouched. Unlike HA's default loader, nothing is renamed or reset.
    Migration to a new version must be an explicit, reviewed change.
    """
    try:
        with open(path, encoding="utf-8") as file:
            envelope = json.load(file)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as err:
        raise error_type("Store file is unreadable or corrupt") from err
    if (
        not isinstance(envelope, dict)
        or envelope.get("version") != version
        or envelope.get("minor_version", 1) != 1
        or envelope.get("key") != key
        or envelope.get("data") is None
    ):
        raise error_type("Invalid or unsupported store envelope")
    return envelope["data"]


class DurableStore(Store):
    """Commit before returning, including while HA is stopping.

    HA's async_save may defer writes or swallow write errors, which is unsafe
    when an ownership record must be durable before modifying an artifact.
    Against a real HA Store, a missing private write hook is a hard error rather
    than a silent downgrade to async_save.
    """

    def __init__(
        self,
        hass: Any,
        version: int,
        key: str,
        error_type: type[Exception],
        read_only_message: str,
        read_envelope: Callable[[str], Any],
    ) -> None:
        # serialize_in_event_loop was added in HA 2025.12; omit on older versions.
        store_kwargs: dict[str, Any] = {
            "private": True,
            "atomic_writes": True,
        }
        if _USES_HOMEASSISTANT_STORE:
            import inspect

            sig = inspect.signature(Store.__init__)
            if "serialize_in_event_loop" in sig.parameters:
                store_kwargs["serialize_in_event_loop"] = False
        super().__init__(hass, version, key, **store_kwargs)
        self._ownership_error = error_type
        self._read_only_message = read_only_message
        self._read_envelope = read_envelope
        if _USES_HOMEASSISTANT_STORE and not hasattr(self, "_async_write_data"):
            raise error_type(UNSUPPORTED_STORE_MESSAGE)

    async def _async_load_data(self) -> Any:
        manager = getattr(self, "_manager", None)
        if not _USES_HOMEASSISTANT_STORE or self._data is not None:
            return await super()._async_load_data()
        if manager is not None and manager.async_fetch(self.key):
            return await super()._async_load_data()
        # Manager not set (async_open not called) or nothing cached —
        # fall back to reading the envelope directly rather than relying
        # on the HA Store internals that require async_open().
        return await self.hass.async_add_executor_job(self._read_envelope, self.path)

    async def async_save(self, data: dict[str, Any]) -> None:
        if not _USES_HOMEASSISTANT_STORE:
            await super().async_save(data)
            return
        envelope = {
            "version": self.version, "minor_version": self.minor_version,
            "key": self.key, "data": data,
        }
        async with self._write_lock:
            if self._read_only:
                raise self._ownership_error(self._read_only_message)
            await self._async_write_data(self.path, envelope)
            manager = getattr(self, "_manager", None)
            if manager is not None:
                manager.async_invalidate(self.key)
