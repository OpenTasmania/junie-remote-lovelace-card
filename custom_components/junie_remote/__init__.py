# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""JetBrains Junie Remote integration for Home Assistant."""

from __future__ import annotations

import asyncio
import ctypes
import errno
import hashlib
import logging
import os
import stat
import tempfile
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .artifact_ledger import ARTIFACT_HASS_KEY, ArtifactLedger
from .client import JunieRemoteClient
from .const import (
    BASE_URL,
    CONF_COOKIE_HEADER,
    CONF_STORAGE_STATE,
    DOMAIN,
    SERVICE_CANCEL,
    SERVICE_CANCEL_TASK,
    SERVICE_CLEANUP_TRANSCRIPTS,
    SERVICE_CONFIRM_PLAN,
    SERVICE_KICK_CLIENT,
    SERVICE_RESPOND,
    SERVICE_RESPOND_REQUEST,
    SERVICE_RESUME_TRANSCRIPTS,
    SERVICE_SELECT_MODEL,
    SERVICE_SEND_PLAN_PROMPT,
    SERVICE_SEND_PROMPT,
    SERVICE_TOGGLE_BRAVE_MODE,
)
from .coordinator import JunieRemoteCoordinator
from .durable_store import read_store_envelope
from .ha_compat import (
    EVENT_HOMEASSISTANT_STARTED,
    HAS_HOMEASSISTANT,
    ConfigEntry,
    HomeAssistant,
    HomeAssistantError,
    ServiceCall,
    StaticPathConfig,
    Unauthorized,
    cv,
)
from .storage import (
    _delete_owned_local_file,
    async_cleanup_entry_transcripts,
    create_storage_driver,
    known_public_roots,
)
from .transcript_http import async_register_transcript_view
from .transcript_inventory import INVENTORY_HASS_KEY, TranscriptInventory

_LOGGER = logging.getLogger(__name__)
_ARTIFACT_GENERATION = "junie_remote_artifact_generation"

