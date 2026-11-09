# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Unit tests for JetBrains Junie Remote models and async REST/WS client."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import urllib.parse
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.junie_remote.client import (
    JunieRemoteClient,
    JunieTunnelSession,
    build_ws_url,
    generate_pkce_pair,
    parse_auth_cookies,
)
from custom_components.junie_remote.models import (
    ChatSessionState,
    JunieAuthError,
    JunieRemoteError,
    ModelSelectionState,
    TunnelConflictError,
    TunnelInfo,
    TunnelMetadata,
    TunnelNotFoundError,
)

# --- 1. Auth & Cookies Tests ---


def test_parse_auth_cookies_from_storage_state() -> None:
    """Test parsing cookies and XSRF-TOKEN from Playwright storageState JSON."""
    raw_xsrf = "cf-token-123%2Fxyz%3D%3D"
    storage_state = json.dumps({
        "cookies": [
            {"name": "SESSION", "value": "sess-abc-456", "domain": "junie.jetbrains.com"},
            {"name": "XSRF-TOKEN", "value": raw_xsrf, "domain": "junie.jetbrains.com"},
            {"name": "remember_me", "value": "1", "domain": "junie.jetbrains.com"},
        ]
    })

    cookies, xsrf_token = parse_auth_cookies(storage_state)
    assert cookies["SESSION"] == "sess-abc-456"
    assert cookies["XSRF-TOKEN"] == raw_xsrf
    assert cookies["remember_me"] == "1"
    assert xsrf_token == urllib.parse.unquote(raw_xsrf)
    assert xsrf_token == "cf-token-123/xyz=="


def test_parse_auth_cookies_from_raw_header() -> None:
    """Test parsing raw Cookie header string."""
    raw_xsrf = "token%20abc%2B123"
    raw_header = f"SESSION=sess-999; XSRF-TOKEN={raw_xsrf}; other=test_val"

    cookies, xsrf_token = parse_auth_cookies(raw_header)
    assert cookies["SESSION"] == "sess-999"
    assert cookies["XSRF-TOKEN"] == raw_xsrf
    assert cookies["other"] == "test_val"
    assert xsrf_token == "token abc+123"


def test_parse_auth_cookies_missing_xsrf_and_empty() -> None:
    """Test parsing with missing XSRF token and empty string."""
    cookies, xsrf_token = parse_auth_cookies("SESSION=123; foo=bar")
    assert cookies == {"SESSION": "123", "foo": "bar"}
    assert xsrf_token is None

    empty_cookies, empty_xsrf = parse_auth_cookies("")
    assert empty_cookies == {}
    assert empty_xsrf is None


# --- 2. PKCE Generation & WS URL Tests ---


def test_generate_pkce_pair() -> None:
    """Test RFC 7636 PKCE S256 code verifier and challenge generation."""
    verifier, challenge = generate_pkce_pair()

    # 32 random bytes base64url encoded without padding results in 43 characters
    assert len(verifier) == 43
    assert "=" not in verifier

    # Verify SHA256 base64url calculation
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    assert challenge == expected_challenge
    assert len(challenge) == 43
    assert "=" not in challenge

    # Consecutive calls should produce unique pairs
    v2, c2 = generate_pkce_pair()
    assert verifier != v2
    assert challenge != c2


def test_build_ws_url() -> None:
    """Test WebSocket URL construction with scheme rewriting and code_verifier."""
    # HTTPS to WSS without query string
    url1 = build_ws_url("https://junie.jetbrains.com/ws/tunnel/123", "my_verifier")
    assert url1 == "wss://junie.jetbrains.com/ws/tunnel/123?code_verifier=my_verifier"

    # HTTPS to WSS with existing query parameter
    url2 = build_ws_url("https://junie.jetbrains.com/ws?client=1", "my_verifier")
    assert url2 == "wss://junie.jetbrains.com/ws?client=1&code_verifier=my_verifier"

    # HTTP to WS
    url3 = build_ws_url("http://localhost:8080/ws", "my_verifier")
    assert url3 == "ws://localhost:8080/ws?code_verifier=my_verifier"

    # Already WSS
    url4 = build_ws_url("wss://junie.jetbrains.com/ws", "my_verifier")
    assert url4 == "wss://junie.jetbrains.com/ws?code_verifier=my_verifier"


