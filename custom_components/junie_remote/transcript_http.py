# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Authenticated, admin-only delivery of private local transcripts.

The view is the only way local transcripts are served. Requests must be
authenticated by Home Assistant (bearer token or ``auth/sign_path`` signature),
come from an administrator, and satisfy HA's local-only/network restriction for
that user. Signed links carry the signing user's identity, so the administrator
check is made on every request rather than at signing time. Authorization
failures answer 403 (never 401, which HA's ban middleware would log with the
full signature).
"""

from __future__ import annotations

import logging
from typing import Any

from .const import DOMAIN
from .coordinator import JunieRemoteCoordinator
from .storage import (
    LocalTranscriptStorage,
    TranscriptNotFoundError,
    TranscriptStorageError,
    safe_component,
)
from .transcript_inventory import TranscriptInventoryError

_LOGGER = logging.getLogger(__name__)

VIEW_REGISTERED_KEY = "junie_remote_transcript_view_registered"

_CONTENT_TYPES = {
    "json": "application/json",
    "md": "text/markdown",
}


def async_register_transcript_view(hass: Any) -> bool:
    """Register the production view once; returns False without a real HA HTTP stack."""
    if hass.data.get(VIEW_REGISTERED_KEY):
        return True
    http = getattr(hass, "http", None)
    if http is None or not hasattr(http, "register_view"):
        return False
    try:
        view_cls = _build_view_class()
    except ImportError:
        return False
    http.register_view(view_cls(hass))
    hass.data[VIEW_REGISTERED_KEY] = True
    return True


def _build_view_class() -> type:
    from aiohttp import web
    from homeassistant.components.http import HomeAssistantView
    from homeassistant.components.http.auth import async_user_not_allowed_do_auth
    from homeassistant.components.http.const import KEY_HASS_USER

    class JunieRemoteTranscriptView(HomeAssistantView):  # type: ignore[misc]
        """Serve one entry's latest JSON/Markdown transcript to administrators."""

        url = "/api/junie_remote/transcripts/{entry_id}/{host_key}/{file_format}"
        name = "api:junie_remote:transcripts"
        requires_auth = True

        def __init__(self, hass: Any) -> None:
            self.hass = hass

        async def get(
            self, request: Any, entry_id: str, host_key: str, file_format: str
        ) -> Any:
            user = request.get(KEY_HASS_USER)
            if (
                user is None
                or not user.is_admin
                or async_user_not_allowed_do_auth(self.hass, user, request)
            ):
                raise web.HTTPForbidden()

            if file_format not in _CONTENT_TYPES:
                raise web.HTTPNotFound()
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.domain != DOMAIN:
                raise web.HTTPNotFound()
            coordinator = self.hass.data.get(DOMAIN, {}).get(entry_id)
            if not isinstance(coordinator, JunieRemoteCoordinator) or not isinstance(
                coordinator.storage, LocalTranscriptStorage
            ):
                raise web.HTTPNotFound()

            try:
                data = await coordinator.storage.async_read_transcript(
                    host_key, file_format
                )
            except TranscriptNotFoundError:
                raise web.HTTPNotFound() from None
            except (TranscriptStorageError, TranscriptInventoryError):
                _LOGGER.warning("Local transcript is unavailable for entry %s", entry_id)
                raise web.HTTPNotFound() from None

            headers = {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
            }
            if request.query.get("download") == "1":
                ext = "json" if file_format == "json" else "md"
                headers["Content-Disposition"] = (
                    f'attachment; filename="junie-{safe_component(host_key)}.{ext}"'
                )
            return web.Response(
                body=data,
                content_type=_CONTENT_TYPES[file_format],
                charset="utf-8",
                headers=headers,
            )

    return JunieRemoteTranscriptView