PLATFORMS: list[str] = ["sensor", "switch", "select", "button"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _extract_host_key(hass: HomeAssistant, call_data: dict[str, Any]) -> str:
    """Extract or deduce host_key from service call data."""
    host_key = call_data.get("host_key")
    if host_key:
        return str(host_key).strip()

    entity_id = call_data.get("entity_id")
    if isinstance(entity_id, list) and entity_id:
        entity_id = entity_id[0]
    if isinstance(entity_id, str):
        obj_id = entity_id.split(".", 1)[-1]

        # Check if obj_id directly matches or contains any known host_key
        coordinators = hass.data.get(DOMAIN, {}).values()
        for coord in coordinators:
            if hasattr(coord, "hosts"):
                for k in coord.hosts:
                    if (
                        k == obj_id
                        or obj_id.startswith(f"{k}_")
                        or f"_{k}_" in obj_id
                        or obj_id.endswith(f"_{k}")
                    ):
                        return k

        # Strip standard entity platform suffixes
        for suffix in (
            "_status",
            "_brave_mode",
            "_model_effort",
            "_stop",
            "_confirm_plan",
            "_take_over",
        ):
            if obj_id.endswith(suffix):
                obj_id = obj_id[: -len(suffix)]
                break

        # Strip integration prefix if prepended
        if obj_id.startswith("junie_remote_"):
            obj_id = obj_id[len("junie_remote_") :]
        elif obj_id.startswith("junie_"):
            obj_id = obj_id[len("junie_") :]

        return obj_id

    # Fallback: if exactly one host exists across coordinators, resolve to it
    all_hosts: list[str] = []
    for coord in hass.data.get(DOMAIN, {}).values():
        if hasattr(coord, "hosts"):
            all_hosts.extend(coord.hosts.keys())
    if len(all_hosts) == 1:
        return all_hosts[0]

    raise ValueError(
        "Could not determine target host_key from service call data. "
        "Please provide 'host_key' or 'entity_id'."
    )


def _get_coordinator_for_host(
    hass: HomeAssistant, host_key: str
) -> JunieRemoteCoordinator:
    """Find coordinator responsible for managing host_key."""
    coordinators: list[JunieRemoteCoordinator] = [
        c
        for c in hass.data.get(DOMAIN, {}).values()
        if isinstance(c, JunieRemoteCoordinator)
    ]
    for coord in coordinators:
        if host_key in coord.hosts:
            return coord
    if len(coordinators) == 1:
        return coordinators[0]
    if not coordinators:
        raise ValueError("No active Junie Remote coordinators available")
    raise ValueError(f"No Junie Remote coordinator found for host_key '{host_key}'")


def _build_response_payload(
    call_data: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Build standardized protocol response payload and display text from service data."""
    if "response_payload" in call_data and isinstance(
        call_data["response_payload"], dict
    ):
        display_text = str(call_data.get("display_text") or "OK")
        return display_text, dict(call_data["response_payload"])

    method = str(call_data.get("method") or "ask").lower()
    request_id = str(call_data.get("request_id") or "")
    display_text = call_data.get("display_text")

    if method == "ask":
        resp_val = call_data.get("response", "")
        payload = {
            "method": "ask",
            "requestId": request_id,
            "response": resp_val,
        }
        if not display_text:
            display_text = str(resp_val) if resp_val is not None else "OK"

    elif method == "choice":
        option_id = str(call_data.get("option_id") or "")
        payload = {
            "method": "choice",
            "requestId": request_id,
            "optionId": option_id,
        }
        if not display_text:
            display_text = option_id

    elif method == "approve":
        approve_val = bool(call_data.get("approve", True))
        add_to_allow_list = bool(call_data.get("add_to_allow_list", False))
        payload = {
            "method": "approve",
            "requestId": request_id,
            "approve": approve_val,
        }
        if add_to_allow_list:
            payload["addToAllowList"] = True
            payload["optionIndex"] = int(call_data.get("option_index", 0))

        if not display_text:
            if not approve_val:
                display_text = "Deny"
            elif add_to_allow_list:
                display_text = "Always allow"
            else:
                display_text = "Allow once"

    elif method in ("cancel", "action"):
        payload = {
            "method": "cancel",
            "requestId": request_id,
        }
        if not display_text:
            display_text = "OK"

    elif method == "ask-async":
        option_ids = call_data.get("option_ids")
        if option_ids is None and "option_id" in call_data:
            option_ids = [call_data["option_id"]]
        resp_val = call_data.get("response")
        payload = {
            "method": "ask-async",
            "requestId": request_id,
            "optionIds": list(option_ids) if option_ids else [],
            "response": resp_val,
        }
        if not display_text:
            display_text = str(resp_val) if resp_val else "OK"

    else:
        payload = {
            "method": method,
            "requestId": request_id,
        }
        for k in (
            "response",
            "option_id",
            "option_ids",
            "approve",
            "add_to_allow_list",
            "option_index",
        ):
            if k in call_data:
                camel_k = "".join(
                    word.capitalize() if i > 0 else word
                    for i, word in enumerate(k.split("_"))
                )
                payload[camel_k] = call_data[k]
        if not display_text:
            display_text = "OK"

    return str(display_text), payload


def _get_or_create_inventory(hass: HomeAssistant) -> TranscriptInventory:
    """Return or initialize the shared TranscriptInventory instance."""
    if INVENTORY_HASS_KEY not in hass.data:
        hass.data[INVENTORY_HASS_KEY] = TranscriptInventory(hass)
    return hass.data[INVENTORY_HASS_KEY]


async def _async_require_admin_service_call(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    """Ensure the service call is initiated by an authenticated Home Assistant admin."""
    context = getattr(call, "context", None)
    user_id = getattr(context, "user_id", None) if context else None
    if not user_id:
        raise Unauthorized(context=context)
    auth = getattr(hass, "auth", None)
    if auth and hasattr(auth, "async_get_user"):
        user = await auth.async_get_user(user_id)
        if user is None or not getattr(user, "is_admin", False):
            raise Unauthorized(context=context, user_id=user_id)
    else:
        if getattr(context, "is_admin", None) is not True:
            raise Unauthorized(context=context, user_id=user_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register all domain services for Junie Remote."""
    if not hasattr(hass, "services"):
        return

    async def handle_send_prompt(call: ServiceCall) -> None:
        host_key = _extract_host_key(hass, call.data)
        coord = _get_coordinator_for_host(hass, host_key)
        prompt = str(call.data.get("prompt", ""))
        await coord.async_send_prompt(host_key, prompt)

    async def handle_send_plan_prompt(call: ServiceCall) -> None:
        host_key = _extract_host_key(hass, call.data)
        coord = _get_coordinator_for_host(hass, host_key)
        prompt = str(call.data.get("prompt", ""))
        await coord.async_send_plan_prompt(host_key, prompt)

    async def handle_respond_request(call: ServiceCall) -> None:
        host_key = _extract_host_key(hass, call.data)
        coord = _get_coordinator_for_host(hass, host_key)
        display_text, payload = _build_response_payload(call.data)
        await coord.async_respond_request(host_key, display_text, payload)

    async def handle_select_model(call: ServiceCall) -> None:
        host_key = _extract_host_key(hass, call.data)
        coord = _get_coordinator_for_host(hass, host_key)
        model_id = str(call.data.get("model_id", ""))
        effort_id = call.data.get("effort_id")
        if effort_id is not None:
            effort_id = str(effort_id)
        await coord.async_select_model(host_key, model_id, effort_id)

    async def handle_kick_client(call: ServiceCall) -> None:
        host_key = _extract_host_key(hass, call.data)
        coord = _get_coordinator_for_host(hass, host_key)
        await coord.async_kick_and_takeover(host_key)

    async def handle_confirm_plan(call: ServiceCall) -> None:
        host_key = _extract_host_key(hass, call.data)
        coord = _get_coordinator_for_host(hass, host_key)
        await coord.async_confirm_plan(host_key)

    async def handle_cancel_task(call: ServiceCall) -> None:
        host_key = _extract_host_key(hass, call.data)
        coord = _get_coordinator_for_host(hass, host_key)
        await coord.async_cancel(host_key)

    async def handle_toggle_brave_mode(call: ServiceCall) -> None:
        host_key = _extract_host_key(hass, call.data)
        coord = _get_coordinator_for_host(hass, host_key)
        enabled = bool(call.data.get("enabled", True))
        await coord.async_toggle_brave_mode(host_key, enabled)

    async def handle_cleanup_transcripts(call: ServiceCall) -> None:
        await _async_require_admin_service_call(hass, call)
        if call.data.get("confirm") is not True:
            raise HomeAssistantError(
                "Transcript cleanup requires explicit confirmation (confirm: true)"
            )
        entry_id = str(call.data.get("entry_id") or "").strip()
        if not entry_id:
            raise HomeAssistantError("Config entry ID (entry_id) is required")
        inventory = _get_or_create_inventory(hass)
        await inventory.async_load()
        entry_exists = False
        if (
            hasattr(hass, "config_entries")
            and hass.config_entries.async_get_entry(entry_id)
        ):
            entry_exists = True
        elif inventory.has_entry(entry_id):
            entry_exists = True
        if not entry_exists:
            raise HomeAssistantError(f"Config entry '{entry_id}' not found")
        await async_cleanup_entry_transcripts(hass, entry_id, inventory)

    async def handle_resume_transcripts(call: ServiceCall) -> None:
        await _async_require_admin_service_call(hass, call)
        entry_id = str(call.data.get("entry_id") or "").strip()
        if not entry_id:
            raise HomeAssistantError("Config entry ID (entry_id) is required")
        inventory = _get_or_create_inventory(hass)
        await inventory.async_load()
        entry_exists = False
        if (
            hasattr(hass, "config_entries")
            and hass.config_entries.async_get_entry(entry_id)
        ):
            entry_exists = True
        elif inventory.has_entry(entry_id):
            entry_exists = True
        if not entry_exists:
            raise HomeAssistantError(f"Config entry '{entry_id}' not found")
        await inventory.async_resume(entry_id)

    services_to_register = [
        (SERVICE_SEND_PROMPT, handle_send_prompt),
        (SERVICE_SEND_PLAN_PROMPT, handle_send_plan_prompt),
        (SERVICE_RESPOND_REQUEST, handle_respond_request),
        (SERVICE_RESPOND, handle_respond_request),
        (SERVICE_SELECT_MODEL, handle_select_model),
        (SERVICE_KICK_CLIENT, handle_kick_client),
        (SERVICE_CONFIRM_PLAN, handle_confirm_plan),
        (SERVICE_CANCEL_TASK, handle_cancel_task),
        (SERVICE_CANCEL, handle_cancel_task),
        (SERVICE_TOGGLE_BRAVE_MODE, handle_toggle_brave_mode),
        (SERVICE_CLEANUP_TRANSCRIPTS, handle_cleanup_transcripts),
        (SERVICE_RESUME_TRANSCRIPTS, handle_resume_transcripts),
    ]

    for service_name, handler in services_to_register:
        if not hass.services.has_service(DOMAIN, service_name):
            hass.services.async_register(DOMAIN, service_name, handler)


def _async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister all domain services if no coordinators remain."""
    if not hasattr(hass, "services"):
        return
    for service_name in (
        SERVICE_SEND_PROMPT,
        SERVICE_SEND_PLAN_PROMPT,
        SERVICE_RESPOND_REQUEST,
        SERVICE_RESPOND,
        SERVICE_SELECT_MODEL,
        SERVICE_KICK_CLIENT,
        SERVICE_CONFIRM_PLAN,
        SERVICE_CANCEL_TASK,
        SERVICE_CANCEL,
        SERVICE_TOGGLE_BRAVE_MODE,
        SERVICE_CLEANUP_TRANSCRIPTS,
        SERVICE_RESUME_TRANSCRIPTS,
    ):
        if hass.services.has_service(DOMAIN, service_name):
            hass.services.async_remove(DOMAIN, service_name)


def _fallback_snapshot(source: Path, target: Path) -> tuple[bytes, tuple | None] | None:
    """Read source and destination in a worker; never follow destination symlinks."""
    if target.parent.is_symlink():
        raise OSError("Fallback directory is a symlink")
    if not target.parent.is_dir() or not source.is_file():
        return None
    contents = source.read_bytes()
    return contents, _fallback_identity(target)


def _fallback_identity(target: Path) -> tuple | None:
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise OSError("Fallback destination is not a regular file")
        digest = hashlib.sha256(file.read()).hexdigest()
        return info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size, digest


def _exchange_fallback(first: str, second: str) -> None:
    """Atomically exchange paths, or fail closed where unsupported."""
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as err:
        raise OSError(errno.ENOTSUP, "Atomic exchange is unavailable") from err
    renameat2.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(first), -100, os.fsencode(second), 2) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _fallback_directory_identity(target: Path) -> tuple[int, int]:
    info = os.stat(target.parent, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode):
        raise OSError("Fallback directory is not a directory")
    return info.st_dev, info.st_ino


def _fallback_unchanged(target: Path, previous: tuple, directory: tuple[int, int]) -> bool:
    return (
        _fallback_directory_identity(target) == directory
        and _fallback_identity(target) == previous
        and _fallback_directory_identity(target) == directory
    )


def _publish_fallback(
    target: Path, contents: bytes, previous: tuple | None, publication: dict[str, bool]
) -> None:
    """Publish complete bytes atomically; never overwrite on initial creation."""
    directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory_info = os.fstat(directory)
    anchored = Path(f"/proc/self/fd/{directory}")
    try:
        fd, temporary = tempfile.mkstemp(prefix=".junie-card-", dir=anchored)
    except BaseException:
        os.close(directory)
        raise
    remove_temporary = True
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(contents)
            file.flush()
            os.fchmod(file.fileno(), 0o644)
            os.fsync(file.fileno())
        def verify_directory() -> None:
            info = os.stat(target.parent, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != (
                directory_info.st_dev, directory_info.st_ino
            ):
                raise OSError("Fallback directory changed during update")

        verify_directory()
        anchored_target = anchored / target.name
        if previous is None:
            os.link(temporary, anchored_target, follow_symlinks=False)
            publication["mutated"] = True
        else:
            # Recheck the file immediately before the atomic replacement.
            current = _fallback_snapshot(target, target)
            if current is None or current[1] != previous:
                raise OSError("Fallback destination changed during update")
            verify_directory()
            staged = os.stat(temporary, follow_symlinks=False)
            staged_identity = _fallback_identity(Path(temporary))
            _exchange_fallback(temporary, str(anchored_target))
            publication["mutated"] = True
            # The exchanged-out file, not the earlier check, proves what was replaced.
            # Preserve an unexpected file even if rollback cannot be completed.
            remove_temporary = False
            try:
                displaced = _fallback_identity(Path(temporary))
                if displaced != previous:
                    raise OSError("Fallback destination changed during exchange")
            except Exception:
                try:
                    now = os.stat(anchored_target, follow_symlinks=False)
                    if (now.st_dev, now.st_ino) == (staged.st_dev, staged.st_ino):
                        _exchange_fallback(temporary, str(anchored_target))
                        remove_temporary = _fallback_identity(Path(temporary)) == staged_identity
                finally:
                    if not remove_temporary:
                        _LOGGER.warning(
                            "Preserved displaced fallback for manual review: %s",
                            target.parent / Path(temporary).name,
                        )
                raise
            remove_temporary = True
        verify_directory()
    finally:
        try:
            if remove_temporary and os.path.lexists(temporary):
                os.unlink(temporary)
        finally:
            os.close(directory)


async def _async_sync_fallback(
    hass: HomeAssistant, source: Path, target: Path, generation: int | None = None
) -> None:
    ledger = hass.data.get(ARTIFACT_HASS_KEY)
    if ledger is None:
        ledger = hass.data[ARTIFACT_HASS_KEY] = ArtifactLedger(hass)

    async def sync() -> None:
        async with ledger.operation_lock:
            if generation is not None and generation != hass.data.get(_ARTIFACT_GENERATION, 0):
                return
            await ledger.async_load()
            snapshot = await asyncio.to_thread(_fallback_snapshot, source, target)
            if snapshot is None:
                return
            contents, previous = snapshot
            record = ledger.file
            path = str(target.absolute())
            digest = hashlib.sha256(contents).hexdigest()
            if previous is not None and previous[4] == digest:
                return
            if previous is not None and record is not None and record["path"] == path:
                # Ledger has a record for this path. If the hash doesn't match,
                # the file was modified externally — preserve it for manual review.
                if record["sha256"] != previous[4]:
                    _LOGGER.warning(
                        "Fallback card %s was modified externally; "
                        "preserving it for manual update", target,
                    )
                    return
            elif previous is not None:
                # No ledger record for this file (e.g., created by an older
                # integration version or manually). Adopt it from the source
                # bundle — the source is the integration's own built artifact.
                _LOGGER.info(
                    "Adopting unowned fallback card %s from source bundle", target,
                )
            directory = await asyncio.to_thread(_fallback_directory_identity, target)
            # If publication or the final ledger commit is interrupted, no file is adopted.
            await ledger.async_set_file(None)
            publication = {"mutated": False}
            try:
                await asyncio.to_thread(_publish_fallback, target, contents, previous, publication)
            except Exception:
                if previous is not None and record is not None and not publication["mutated"]:
                    try:
                        unchanged = await asyncio.to_thread(
                            _fallback_unchanged, target, previous, directory
                        )
                    except OSError:
                        unchanged = False
                    if unchanged:
                        await ledger.async_set_file(record)
                raise
            await ledger.async_set_file({"path": path, "sha256": digest})

    task = asyncio.create_task(sync())
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    task.result()
    if cancelled:
        raise asyncio.CancelledError


async def _register_static_path(hass: HomeAssistant, generation: int | None = None) -> None:
    """Register the frontend directory as a static path."""
    frontend_dir = str(Path(__file__).parent / "frontend")
    url_path = "/junie_remote"

    http = getattr(hass, "http", None)
    if http:
        if hasattr(http, "async_register_static_paths"):
            try:
                await http.async_register_static_paths([
                    StaticPathConfig(url_path, frontend_dir, cache_headers=True)
                ])
            except Exception as err:
                _LOGGER.debug("Could not async_register_static_paths: %s", err)
        elif hasattr(http, "register_static_path"):
            try:
                http.register_static_path(url_path, frontend_dir, cache_headers=True)
            except Exception as err:
                _LOGGER.debug("Could not register_static_path: %s", err)

    # Optional fallback sync to /config/www/junie-remote-card.js if www directory exists
    try:
        config = getattr(hass, "config", None)
        config_path = (
            config.path("www")
            if config and hasattr(config, "path")
            else "/config/www"
        )
        await _async_sync_fallback(
            hass, Path(frontend_dir) / "junie-remote-card.js",
            Path(config_path) / "junie-remote-card.js",
            generation,
        )
    except Exception as err:
        _LOGGER.warning("Could not safely sync fallback card; manual review required: %s", err)


async def _async_register_lovelace_resource(
    hass: HomeAssistant, generation: int | None = None
) -> None:
    """Register or update only a durably owned Lovelace resource."""
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        _LOGGER.warning("Lovelace not loaded; card resource requires manual review")
        return
    resources = getattr(lovelace, "resources", None)
    if getattr(lovelace, "resource_mode", getattr(lovelace, "mode", None)) == "yaml":
        _LOGGER.info("Lovelace resources are YAML-managed; configure the card resource manually")
        return
    if not all(callable(getattr(resources, name, None)) for name in (
        "async_items", "async_create_item", "async_update_item"
    )) or not hasattr(resources, "loaded"):
        _LOGGER.warning("Unsupported Lovelace resource collection; manual configuration required")
        return

    async def register() -> None:
        ledger = hass.data.get(ARTIFACT_HASS_KEY)
        if ledger is None:
            ledger = hass.data[ARTIFACT_HASS_KEY] = ArtifactLedger(hass)
        async with ledger.operation_lock:
            if generation is not None and generation != hass.data.get(_ARTIFACT_GENERATION, 0):
                return
            await ledger.async_load()
            # HA's resource loader treats corrupt storage and dashboard
            # errors as an empty collection. Check those inputs first.
            store = getattr(resources, "store", None)
            ll_config = getattr(resources, "ll_config", None)
            if store is not None:
                from homeassistant.components.lovelace.const import ConfigNotFound  # noqa: PLC0415

                await asyncio.to_thread(
                    read_store_envelope, store.path, store.key, store.version, RuntimeError
                )
                stored = await store.async_load()
                if stored is None:
                    if ll_config is None:
                        raise RuntimeError("Lovelace dashboard cannot be inspected")
                    try:
                        config = await ll_config.async_load(False)
                    except ConfigNotFound:
                        config = {}
                    if not isinstance(config, dict):
                        raise RuntimeError("Invalid Lovelace dashboard configuration")
                    if "resources" in config:
                        raise RuntimeError("Dashboard resources require manual review")
            if not resources.loaded:
                if not callable(getattr(resources, "async_load", None)):
                    raise RuntimeError("Lovelace resources cannot be loaded")
                await resources.async_load()
                resources.loaded = True
            items = list(resources.async_items())
            if not all(isinstance(item, dict) for item in items):
                raise RuntimeError("Invalid Lovelace resource collection")

            path = Path(__file__).parent / "frontend" / "junie-remote-card.js"
            digest = await asyncio.to_thread(lambda: hashlib.sha256(path.read_bytes()).hexdigest())
            card_path = "/junie_remote/junie-remote-card.js"
            url = f"{card_path}?v={digest}"
            record = ledger.resource
            if record is not None:
                matching = [item for item in items if item.get("id") == record["id"]]
                if len(matching) != 1 or any(
                    matching[0].get(key) != value for key, value in record.items()
                ):
                    _LOGGER.warning(
                        "Owned Lovelace resource is missing or modified; manual review required"
                    )
                    return
                if record["url"] == url and record["type"] == "module":
                    return

            def contains_card(candidate_items: list[dict[str, Any]]) -> bool:
                for item in candidate_items:
                    existing = item.get("url")
                    if not isinstance(existing, str):
                        raise RuntimeError("Invalid Lovelace resource URL")
                    parsed = urlsplit(existing)
                    if not parsed.scheme and not parsed.netloc and parsed.path in (
                        card_path, "/local/junie-remote-card.js"
                    ):
                        return True
                return False

            if record is None and contains_card(items):
                _LOGGER.warning(
                    "Existing card resource is not provably owned; manual review required"
                )
                return

            if HAS_HOMEASSISTANT:
                from homeassistant.components.lovelace.resources import (  # noqa: PLC0415
                    ResourceStorageCollection,
                )

                if (
                    type(resources) is not ResourceStorageCollection
                    or store is None
                    or store.key != "lovelace_resources"
                    or store.version != 1
                    or not callable(getattr(store, "async_save", None))
                ):
                    raise RuntimeError("Unsupported durable Lovelace resource storage")

            # Null ownership before mutation: an interrupted operation cannot be adopted.
            await ledger.async_set_resource(None)
            if (
                hass.data.get("lovelace") is not lovelace
                or lovelace.resources is not resources
                or getattr(lovelace, "resource_mode", getattr(lovelace, "mode", None)) == "yaml"
            ):
                raise RuntimeError("Lovelace resources changed during registration")
            if record is None:
                if contains_card(list(resources.async_items())):
                    raise RuntimeError("Card resource appeared during registration")
                item = await resources.async_create_item({"res_type": "module", "url": url})
            else:
                current = [
                    item for item in resources.async_items() if item.get("id") == record["id"]
                ]
                if len(current) != 1 or any(current[0].get(k) != v for k, v in record.items()):
                    raise RuntimeError("Lovelace resource changed during update")
                item = await resources.async_update_item(
                    record["id"], {"res_type": "module", "url": url}
                )
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not item["id"]
                or item.get("url") != url
                or item.get("type") != "module"
            ):
                raise RuntimeError("Lovelace returned an unexpected resource identity")
            expected = {"id": item["id"], "type": "module", "url": url}
            snapshot = {"items": deepcopy(list(resources.async_items()))}
            matching = [
                resource for resource in snapshot["items"] if resource.get("id") == item["id"]
            ]
            if len(matching) != 1 or any(matching[0].get(k) != v for k, v in expected.items()):
                raise RuntimeError("Lovelace resource changed during registration")
            if HAS_HOMEASSISTANT:
                # ResourceStorageCollection v1 persists its public dict items as
                # {"items": [...]}. HA's save can swallow errors or defer on stop,
                # so verify the actual file rather than trusting its return value.
                await store.async_save(snapshot)
                persisted = await asyncio.to_thread(
                    read_store_envelope, store.path, store.key, store.version, RuntimeError
                )
                if persisted != snapshot or list(resources.async_items()) != snapshot["items"]:
                    raise RuntimeError("Lovelace resource store could not be verified")
            if (
                hass.data.get("lovelace") is not lovelace
                or lovelace.resources is not resources
                or getattr(lovelace, "resource_mode", getattr(lovelace, "mode", None)) == "yaml"
            ):
                raise RuntimeError("Lovelace resource collection changed during registration")
            await ledger.async_set_resource(expected)

    async def finish() -> None:
        task = asyncio.create_task(register())
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    try:
        await finish()
    except Exception as err:
        _LOGGER.warning(
            "Could not safely register Lovelace resource; manual review required: %s", err
        )


def _warn_legacy_public_transcripts(config_www: Path) -> None:
    """Warn (never delete) when old public transcript copies may still exist."""
    legacy = config_www / "junie_remote"
    try:
        found = legacy.is_dir() and any(
            child.is_dir() and any(child.glob("*.json")) for child in legacy.iterdir()
        )
    except OSError:
        found = False
    if found:
        _LOGGER.warning(
            "Legacy public Junie transcripts remain in %s and are served without "
            "authentication at /local/junie_remote/. They were not deleted. Review and "
            "remove them manually and check your backups; new transcripts are stored "
            "privately.",
            legacy,
        )


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Junie Remote component and register Lovelace frontend resource."""
    generation = hass.data.get(_ARTIFACT_GENERATION, 0)
    await _register_static_path(hass, generation)
    async_register_transcript_view(hass)
    _async_register_services(hass)

    async def _register_lovelace(_event: Any = None) -> None:
        await _async_register_lovelace_resource(hass, generation)

    state = getattr(hass, "state", None)
    state_str = getattr(state, "value", str(state)) if state else ""
    if state_str.lower() in ("running", "corestate.running"):
        await _register_lovelace()
    elif hasattr(hass, "bus"):
        listen_fn = getattr(
            hass.bus, "async_listen_once", getattr(hass.bus, "async_listen", None)
        )
        if listen_fn is not None:
            try:
                listen_fn(EVENT_HOMEASSISTANT_STARTED, _register_lovelace)
            except Exception as err:
                _LOGGER.debug("Could not listen for Lovelace start in setup: %s", err)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up JetBrains Junie Remote from a config entry."""
    generation = hass.data.get(_ARTIFACT_GENERATION, 0)
    hass.data.setdefault(DOMAIN, {})
    previous: JunieRemoteCoordinator | None = hass.data[DOMAIN].get(entry.entry_id)
    if previous is not None:
        async with previous.unload_lock:
            if hass.data[DOMAIN].get(entry.entry_id) is previous:
                if not previous.platforms_unloaded:
                    if not await _async_unload_coordinator(hass, entry, previous):
                        raise RuntimeError("Cannot replace coordinator after failed unload")
                else:
                    await previous.async_shutdown()
                    await previous.client.close()
                    hass.data[DOMAIN].pop(entry.entry_id)

    # Register static path in case async_setup was not called
    await _register_static_path(hass, generation)

    # Register Lovelace resource immediately if running, or on startup
    async def _lovelace_started(_event: Any = None) -> None:
        await _async_register_lovelace_resource(hass, generation)

    state = getattr(hass, "state", None)
    state_str = getattr(state, "value", str(state)) if state else ""
    if state_str.lower() in ("running", "corestate.running"):
        await _lovelace_started()
    elif hasattr(hass, "bus"):
        listen_fn = getattr(
            hass.bus, "async_listen_once", getattr(hass.bus, "async_listen", None)
        )
        if listen_fn is not None:
            try:
                unsub = listen_fn(EVENT_HOMEASSISTANT_STARTED, _lovelace_started)
                if unsub:
                    entry.async_on_unload(unsub)
            except Exception as err:
                _LOGGER.debug("Could not listen for Lovelace start event: %s", err)

    auth_input = (
        entry.options.get("auth_input")
        or entry.data.get("auth_input")
        or entry.data.get(CONF_COOKIE_HEADER)
        or entry.data.get(CONF_STORAGE_STATE)
        or ""
    )
    base_url = (
        entry.options.get("base_url")
        or entry.data.get("base_url")
        or BASE_URL
    )

    client = JunieRemoteClient(auth_input=auth_input, base_url=base_url)

    storage_config = {**entry.data, **entry.options}
    if hasattr(hass, "config") and hasattr(hass.config, "path"):
        config_dir = Path(hass.config.path())
        config_www = Path(hass.config.path("www"))
    else:
        config_dir = Path("/config")
        config_www = config_dir / "www"
    default_local_dir = config_dir / "junie_remote" / "transcripts"
    inventory = hass.data.get(INVENTORY_HASS_KEY)
    if inventory is None:
        inventory = hass.data[INVENTORY_HASS_KEY] = TranscriptInventory(hass)
    storage = create_storage_driver(
        storage_config,
        default_local_dir=default_local_dir,
        entry_id=entry.entry_id,
        inventory=inventory,
        public_roots=known_public_roots(config_dir),
        config_dir=config_dir,
    )
    async_register_transcript_view(hass)
    await asyncio.to_thread(_warn_legacy_public_transcripts, config_www)

    coordinator = JunieRemoteCoordinator(hass, client, storage)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward entry setups to platforms
    existing_platforms = [
        p for p in PLATFORMS if (Path(__file__).parent / f"{p}.py").exists()
    ]
    platforms_to_forward = existing_platforms if existing_platforms else PLATFORMS
    if hasattr(hass, "config_entries") and hasattr(
        hass.config_entries, "async_forward_entry_setups"
    ):
        try:
            await hass.config_entries.async_forward_entry_setups(
                entry, platforms_to_forward
            )
        except Exception as err:
            _LOGGER.debug("Could not forward entry setups: %s", err)

    _async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a JetBrains Junie Remote config entry."""
    coordinator: JunieRemoteCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if coordinator is None:
        return True
    async with coordinator.unload_lock:
        if hass.data.get(DOMAIN, {}).get(entry.entry_id) is not coordinator:
            return True
        return await _async_unload_coordinator(hass, entry, coordinator)


async def _async_remove_owned_resource(
    hass: HomeAssistant, ledger: ArtifactLedger, no_entries: Callable[[], bool]
) -> None:
    record = ledger.resource
    if record is None:
        return
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if lovelace is None or getattr(
        lovelace, "resource_mode", getattr(lovelace, "mode", None)
    ) == "yaml":
        raise RuntimeError("Lovelace resources unavailable or YAML-managed")
    if not hasattr(resources, "loaded") or not all(
        callable(getattr(resources, name, None))
        for name in ("async_items", "async_load", "async_delete_item")
    ):
        raise RuntimeError("Unsupported Lovelace resource collection")
    store = getattr(resources, "store", None)
    if HAS_HOMEASSISTANT:
        from homeassistant.components.lovelace.resources import ResourceStorageCollection  # noqa: PLC0415

        if (type(resources) is not ResourceStorageCollection or store is None
            or store.key != "lovelace_resources" or store.version != 1
            or not callable(getattr(store, "async_save", None))):
            raise RuntimeError("Unsupported durable Lovelace resource storage")
        persisted = await asyncio.to_thread(
            read_store_envelope, store.path, store.key, store.version, RuntimeError
        )
        if persisted is None:
            raise RuntimeError("Lovelace resource store missing")
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True
    items = list(resources.async_items())
    if not all(isinstance(item, dict) for item in items):
        raise RuntimeError("Invalid Lovelace resource collection")
    matching = [item for item in items if item.get("id") == record["id"]]
    if len(matching) > 1 or (matching and matching[0] != record):
        raise RuntimeError("Owned Lovelace resource was modified")
    if (hass.data.get("lovelace") is not lovelace or lovelace.resources is not resources
        or getattr(lovelace, "resource_mode", getattr(lovelace, "mode", None)) == "yaml"):
        raise RuntimeError("Lovelace resources changed during removal")
    if not no_entries():
        raise RuntimeError("A configured entry now needs the card")
    if matching:
        await resources.async_delete_item(record["id"])
    snapshot = {"items": deepcopy(list(resources.async_items()))}
    if any(item.get("id") == record["id"] for item in snapshot["items"]):
        raise RuntimeError("Lovelace resource reappeared during removal")
    if HAS_HOMEASSISTANT:
        await store.async_save(snapshot)
        persisted = await asyncio.to_thread(
            read_store_envelope, store.path, store.key, store.version, RuntimeError
        )
        if persisted != snapshot or list(resources.async_items()) != snapshot["items"]:
            raise RuntimeError("Lovelace resource removal could not be verified")
    if (hass.data.get("lovelace") is not lovelace or lovelace.resources is not resources
        or getattr(lovelace, "resource_mode", getattr(lovelace, "mode", None)) == "yaml"):
        raise RuntimeError("Lovelace resources changed during removal")
    await ledger.async_set_resource(None)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove demonstrably owned artifacts only after the final permanent removal."""
    ledger = hass.data.get(ARTIFACT_HASS_KEY)
    if ledger is None:
        ledger = hass.data[ARTIFACT_HASS_KEY] = ArtifactLedger(hass)

    async def remove() -> None:
        async with ledger.operation_lock:
            entries = getattr(hass.config_entries, "async_entries", None)
            state = getattr(entry, "state", None)

            def no_entries() -> bool:
                return callable(entries) and not entries(DOMAIN) and not hass.data.get(DOMAIN)

            if (not no_entries()
                or getattr(state, "name", "") == "FAILED_UNLOAD"):
                _LOGGER.warning("Shared card artifacts retained: an entry may still need them")
                return
            hass.data[_ARTIFACT_GENERATION] = hass.data.get(_ARTIFACT_GENERATION, 0) + 1
            try:
                await ledger.async_load()
            except Exception as err:
                _LOGGER.warning("Artifact ownership unavailable; manual review required: %s", err)
                return
            try:
                await _async_remove_owned_resource(hass, ledger, no_entries)
            except Exception as err:
                _LOGGER.warning(
                    "Could not remove owned Lovelace resource; manual review required: %s", err
                )
            try:
                record = ledger.file
                target = Path(hass.config.path("www", "junie-remote-card.js")).absolute()
                if record is not None:
                    if not no_entries():
                        raise RuntimeError("A configured entry now needs the card")
                    if record["path"] != str(target):
                        raise RuntimeError("Fallback path does not match configured www")
                    # Invalidate first: after a crash a same-content replacement is not ours.
                    await ledger.async_set_file(None)
                    if not no_entries():
                        await ledger.async_set_file(record)
                        raise RuntimeError("A configured entry now needs the card")
                    error, _, was_quarantined = await asyncio.to_thread(
                        _delete_owned_local_file, record["path"], record["sha256"]
                    )
                    if error:
                        if not was_quarantined:
                            await ledger.async_set_file(record)
                        raise RuntimeError(error)
            except Exception as err:
                _LOGGER.warning(
                    "Could not remove owned fallback card; manual review required: %s", err
                )

    task = asyncio.create_task(remove())
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


async def _async_unload_coordinator(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: JunieRemoteCoordinator
) -> bool:
    """Unload platforms before shutting down the entry's coordinator."""
    existing_platforms = [
        p for p in PLATFORMS if (Path(__file__).parent / f"{p}.py").exists()
    ]
    platforms_to_unload = existing_platforms if existing_platforms else PLATFORMS

    if not coordinator.platforms_unloaded and hasattr(hass, "config_entries") and hasattr(
        hass.config_entries, "async_unload_platforms"
    ):
        try:
            unloaded = await hass.config_entries.async_unload_platforms(
                entry, platforms_to_unload
            )
        except Exception as err:
            _LOGGER.exception("Could not unload platforms for entry %s: %s", entry.entry_id, err)
            return False
        if not unloaded:
            _LOGGER.warning("Could not unload platforms for entry %s", entry.entry_id)
            return False
    coordinator.platforms_unloaded = True

    try:
        await coordinator.async_shutdown()
        await coordinator.client.close()
    except asyncio.CancelledError:
        if asyncio.current_task().cancelling():
            raise
        _LOGGER.error("Coordinator shutdown was cancelled for entry %s", entry.entry_id)
        return False
    except Exception:
        _LOGGER.exception("Could not shut down entry %s", entry.entry_id)
        return False

    hass.data[DOMAIN].pop(entry.entry_id, None)

    if not hass.data.get(DOMAIN):
        _async_unregister_services(hass)

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)