# --- 3. Models & Host Key Tests ---


def test_tunnel_info_and_compute_host_key() -> None:
    """Test TunnelInfo metadata parsing, serialization, and deterministic host key."""
    data = {
        "tunnelId": "c7b3d1e0-1234-4567-89ab-cdef01234567",
        "connectedClients": 1,
        "metadata": {
            "currentDirectory": "/home/alice/projects/repo",
            "userName": "alice",
            "osName": "Linux",
            "createdAt": "2026-11-07T00:00:00Z",
            "gitRepoUrl": "git@gitlab.com:opentasmania/repo.git",
            "gitBranch": "master",
        },
    }

    tunnel = TunnelInfo.from_dict(data)
    assert tunnel.tunnel_id == "c7b3d1e0-1234-4567-89ab-cdef01234567"
    assert tunnel.connected_clients == 1
    assert tunnel.metadata.user_name == "alice"
    assert tunnel.metadata.git_branch == "master"

    # Deterministic slug with gitRepoUrl
    host_key = tunnel.compute_host_key()
    assert host_key == "alice_linux_git_gitlab_com_opentasmania_repo_git"

    # Calling repeatedly produces the exact same slug
    assert tunnel.compute_host_key() == host_key

    # Without gitRepoUrl -> falls back to currentDirectory
    tunnel.metadata.git_repo_url = None
    dir_host_key = tunnel.compute_host_key()
    assert dir_host_key == "alice_linux_home_alice_projects_repo"

    # Without metadata -> falls back to tunnel_id
    empty_tunnel = TunnelInfo(tunnel_id="tid-123", metadata=TunnelMetadata())
    assert empty_tunnel.compute_host_key() == "user_os_tid_123"

    # to_dict roundtrip
    serialized = tunnel.to_dict()
    assert serialized["tunnelId"] == tunnel.tunnel_id
    assert serialized["connectedClients"] == tunnel.connected_clients
    assert serialized["metadata"]["userName"] == "alice"


def test_model_selection_and_options() -> None:
    """Test ModelSelectionState and ModelOption selectable formatting."""
    data = {
        "currentModelId": "claude-3-7-sonnet",
        "currentEffortId": "high",
        "models": [
            {
                "id": "claude-3-7-sonnet",
                "name": "Claude 3.7 Sonnet",
                "currentEffortId": "high",
                "supportedEfforts": [
                    {"id": "low", "name": "Low"},
                    {"id": "high", "name": "High"},
                ],
            },
            {
                "id": "gpt-4o",
                "name": "GPT-4o",
                "supportedEfforts": [],
            },
        ],
    }

    state = ModelSelectionState.from_dict(data)
    assert state.current_selection == "claude-3-7-sonnet:high"

    options = state.get_selectable_options()
    assert len(options) == 3
    assert options[0] == ("claude-3-7-sonnet:low", "Claude 3.7 Sonnet · Low")
    assert options[1] == ("claude-3-7-sonnet:high", "Claude 3.7 Sonnet · High")
    assert options[2] == ("gpt-4o", "GPT-4o")

    # Roundtrip serialization
    d = state.to_dict()
    assert d["currentModelId"] == "claude-3-7-sonnet"
    assert len(d["models"]) == 2


# --- 4. ChatSessionState Event Reducer Tests ---


