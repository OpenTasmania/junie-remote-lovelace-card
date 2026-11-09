# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Async REST and PKCE S256 WebSocket client for JetBrains Junie Remote."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import json
import logging
import secrets
import urllib.parse
import uuid
from typing import Any, Callable

import aiohttp

from .const import API_BASE_PATH, BASE_URL
from .models import (
    ChatSessionState,
    JunieAuthError,
    JunieRemoteError,
    TunnelConflictError,
    TunnelInfo,
    TunnelNotFoundError,
)

_LOGGER = logging.getLogger(__name__)


def parse_auth_cookies(auth_input: str) -> tuple[dict[str, str], str | None]:
    """Parse storageState JSON or Cookie header into cookies dict and XSRF token."""
    raw = auth_input.strip()
    cookies: dict[str, str] = {}
    if not raw:
        return cookies, None

    if raw.startswith("{") and raw.endswith("}"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "cookies" in data:
                cookie_list = data["cookies"]
                if isinstance(cookie_list, list):
                    for item in cookie_list:
                        if isinstance(item, dict) and "name" in item and "value" in item:
                            cookies[str(item["name"])] = str(item["value"])
        except json.JSONDecodeError:
            pass

    if not cookies:
        for item in raw.split(";"):
            item = item.strip()
            if not item or "=" not in item:
                continue
            name, value = item.split("=", 1)
            cookies[name.strip()] = value.strip()

    xsrf_cookie = cookies.get("XSRF-TOKEN")
    xsrf_token_decoded = urllib.parse.unquote(xsrf_cookie) if xsrf_cookie else None
    return cookies, xsrf_token_decoded


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE S256 code_verifier and code_challenge."""
    verifier_bytes = secrets.token_bytes(32)
    code_verifier = base64.urlsafe_b64encode(verifier_bytes).decode("ascii").rstrip("=")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


def build_ws_url(ws_url: str, code_verifier: str) -> str:
    """Rewrite wsUrl scheme to wss:// / ws:// and append code_verifier query parameter."""
    if ws_url.startswith("https://"):
        url = "wss://" + ws_url[8:]
    elif ws_url.startswith("http://"):
        url = "ws://" + ws_url[7:]
    else:
        url = ws_url
    delimiter = "&" if "?" in url else "?"
    return f"{url}{delimiter}code_verifier={code_verifier}"


class JunieRemoteClient:
    """Async client communicating with the JetBrains Junie Remote REST API."""

    def __init__(
        self,
        auth_input: str | None = None,
        cookies: dict[str, str] | None = None,
        xsrf_token: str | None = None,
        session: aiohttp.ClientSession | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        """Initialize JunieRemoteClient."""
        self.base_url = base_url.rstrip("/")
        self._session = session
        self._own_session = session is None
        self.cookies: dict[str, str] = dict(cookies or {})
        self.xsrf_token: str | None = xsrf_token
        if auth_input:
            self.set_auth(auth_input)

    def set_auth(self, auth_input: str) -> None:
        """Set authentication cookies from storageState JSON or Cookie header."""
        cookies, xsrf = parse_auth_cookies(auth_input)
        self.cookies = cookies
        self.xsrf_token = xsrf

    @property
    def session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp ClientSession."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self._session

    async def close(self) -> None:
        """Close the underlying ClientSession if owned."""
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> JunieRemoteClient:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    def _get_headers(self) -> dict[str, str]:
        """Construct request headers including Cookie and X-XSRF-TOKEN."""
        headers: dict[str, str] = {}
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        if self.xsrf_token:
            headers["X-XSRF-TOKEN"] = self.xsrf_token
        return headers

    def _format_url(self, path: str) -> str:
        """Format a full URL from a relative API path."""
        if path.startswith("/api/public"):
            return f"{self.base_url}{path}"
        if path.startswith("/"):
            return f"{self.base_url}{API_BASE_PATH}{path}"
        return f"{self.base_url}{API_BASE_PATH}/{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an HTTP request with authentication headers and error mapping."""
        url = self._format_url(path)
        headers = self._get_headers()
        if json_data is not None:
            headers["Content-Type"] = "application/json"

        async with self.session.request(
            method,
            url,
            headers=headers,
            json=json_data,
            params=params,
        ) as resp:
            status = resp.status
            if status >= 400:
                error_msg = ""
                try:
                    data = await resp.json()
                    if isinstance(data, dict):
                        error_msg = data.get("message") or data.get("error") or str(data)
                except Exception:
                    error_msg = await resp.text()

                if not error_msg:
                    error_msg = resp.reason or f"HTTP {status}"

                if status == 401:
                    raise JunieAuthError(f"Authentication failed (HTTP 401): {error_msg}")
                if status == 404:
                    raise TunnelNotFoundError(f"Tunnel not found (HTTP 404): {error_msg}")
                if status == 409:
                    raise TunnelConflictError(f"Tunnel conflict (HTTP 409): {error_msg}")
                raise JunieRemoteError(f"HTTP {status} error: {error_msg}")

            if resp.content_type == "application/json":
                return await resp.json()
            text = await resp.text()
            if not text:
                return None
            try:
                return json.loads(text)
            except Exception:
                return text

    async def list_tunnels(self) -> list[TunnelInfo]:
        """Fetch all active remote tunnels."""
        data = await self._request("GET", "/cli/tunnel/tunnels")
        if isinstance(data, list):
            return [TunnelInfo.from_dict(item) for item in data]
        return []

    async def get_tunnel(self, tunnel_id: str) -> TunnelInfo:
        """Fetch metadata for a single remote tunnel."""
        data = await self._request("GET", f"/cli/tunnel/tunnels/{tunnel_id}")
        return TunnelInfo.from_dict(data)

    async def connect_tunnel(
        self,
        tunnel_id: str,
        code_challenge: str,
        code_challenge_method: str = "S256",
    ) -> str:
        """Request connection to a tunnel using PKCE S256 code challenge, returning wsUrl."""
        data = await self._request(
            "POST",
            f"/cli/tunnel/tunnels/{tunnel_id}/client/connect",
            json_data={
                "codeChallenge": code_challenge,
                "codeChallengeMethod": code_challenge_method,
            },
        )
        if isinstance(data, dict) and "wsUrl" in data:
            return str(data["wsUrl"])
        raise JunieRemoteError(f"Unexpected response from connect_tunnel: {data}")

    async def kick_client(self, tunnel_id: str) -> None:
        """Kick the currently connected client on a remote tunnel."""
        await self._request("POST", f"/cli/tunnel/tunnels/{tunnel_id}/kick-client", json_data={})

    async def create_token(self, name: str) -> dict[str, Any]:
        """Create a new Junie CLI authentication token."""
        return await self._request("POST", "/cli/tokens", json_data={"name": name})

    async def delete_token(self, token_id: str) -> None:
        """Delete an existing Junie CLI authentication token."""
        await self._request("DELETE", f"/cli/tokens/{token_id}")


class JunieTunnelSession:
    """Manages the WebSocket connection and state reducer for a remote tunnel."""

    def __init__(
        self,
        client: JunieRemoteClient,
        tunnel_id: str,
        handshake_timeout: float = 20.0,
        on_status_change: Callable[[str, Exception | None], Any] | None = None,
        on_event: Callable[[dict[str, Any], ChatSessionState], Any] | None = None,
    ) -> None:
        """Initialize JunieTunnelSession."""
        self.client = client
        self.tunnel_id = tunnel_id
        self.handshake_timeout = handshake_timeout
        self.on_status_change = on_status_change
        self.on_event = on_event
        self.state = ChatSessionState()
        self.connection_status: str = "disconnected"
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self._listen_task: asyncio.Task[None] | None = None

    def _set_status(self, status: str, error: Exception | None = None) -> None:
        """Update connection status and notify callback."""
        self.connection_status = status
        if self.on_status_change:
            try:
                res = self.on_status_change(status, error)
                if inspect.isawaitable(res):
                    asyncio.create_task(res)
            except Exception:
                _LOGGER.exception("Error in on_status_change callback")

    def _notify_event(self, event: dict[str, Any]) -> None:
        """Notify event callback of incoming frame."""
        if self.on_event:
            try:
                res = self.on_event(event, self.state)
                if inspect.isawaitable(res):
                    asyncio.create_task(res)
            except Exception:
                _LOGGER.exception("Error in on_event callback")

    async def connect(self) -> None:
        """Establish WebSocket connection using PKCE S256 and perform handshake."""
        if self.ws and not self.ws.closed:
            await self.dispose()

        self._set_status("connecting", None)
        ws: aiohttp.ClientWebSocketResponse | None = None
        try:
            code_verifier, code_challenge = generate_pkce_pair()
            raw_ws_url = await self.client.connect_tunnel(self.tunnel_id, code_challenge)
            ws_url = build_ws_url(raw_ws_url, code_verifier)

            ws = await self.client.session.ws_connect(
                ws_url,
                headers=self.client._get_headers(),
            )

            # Send immediate client-connected frame
            req_id = str(uuid.uuid4())
            await ws.send_json({"type": "client-connected", "requestId": req_id})

            # Handshake: wait for agent-ready
            async def _wait_for_agent_ready() -> dict[str, Any]:
                assert ws is not None
                while not ws.closed:
                    msg = await ws.receive()
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("type") == "agent-ready":
                            return data
                        self.state.apply_event(data)
                        self._notify_event(data)
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        close_reason = str(getattr(msg, "extra", "") or "")
                        if "client-kicked" in close_reason:
                            self._set_status("kicked", None)
                        raise JunieRemoteError(
                            f"WebSocket closed during handshake ({msg.type}): {close_reason}"
                        )
                raise JunieRemoteError("WebSocket closed before agent-ready received")

            await asyncio.wait_for(_wait_for_agent_ready(), timeout=self.handshake_timeout)

            self.ws = ws
            self._set_status("connected", None)
            self._listen_task = asyncio.create_task(self._listen_loop())

        except asyncio.TimeoutError as err:
            if ws is not None and not ws.closed:
                await ws.close(code=4000, message=b"handshake-timeout")
            self._set_status("failed", err)
            raise JunieRemoteError("Handshake timed out waiting for agent-ready") from err
        except Exception as err:
            if ws is not None and not ws.closed:
                await ws.close()
            if self.connection_status != "kicked":
                self._set_status("failed", err)
            raise

    async def _listen_loop(self) -> None:
        """Listen for incoming WebSocket frames and dispatch to state reducer."""
        assert self.ws is not None
        ws = self.ws
        close_reason = ""
        try:
            while not ws.closed:
                msg = await ws.receive()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        event = json.loads(msg.data)
                    except Exception:
                        _LOGGER.warning("Received invalid JSON over WebSocket: %s", msg.data)
                        continue
                    self.state.apply_event(event)
                    self._notify_event(event)
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    close_reason = str(getattr(msg, "extra", "") or "")
                    break
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.exception("Unexpected error in WebSocket listen loop")
            if self.connection_status != "disconnected":
                self._set_status("failed", err)
            return
        finally:
            if not close_reason and ws:
                raw_reason = getattr(ws, "close_reason", None)
                if raw_reason:
                    close_reason = str(raw_reason)
                elif hasattr(ws, "exception") and ws.exception():
                    close_reason = str(ws.exception())

            if "client-kicked" in close_reason:
                self._set_status("kicked", None)
            elif self.connection_status not in ("disconnected", "kicked", "failed"):
                self._set_status("disconnected", None)

    async def kick_and_retry(self, wait_delay: float = 0.5) -> None:
        """Kick the active connected client and re-attempt connection."""
        await self.client.kick_client(self.tunnel_id)
        if wait_delay > 0:
            await asyncio.sleep(wait_delay)
        await self.connect()

    async def dispose(self) -> None:
        """Close WebSocket connection and stop background tasks."""
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None
        if self.ws and not self.ws.closed:
            await self.ws.close(code=1000)
            self.ws = None
        self._set_status("disconnected", None)

    async def _send(self, payload: dict[str, Any]) -> None:
        """Send a JSON payload over the connected WebSocket."""
        if not self.ws or self.ws.closed:
            raise JunieRemoteError("Cannot send message: WebSocket is not connected")
        await self.ws.send_json(payload)

    async def send_prompt(self, prompt: str) -> None:
        """Send a prompt or steer message."""
        await self._send({"type": "prompt", "prompt": prompt})

    async def send_plan_prompt(self, prompt: str) -> None:
        """Send a plan refinement prompt."""
        await self._send({"type": "planPrompt", "prompt": prompt})

    async def confirm_plan(self) -> None:
        """Confirm and implement the proposed plan."""
        await self._send({"type": "confirmAndImplementPlan"})

    async def cancel(self) -> None:
        """Cancel the current task."""
        await self._send({"type": "cancel"})

    async def toggle_brave_mode(self, enabled: bool) -> None:
        """Toggle brave mode."""
        await self._send({"type": "toggleBraveMode", "enabled": enabled})

    async def select_model(self, model_id: str, effort_id: str | None = None) -> None:
        """Select active model and optional effort level."""
        payload: dict[str, Any] = {"type": "selectModel", "modelId": model_id}
        if effort_id is not None:
            payload["effortId"] = effort_id
        await self._send(payload)

    async def send_response(self, display_text: str, response_payload: dict[str, Any]) -> None:
        """Send a response to an interactive request."""
        await self._send({
            "type": "response",
            "displayText": display_text,
            "response": response_payload,
        })
