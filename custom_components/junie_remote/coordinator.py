# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Coordinator for JetBrains Junie Remote host auto-discovery and session streaming."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Coroutine, TypeVar

from .client import JunieRemoteClient, JunieTunnelSession
from .const import DEFAULT_POLL_INTERVAL
from .ha_compat import DataUpdateCoordinator, HomeAssistant
from .models import ChatSessionState, JunieRemoteError, TunnelInfo
from .storage import (
    TranscriptDocument,
    TranscriptResult,
    TranscriptStorageDriver,
    TranscriptStorageError,
)

_LOGGER = logging.getLogger(__name__)
_T = TypeVar("_T")


@dataclass
class HostBridgeState:
    """State bridge for a discovered remote host running Junie CLI."""

    host_key: str
    tunnel: TunnelInfo
    session: JunieTunnelSession | None = None
    chat_state: ChatSessionState = field(default_factory=ChatSessionState)
    connection_status: str = "disconnected"
    last_error: str | None = None
    transcript_result: TranscriptResult | None = None
    auto_connect: bool = True

    @property
    def device_name(self) -> str:
        """Human-friendly device name for Home Assistant device registry."""
        user = self.tunnel.metadata.user_name or "Junie"
        os_name = self.tunnel.metadata.os_name or ""
        repo = (
            self.tunnel.metadata.git_repo_url
            or self.tunnel.metadata.current_directory
            or ""
        )
        base = f"{user}@{os_name}" if os_name else user
        if repo:
            repo_name = repo.rstrip("/").split("/")[-1]
            return f"{base} ({repo_name})"
        return base

    def to_dict(self) -> dict[str, Any]:
        """Convert host bridge state to serializable dictionary."""
        return {
            "host_key": self.host_key,
            "tunnel_id": self.tunnel.tunnel_id,
            "device_name": self.device_name,
            "connection_status": self.connection_status,
            "last_error": self.last_error,
            "chat_state": self.chat_state.to_dict(),
            "transcript_json_url": (
                self.transcript_result.json_url if self.transcript_result else None
            ),
            "transcript_md_url": (
                self.transcript_result.md_url if self.transcript_result else None
            ),
            "last_step_preview": (
                self.transcript_result.last_step_preview
                if self.transcript_result
                else None
            ),
        }