def test_chat_session_state_event_reducer() -> None:
    """Test applying incoming WebSocket events across all defined event types."""
    state = ChatSessionState()

    # 1. session-metadata
    state.apply_event({
        "type": "session-metadata",
        "title": "Fix authentication bug",
        "gitBranch": "feature/auth",
        "workingDir": "/home/user/project",
    })
    assert state.title == "Fix authentication bug"
    assert state.git_branch == "feature/auth"
    assert state.working_dir == "/home/user/project"

    # 2. ready-step
    state.apply_event({
        "type": "ready-step",
        "step": {
            "type": "user-prompt",
            "prompt": "Investigate bug",
        },
    })
    assert len(state.history) == 1
    assert state.history[0]["prompt"] == "Investigate bug"

    # 3. progressing-steps
    state.apply_event({
        "type": "progressing-steps",
        "steps": [{"stepId": "s1", "type": "command", "title": "pytest"}],
    })
    assert len(state.progressing_steps) == 1
    assert state.progressing_steps[0]["stepId"] == "s1"

    # 4. active-requests
    state.apply_event({
        "type": "active-requests",
        "requests": [{"requestId": "r1", "type": "ask", "question": "Proceed?"}],
    })
    assert len(state.active_requests) == 1
    assert state.active_requests[0]["requestId"] == "r1"

    # 5. brave-mode-state
    state.apply_event({"type": "brave-mode-state", "enabled": True})
    assert state.brave_mode is True

    # 6. model-selection-state
    state.apply_event({
        "type": "model-selection-state",
        "currentModelId": "claude-3-7-sonnet",
        "currentEffortId": "medium",
        "models": [{"id": "claude-3-7-sonnet", "name": "Claude 3.7", "supportedEfforts": []}],
    })
    assert state.model_selection.current_model_id == "claude-3-7-sonnet"
    assert state.model_selection.current_effort_id == "medium"

    # 7. plan-proposal with seq=5
    state.apply_event({
        "type": "plan-proposal",
        "seq": 5,
        "readyForReview": True,
        "showActions": True,
        "planFilePath": "/path/to/plan.md",
        "sections": [{"name": "Sec1", "content": "Content"}],
        "deliverySteps": [{"name": "Step1", "description": "Desc"}],
    })
    assert state.plan_proposal is not None
    assert state.plan_proposal.seq == 5
    assert state.plan_proposal.ready_for_review is True

    # 8. session-status with hasPlan=False and seq=6 -> clears prior plan proposal with seq < 6
    state.apply_event({
        "type": "session-status",
        "status": "waiting-for-input",
        "canSendPrompt": False,
        "braveMode": True,
        "hasPlan": False,
        "seq": 6,
    })
    assert state.session_status == "waiting-for-input"
    assert state.can_send_prompt is False
    assert state.has_plan is False
    assert state.last_status_seq == 6
    assert state.last_reset_seq == 6
    assert state.plan_proposal is None

    # Stale plan proposal with seq=5 (< last_reset_seq 6) is ignored
    state.apply_event({
        "type": "plan-proposal",
        "seq": 5,
        "readyForReview": True,
    })
    assert state.plan_proposal is None

    # New plan proposal with seq=7 (>= 6) is accepted
    state.apply_event({
        "type": "plan-proposal",
        "seq": 7,
        "readyForReview": True,
    })
    assert state.plan_proposal is not None
    assert state.plan_proposal.seq == 7

    # session-status with hasPlan=True keeps plan proposal
    state.apply_event({
        "type": "session-status",
        "status": "idle",
        "canSendPrompt": True,
        "hasPlan": True,
        "seq": 8,
    })
    assert state.has_plan is True
    assert state.plan_proposal is not None
    assert state.plan_proposal.seq == 7

    # to_dict serialization
    serialized = state.to_dict()
    assert serialized["title"] == "Fix authentication bug"
    assert serialized["sessionStatus"] == "idle"
    assert serialized["canSendPrompt"] is True
    assert serialized["hasPlan"] is True
    assert serialized["planProposal"]["seq"] == 7
    assert len(serialized["history"]) == 1


# --- 5. REST Client API Tests ---


@pytest.mark.asyncio
async def test_rest_client_api_methods() -> None:
    """Test all REST API endpoints, auth headers, and error handling."""
    captured_headers: dict[str, str] = {}
    tunnel_id = "test-tunnel-123"

    async def list_handler(request: web.Request) -> web.Response:
        captured_headers.update(request.headers)
        return web.json_response([
            {
                "tunnelId": tunnel_id,
                "connectedClients": 0,
                "metadata": {
                    "userName": "alice",
                    "osName": "Linux",
                    "currentDirectory": "/home/alice",
                },
            }
        ])

    async def get_handler(request: web.Request) -> web.Response:
        tid = request.match_info["tunnel_id"]
        if tid != tunnel_id:
            return web.json_response({"message": "Not found"}, status=404)
        return web.json_response({
            "tunnelId": tid,
            "connectedClients": 0,
            "metadata": {"userName": "alice", "osName": "Linux"},
        })

    async def connect_handler(request: web.Request) -> web.Response:
        tid = request.match_info["tunnel_id"]
        body = await request.json()
        assert body["codeChallengeMethod"] == "S256"
        assert len(body["codeChallenge"]) > 0
        if tid == "conflict-tunnel":
            return web.json_response({"message": "Another client connected"}, status=409)
        return web.json_response({"wsUrl": f"https://mock-ws/tunnel/{tid}"})

    async def kick_handler(request: web.Request) -> web.Response:
        return web.Response(status=204)

    async def tokens_handler(request: web.Request) -> web.Response:
        if request.method == "POST":
            body = await request.json()
            return web.json_response({"id": "tok-1", "name": body["name"]}, status=201)
        return web.Response(status=204)

    async def auth_fail_handler(request: web.Request) -> web.Response:
        return web.json_response({"error": "Unauthorized session"}, status=401)

    async def server_error_handler(request: web.Request) -> web.Response:
        return web.Response(status=500, text="Internal Server Error")

    app = web.Application()
    app.router.add_get("/api/public/cli/tunnel/tunnels", list_handler)
    app.router.add_get("/api/public/cli/tunnel/tunnels/{tunnel_id}", get_handler)
    app.router.add_post(
        "/api/public/cli/tunnel/tunnels/{tunnel_id}/client/connect", connect_handler
    )
    app.router.add_post("/api/public/cli/tunnel/tunnels/{tunnel_id}/kick-client", kick_handler)
    app.router.add_post("/api/public/cli/tokens", tokens_handler)
    app.router.add_delete("/api/public/cli/tokens/{token_id}", tokens_handler)
    app.router.add_get("/api/public/cli/auth-fail", auth_fail_handler)
    app.router.add_get("/api/public/cli/server-error", server_error_handler)

    server = TestServer(app)
    await server.start_server()

    try:
        auth_cookie_str = "XSRF-TOKEN=xsrf%20token%3D; SESSION=sess-123"
        async with JunieRemoteClient(
            auth_input=auth_cookie_str,
            base_url=str(server.make_url("")),
        ) as client:
            # 1. list_tunnels
            tunnels = await client.list_tunnels()
            assert len(tunnels) == 1
            assert tunnels[0].tunnel_id == tunnel_id
            assert "Cookie" in captured_headers
            assert "X-XSRF-TOKEN" in captured_headers
            assert captured_headers["X-XSRF-TOKEN"] == "xsrf token="

            # 2. get_tunnel
            t = await client.get_tunnel(tunnel_id)
            assert t.tunnel_id == tunnel_id

            # 3. get_tunnel 404 -> TunnelNotFoundError
            with pytest.raises(TunnelNotFoundError):
                await client.get_tunnel("unknown-tunnel")

            # 4. connect_tunnel
            ws_url = await client.connect_tunnel(tunnel_id, code_challenge="challenge_xyz")
            assert ws_url == f"https://mock-ws/tunnel/{tunnel_id}"

            # 5. connect_tunnel 409 -> TunnelConflictError
            with pytest.raises(TunnelConflictError):
                await client.connect_tunnel("conflict-tunnel", code_challenge="challenge_xyz")

            # 6. kick_client
            await client.kick_client(tunnel_id)

            # 7. create_token & delete_token
            tok = await client.create_token("my-token")
            assert tok["id"] == "tok-1"
            assert tok["name"] == "my-token"
            await client.delete_token("tok-1")

            # 8. 401 Unauthorized -> JunieAuthError
            with pytest.raises(JunieAuthError):
                await client._request("GET", "/cli/auth-fail")

            # 9. 500 Server Error -> JunieRemoteError
            with pytest.raises(JunieRemoteError):
                await client._request("GET", "/cli/server-error")

    finally:
        await server.close()