class JunieRemoteCoordinator(DataUpdateCoordinator[dict[str, HostBridgeState]]):
    """DataUpdateCoordinator for JetBrains Junie Remote."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: JunieRemoteClient,
        storage: TranscriptStorageDriver,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        auto_connect: bool = True,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Junie Remote Coordinator",
            update_interval=timedelta(seconds=poll_interval),
        )
        self.client = client
        self.storage = storage
        self.hosts: dict[str, HostBridgeState] = {}
        self.auto_connect = auto_connect
        self._transcript_save_locks: dict[str, asyncio.Lock] = {}
        self._closing = False
        self._save_tasks: set[asyncio.Task[None]] = set()
        self._save_work_tasks: set[asyncio.Task[None]] = set()
        self._producer_tasks: set[asyncio.Task[Any]] = set()
        self._shutdown_task: asyncio.Task[None] | None = None
        self.unload_lock = asyncio.Lock()
        self.platforms_unloaded = False

    def _track_task(
        self, coro: Coroutine[Any, Any, _T], tasks: set[asyncio.Task[Any]], label: str,
        *, use_hass: bool = True,
    ) -> asyncio.Task[_T]:
        create_task = (
            getattr(self.hass, "async_create_task", asyncio.create_task)
            if use_hass else asyncio.create_task
        )
        task = create_task(coro)
        tasks.add(task)

        def finished(done: asyncio.Task[Any]) -> None:
            tasks.discard(done)
            if not done.cancelled() and (error := done.exception()) is not None:
                _LOGGER.error(
                    "%s failed", label, exc_info=(type(error), error, error.__traceback__)
                )

        task.add_done_callback(finished)
        return task

    def async_set_updated_data(self, data: dict[str, HostBridgeState]) -> None:
        """Avoid notifications and new polling after shutdown starts."""
        if not self._closing:
            super().async_set_updated_data(data)

    def async_set_update_error(self, err: Exception) -> None:
        if not self._closing:
            super().async_set_update_error(err)

    def async_update_listeners(self) -> None:
        if not self._closing:
            super().async_update_listeners()

    def _schedule_refresh(self) -> None:
        if not self._closing:
            super()._schedule_refresh()

    async def _async_update_data(self) -> dict[str, HostBridgeState]:
        """Fetch remote tunnels and reconcile dynamic host bindings."""
        if self._closing:
            return self.hosts
        task = self._track_task(self._async_reconcile(), self._producer_tasks, "Tunnel refresh")
        return await asyncio.shield(task)

    async def _async_reconcile(self) -> dict[str, HostBridgeState]:
        try:
            tunnels = await self.client.list_tunnels()
        except Exception as err:
            _LOGGER.error("Failed to list Junie remote tunnels: %s", err)
            raise JunieRemoteError(f"Failed to list remote tunnels: {err}") from err

        if self._closing:
            return self.hosts
        active_host_keys: set[str] = set()

        for tunnel in tunnels:
            host_key = tunnel.compute_host_key()
            active_host_keys.add(host_key)

            if host_key in self.hosts:
                state = self.hosts[host_key]
                # Dynamic Tunnel Rebinding: check if tunnelId changed
                if state.tunnel.tunnel_id != tunnel.tunnel_id:
                    _LOGGER.info(
                        "Host '%s' tunnelId changed: %s -> %s (CLI restarted)",
                        host_key,
                        state.tunnel.tunnel_id,
                        tunnel.tunnel_id,
                    )
                    had_active_session = (
                        state.session is not None
                        or state.connection_status in ("connected", "connecting")
                    )
                    if state.session:
                        await state.session.dispose()
                        state.session = None
                    state.tunnel = tunnel
                    state.connection_status = "disconnected"
                    state.last_error = None
                    if (self.auto_connect and state.auto_connect) or had_active_session:
                        await self._async_connect_host(host_key)
                else:
                    state.tunnel = tunnel
                    if (
                        self.auto_connect
                        and state.auto_connect
                        and (
                            state.session is None
                            or state.connection_status in ("disconnected", "failed")
                        )
                        and (tunnel.connected_clients == 0 or state.session is None)
                    ):
                        await self._async_connect_host(host_key)
            else:
                # Newly discovered host
                state = HostBridgeState(
                    host_key=host_key,
                    tunnel=tunnel,
                    chat_state=ChatSessionState(),
                    connection_status="disconnected",
                    auto_connect=self.auto_connect,
                )
                self.hosts[host_key] = state
                if self.auto_connect and state.auto_connect:
                    await self._async_connect_host(host_key)

        # Mark offline hosts no longer returned by the gateway
        for h_key, state in list(self.hosts.items()):
            if h_key not in active_host_keys:
                if state.session:
                    await state.session.dispose()
                    state.session = None
                state.connection_status = "offline"

        return self.hosts

    async def _async_connect_host(self, host_key: str, kick: bool = False) -> None:
        """Establish or retry WebSocket connection for a given host."""
        if self._closing:
            return
        task = self._track_task(
            self._async_connect_host_inner(host_key, kick),
            self._producer_tasks,
            "Tunnel connection",
        )
        await asyncio.shield(task)

    async def _async_connect_host_inner(self, host_key: str, kick: bool) -> None:
        state = self.hosts.get(host_key)
        if not state:
            return

        if not kick and state.session and state.connection_status in ("connected", "connecting"):
            return

        if state.session:
            await state.session.dispose()
            state.session = None

        if self._closing:
            return
        session = JunieTunnelSession(
            client=self.client,
            tunnel_id=state.tunnel.tunnel_id,
            on_status_change=lambda status, err: self._on_session_status_change(
                host_key, status, err
            ),
            on_event=lambda event, chat_state: self._on_session_event(
                host_key, event, chat_state
            ),
        )
        state.session = session
        state.connection_status = "connecting"

        try:
            if kick:
                await session.kick_and_retry()
            else:
                await session.connect()
        except Exception as err:
            _LOGGER.warning(
                "Connection to tunnel %s for host %s failed: %s",
                state.tunnel.tunnel_id,
                host_key,
                err,
            )
            state.connection_status = "failed"
            state.last_error = str(err)

    def _on_session_status_change(
        self, host_key: str, status: str, err: Exception | None
    ) -> None:
        """Handle session connection status transition."""
        if self._closing:
            return
        state = self.hosts.get(host_key)
        if not state:
            return

        state.connection_status = status
        if err:
            state.last_error = str(err)
        elif status == "connected":
            state.last_error = None

        self._schedule_save_and_notify(host_key)

    def _on_session_event(
        self,
        host_key: str,
        event: dict[str, Any],
        chat_state: ChatSessionState,
    ) -> None:
        """Handle incoming event from session."""
        if self._closing:
            return
        state = self.hosts.get(host_key)
        if not state:
            return

        state.chat_state = chat_state
        self._schedule_save_and_notify(host_key)

    def _schedule_save_and_notify(self, host_key: str) -> None:
        """Schedule transcript save and coordinator listener dispatch."""
        if not self._closing:
            work = self._track_task(
                self._async_save_and_notify(host_key), self._save_work_tasks,
                "Transcript save", use_hass=False,
            )
            self._track_task(
                self._async_wait_for_save(work), self._save_tasks, "Transcript save waiter"
            )

    async def _async_wait_for_save(self, work: asyncio.Task[None]) -> None:
        """Keep the HA-tracked waiter alive until the accepted save finishes."""
        cancelled = False
        while True:
            try:
                await asyncio.shield(work)
                break
            except asyncio.CancelledError:
                if work.cancelled():
                    raise
                cancelled = True
            except Exception:
                # The tracked work task logs its own error.
                break
        if cancelled:
            raise asyncio.CancelledError

    async def _async_save_and_notify(self, host_key: str) -> None:
        """Persist current state document and notify listeners."""
        if host_key not in self.hosts:
            return

        lock = self._transcript_save_locks.setdefault(host_key, asyncio.Lock())
        async with lock:
            state = self.hosts.get(host_key)
            if not state:
                return

            doc = TranscriptDocument.build(
                host_key=host_key,
                tunnel=state.tunnel,
                chat_state=state.chat_state,
                connection_status=state.connection_status,
            )

            # Keep the host lock until thread-backed storage actually finishes,
            # even if the tracked save task is cancelled more than once.
            write = asyncio.create_task(self.storage.async_save_transcript(doc))
            cancelled = False
            while True:
                try:
                    res = await asyncio.shield(write)
                    state.transcript_result = res
                    break
                except asyncio.CancelledError:
                    if write.cancelled():
                        raise
                    cancelled = True
                except TranscriptStorageError as err:
                    if "paused" in str(err).lower():
                        _LOGGER.debug(
                            "Transcript save skipped; writes paused for host %s",
                            host_key,
                        )
                    else:
                        _LOGGER.exception(
                            "Failed to save transcript for host %s", host_key
                        )
                    break
                except Exception:
                    _LOGGER.exception("Failed to save transcript for host %s", host_key)
                    break

            if cancelled:
                raise asyncio.CancelledError

            self.async_set_updated_data(self.hosts)

    def _get_connected_session(self, host_key: str) -> JunieTunnelSession:
        """Retrieve connected session for host or raise JunieRemoteError."""
        if self._closing:
            raise JunieRemoteError("Coordinator is shutting down")
        if host_key not in self.hosts:
            raise JunieRemoteError(f"Host '{host_key}' not found")
        state = self.hosts[host_key]
        if not state.session or state.connection_status != "connected":
            raise JunieRemoteError(
                f"Host '{host_key}' is not connected (status: {state.connection_status})"
            )
        return state.session

    async def async_send_prompt(self, host_key: str, prompt: str) -> None:
        """Send a task prompt or steer message to the remote host."""
        session = self._get_connected_session(host_key)
        await session.send_prompt(prompt)

    async def async_send_plan_prompt(self, host_key: str, prompt: str) -> None:
        """Send a plan refinement prompt to the remote host."""
        session = self._get_connected_session(host_key)
        await session.send_plan_prompt(prompt)

    async def async_confirm_plan(self, host_key: str) -> None:
        """Confirm and implement the proposed plan on the remote host."""
        session = self._get_connected_session(host_key)
        await session.confirm_plan()

    async def async_cancel(self, host_key: str) -> None:
        """Cancel current active task on the remote host."""
        session = self._get_connected_session(host_key)
        await session.cancel()

    async def async_toggle_brave_mode(self, host_key: str, enabled: bool) -> None:
        """Toggle brave mode on the remote host."""
        session = self._get_connected_session(host_key)
        await session.toggle_brave_mode(enabled)

    async def async_select_model(
        self, host_key: str, model_id: str, effort_id: str | None = None
    ) -> None:
        """Select active LLM model and optional effort level."""
        session = self._get_connected_session(host_key)
        await session.select_model(model_id, effort_id)

    async def async_respond_request(
        self,
        host_key: str,
        display_text: str,
        response_payload: dict[str, Any],
    ) -> None:
        """Send response to an interactive request."""
        session = self._get_connected_session(host_key)
        await session.send_response(display_text, response_payload)

    async def async_kick_and_takeover(self, host_key: str) -> None:
        """Kick conflicting client and establish session connection."""
        if self._closing:
            raise JunieRemoteError("Coordinator is shutting down")
        if host_key not in self.hosts:
            raise JunieRemoteError(f"Host '{host_key}' not found")
        await self._async_connect_host(host_key, kick=True)

    async def async_drain_saves(self) -> None:
        """Wait for any in-flight transcript saves to finish."""
        while self._save_tasks or self._save_work_tasks:
            tracked_tasks = self._save_tasks | self._save_work_tasks
            done = {task for task in tracked_tasks if task.done()}
            self._save_tasks.difference_update(done)
            self._save_work_tasks.difference_update(done)
            pending = self._save_tasks | self._save_work_tasks
            if pending:
                await asyncio.wait(set(pending))

    async def async_shutdown(self) -> None:
        """Stop producers and drain accepted work, even if a caller is cancelled."""
        self._closing = True
        if self._shutdown_task is None or (
            self._shutdown_task.done()
            and (self._shutdown_task.cancelled() or self._shutdown_task.exception() is not None)
        ):
            self._shutdown_task = asyncio.create_task(self._async_shutdown_inner())
            self._shutdown_task.add_done_callback(self._observe_shutdown)
        await asyncio.shield(self._shutdown_task)

    @staticmethod
    def _observe_shutdown(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            _LOGGER.error(
                "Coordinator shutdown failed",
                exc_info=(type(error), error, error.__traceback__),
            )

    async def _async_shutdown_inner(self) -> None:
        await super().async_shutdown()
        # A cancelled drain must not cancel work that a retry must still await.
        while self._producer_tasks:
            done = {task for task in self._producer_tasks if task.done()}
            self._producer_tasks.difference_update(done)
            if self._producer_tasks:
                await asyncio.wait(set(self._producer_tasks))
        errors: list[Exception] = []
        for state in list(self.hosts.values()):
            if state.session:
                try:
                    await state.session.dispose()
                except Exception as err:
                    errors.append(err)
                    _LOGGER.exception("Failed to dispose session for host %s", state.host_key)
                else:
                    state.session = None
        while self._save_tasks or self._save_work_tasks:
            tracked_tasks = self._save_tasks | self._save_work_tasks
            done = {task for task in tracked_tasks if task.done()}
            self._save_tasks.difference_update(done)
            self._save_work_tasks.difference_update(done)
            pending = self._save_tasks | self._save_work_tasks
            if pending:
                await asyncio.wait(set(pending))
        if errors:
            raise errors[0]