# --- 6. JunieTunnelSession WebSocket Tests ---


@pytest.mark.asyncio
async def test_tunnel_session_handshake_and_commands() -> None:
    """Test WebSocket connection, handshake, incoming events, and outgoing commands."""
    received_frames: list[dict[str, Any]] = []
    ws_connected_event = asyncio.Event()

    async def ws_handler(request: web.Request) -> web.WebSocketResponse:
        # Check code_verifier param
        verifier = request.query.get("code_verifier")
        assert verifier is not None

        ws = web.WebSocketResponse()
        await ws.prepare(request)

        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                received_frames.append(data)

                # Handshake: on client-connected, reply agent-ready
                if data.get("type") == "client-connected":
                    ws_connected_event.set()
                    await ws.send_json({
                        "type": "agent-ready",
                        "requestId": data.get("requestId"),
                        "tunnelId": "tunnel-test",
                    })

                elif data.get("type") == "prompt":
                    # Send back a response event
                    await ws.send_json({
                        "type": "ready-step",
                        "step": {
                            "type": "user-prompt",
                            "prompt": data.get("prompt"),
                        },
                    })
            elif msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSED):
                break

        return ws

    async def connect_api(request: web.Request) -> web.Response:
        return web.json_response({"wsUrl": f"http://{request.host}/ws"})

    async def kick_api(request: web.Request) -> web.Response:
        return web.Response(status=204)

    app = web.Application()
    app.router.add_post("/api/public/cli/tunnel/tunnels/{tunnel_id}/client/connect", connect_api)
    app.router.add_post("/api/public/cli/tunnel/tunnels/{tunnel_id}/kick-client", kick_api)
    app.router.add_get("/ws", ws_handler)

    server = TestServer(app)
    await server.start_server()

    status_changes: list[str] = []
    received_events: list[dict[str, Any]] = []

    def on_status(status: str, error: Exception | None) -> None:
        status_changes.append(status)

    def on_event(event: dict[str, Any], state: ChatSessionState) -> None:
        received_events.append(event)

    try:
        async with JunieRemoteClient(base_url=str(server.make_url(""))) as client:
            session = JunieTunnelSession(
                client=client,
                tunnel_id="tunnel-test",
                handshake_timeout=5.0,
                on_status_change=on_status,
                on_event=on_event,
            )

            assert session.connection_status == "disconnected"

            # Connect and handshake
            await session.connect()
            assert session.connection_status == "connected"
            assert "connecting" in status_changes
            assert "connected" in status_changes
            assert len(received_frames) >= 1
            assert received_frames[0]["type"] == "client-connected"

            # Send outgoing helper commands
            await session.send_prompt("Hello Junie")
            await session.send_plan_prompt("Refine architecture")
            await session.confirm_plan()
            await session.cancel()
            await session.toggle_brave_mode(True)
            await session.select_model("claude-3-7-sonnet", "high")
            await session.send_response("Allow once", {
                "method": "approve",
                "requestId": "req-1",
                "approve": True,
            })

            # Wait briefly for server to process and respond
            await asyncio.sleep(0.1)

            # Verify outgoing command payloads received by mock server
            types_sent = [f["type"] for f in received_frames]
            assert "prompt" in types_sent
            assert "planPrompt" in types_sent
            assert "confirmAndImplementPlan" in types_sent
            assert "cancel" in types_sent
            assert "toggleBraveMode" in types_sent
            assert "selectModel" in types_sent
            assert "response" in types_sent

            # Verify model selection payload
            model_frame = next(f for f in received_frames if f["type"] == "selectModel")
            assert model_frame["modelId"] == "claude-3-7-sonnet"
            assert model_frame["effortId"] == "high"

            # Verify response frame
            resp_frame = next(f for f in received_frames if f["type"] == "response")
            assert resp_frame["displayText"] == "Allow once"
            assert resp_frame["response"]["method"] == "approve"

            # Verify state was updated with ready-step sent back by server
            assert len(session.state.history) >= 1
            assert session.state.history[0]["prompt"] == "Hello Junie"
            assert len(received_events) >= 1

            # Dispose connection
            await session.dispose()
            assert session.connection_status == "disconnected"
            assert session.ws is None

            # Sending when disconnected raises JunieRemoteError
            with pytest.raises(JunieRemoteError):
                await session.send_prompt("Failed prompt")

    finally:
        await server.close()


@pytest.mark.asyncio
async def test_tunnel_session_handshake_timeout() -> None:
    """Test handshake timeout when server does not respond with agent-ready."""
    async def noop_ws_handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        # Never send agent-ready
        await asyncio.sleep(5)
        return ws

    async def connect_api(request: web.Request) -> web.Response:
        return web.json_response({"wsUrl": f"http://{request.host}/ws"})

    app = web.Application()
    app.router.add_post("/api/public/cli/tunnel/tunnels/{tunnel_id}/client/connect", connect_api)
    app.router.add_get("/ws", noop_ws_handler)

    server = TestServer(app)
    await server.start_server()

    try:
        async with JunieRemoteClient(base_url=str(server.make_url(""))) as client:
            session = JunieTunnelSession(
                client=client,
                tunnel_id="tunnel-timeout",
                handshake_timeout=0.2,  # Quick timeout
            )
            with pytest.raises(JunieRemoteError, match="Handshake timed out"):
                await session.connect()

            assert session.connection_status == "failed"
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_tunnel_session_client_kicked() -> None:
    """Test handling of WebSocket close with reason 'client-kicked'."""
    async def kicked_ws_handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") == "client-connected":
                    await ws.send_json({
                        "type": "agent-ready",
                        "requestId": data.get("requestId"),
                        "tunnelId": "tunnel-kicked",
                    })
                    # Immediately kick client
                    await ws.close(code=1000, message=b"client-kicked")
                    break

        return ws

    async def connect_api(request: web.Request) -> web.Response:
        return web.json_response({"wsUrl": f"http://{request.host}/ws"})

    async def kick_api(request: web.Request) -> web.Response:
        return web.Response(status=204)

    app = web.Application()
    app.router.add_post("/api/public/cli/tunnel/tunnels/{tunnel_id}/client/connect", connect_api)
    app.router.add_post("/api/public/cli/tunnel/tunnels/{tunnel_id}/kick-client", kick_api)
    app.router.add_get("/ws", kicked_ws_handler)

    server = TestServer(app)
    await server.start_server()

    try:
        async with JunieRemoteClient(base_url=str(server.make_url(""))) as client:
            session = JunieTunnelSession(
                client=client,
                tunnel_id="tunnel-kicked",
                handshake_timeout=2.0,
            )
            await session.connect()
            # Wait for close frame to be processed
            await asyncio.sleep(0.1)

            assert session.connection_status == "kicked"

            # Test kick_and_retry
            # After kick_and_retry, it calls kick_client then connect
            # We can verify it executes without error (will be kicked again)
            await session.kick_and_retry(wait_delay=0.01)
            await asyncio.sleep(0.1)
            assert session.connection_status == "kicked"

    finally:
        await server.close()
