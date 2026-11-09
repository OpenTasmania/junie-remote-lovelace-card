"""Real Home Assistant proof of the PRODUCTION transcript view.

Runs against HA's real HTTP stack (auth middleware, ``hass_client``,
``hass_client_no_auth`` and a real WebSocket ``auth/sign_path`` client) with
the integration's real ``LocalTranscriptStorage``, ``TranscriptInventory``,
``JunieRemoteCoordinator`` and ``async_register_transcript_view``. Only the
Junie cloud client is a stub; nothing in the authorization path is mocked.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.config_entries import ConfigEntryState, current_entry
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from yarl import URL

from custom_components.junie_remote import async_setup_entry, async_unload_entry
from custom_components.junie_remote.const import DOMAIN
from custom_components.junie_remote.coordinator import JunieRemoteCoordinator
from custom_components.junie_remote.models import (
    ChatSessionState,
    TunnelInfo,
    TunnelMetadata,
)
from custom_components.junie_remote.storage import (
    LocalTranscriptStorage,
    TranscriptDocument,
)
from custom_components.junie_remote.transcript_http import (
    async_register_transcript_view,
)
from custom_components.junie_remote.transcript_inventory import (
    INVENTORY_HASS_KEY,
    TranscriptInventory,
)

SECRET = "TOP-SECRET-PROMPT"


def make_doc(host_key: str, label: str) -> TranscriptDocument:
    tunnel = TunnelInfo(
        tunnel_id=f"tunnel-{label}",
        connected_clients=1,
        metadata=TunnelMetadata(user_name=label, os_name="linux"),
    )
    state = ChatSessionState(
        title=f"{SECRET} {label}",
        history=[{"type": "user-prompt", "prompt": f"{SECRET} {label}"}],
    )
    return TranscriptDocument.build(host_key, tunnel, state, "connected", "2026-01-01T00:00:00Z")


def make_coordinator(hass, entry, root, www, inventory):
    storage = LocalTranscriptStorage(
        base_dir=root, entry_id=entry.entry_id, inventory=inventory, public_roots=[www]
    )
    coordinator = JunieRemoteCoordinator(hass, MagicMock(), storage, auto_connect=False)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    return coordinator


@pytest.fixture
async def proof(hass, hass_client, hass_client_no_auth, hass_ws_client, tmp_path):
    assert await async_setup_component(
        hass,
        "http",
        {"http": {"use_x_forwarded_for": True, "trusted_proxies": ["127.0.0.1"]}},
    )
    assert await async_setup_component(hass, "websocket_api", {})
    assert await async_setup_component(hass, "auth", {})
    assert async_register_transcript_view(hass)
    assert async_register_transcript_view(hass)  # idempotent: no duplicate route

    entries = [MockConfigEntry(domain=DOMAIN) for _ in range(2)]
    other = MockConfigEntry(domain="some_other_integration")
    for entry in [*entries, other]:
        entry.add_to_hass(hass)

    root = tmp_path / "private"
    www = tmp_path / "www"
    www.mkdir()
    inventory = hass.data[INVENTORY_HASS_KEY] = TranscriptInventory(hass)
    results = {}
    coordinators = {}
    docs = {}
    for entry, label in zip(entries, ("a", "b"), strict=True):
        coordinators[entry.entry_id] = make_coordinator(hass, entry, root, www, inventory)
        docs[label] = make_doc(f"host-{label}", label)
        results[label] = await coordinators[entry.entry_id].storage.async_save_transcript(
            docs[label]
        )
    # An unrelated integration entry that happens to have a coordinator-shaped object
    make_coordinator(hass, other, root, www, inventory)
    await hass.data[DOMAIN][other.entry_id].storage.async_save_transcript(
        make_doc("host-a", "other")
    )

    return SimpleNamespace(
        hass=hass,
        entries=entries,
        other=other,
        root=root,
        www=www,
        tmp=tmp_path,
        docs=docs,
        results=results,
        inventory=inventory,
        coordinators=coordinators,
        anonymous=await hass_client_no_auth(),
        admin=await hass_client(),
        admin_ws=await hass_ws_client(),
    )


def entry_root(proof, entry) -> Path:
    return proof.root.resolve() / entry.entry_id


def transcript_path(entry, host, file_format):
    return f"/api/junie_remote/transcripts/{entry.entry_id}/{host}/{file_format}"


async def sign(ws, path, expires=30):
    await ws.send_json_auto_id({"type": "auth/sign_path", "path": path, "expires": expires})
    result = await ws.receive_json()
    assert result["success"] is True
    return result["result"]["path"]


async def test_authentication_and_admin_access(proof):
    for entry, host, label in zip(proof.entries, ("host-a", "host-b"), ("a", "b"), strict=True):
        doc = proof.docs[label]
        for file_format, body, content_type in (
            ("json", doc.to_json(), "application/json"),
            ("md", doc.render_markdown(), "text/markdown"),
        ):
            path = transcript_path(entry, host, file_format)
            assert (await proof.anonymous.get(path)).status == 401
            response = await proof.admin.get(path)
            assert response.status == 200
            assert response.content_type == content_type
            assert await response.text() == body
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert "Content-Disposition" not in response.headers
            response = await proof.anonymous.get(await sign(proof.admin_ws, path))
            assert response.status == 200
            assert response.content_type == content_type
            assert await response.text() == body


async def test_sensor_urls_use_authenticated_view_and_never_carry_credentials(proof):
    for entry, label, host in zip(proof.entries, ("a", "b"), ("host-a", "host-b"), strict=True):
        result = proof.results[label]
        for url, file_format in ((result.json_url, "json"), (result.md_url, "md")):
            assert url.startswith(f"/api/junie_remote/transcripts/{entry.entry_id}/{host}/")
            assert "authSig" not in url and "token" not in url.lower()
            assert "/local/" not in url
            assert (await proof.anonymous.get(url)).status == 401
            response = await proof.admin.get(url)
            assert response.status == 200
            assert SECRET in await response.text()
            # on-demand signed download of exactly the URL held in entity state
            download = URL(url).update_query(download="1")
            signed = await sign(proof.admin_ws, f"{download.path}?{download.query_string}")
            response = await proof.anonymous.get(signed)
            assert response.status == 200
            assert response.headers["Content-Disposition"] == (
                f'attachment; filename="junie-{host}.{file_format}"'
            )
    assert not list(proof.www.rglob("*"))


async def test_non_admin_bearer_and_signed_paths_denied(
    proof, hass, hass_client, hass_ws_client, hass_read_only_access_token
):
    user = await hass.auth.async_create_user("regular", group_ids=[GROUP_ID_USER])
    assert not user.is_admin
    refresh = await hass.auth.async_create_refresh_token(user, client_id="https://example.com/")
    token = hass.auth.async_create_access_token(refresh)
    for access_token in (token, hass_read_only_access_token):
        client = await hass_client(access_token)
        ws = await hass_ws_client(access_token=access_token)
        for file_format in ("json", "md"):
            path = transcript_path(proof.entries[0], "host-a", file_format)
            response = await client.get(path)
            assert response.status == 403
            assert SECRET not in await response.text()
            signed = await sign(ws, path)
            response = await proof.anonymous.get(signed)
            assert response.status == 403
            assert SECRET not in await response.text()


async def test_entry_host_and_path_containment(proof):
    a, b = proof.entries
    paths = [
        transcript_path(a, "host-b", "json"),
        transcript_path(b, "host-a", "json"),
        "/api/junie_remote/transcripts/missing/host-a/json",
        transcript_path(proof.other, "host-a", "json"),
        transcript_path(a, "host-a", "txt"),
        transcript_path(a, "..", "json"),
        transcript_path(a, "tunnel-tunnel-a", "json"),
        URL(f"/api/junie_remote/transcripts/{a.entry_id}/%2e%2e%2fhost-b/json", encoded=True),
        URL(
            f"/api/junie_remote/transcripts/{a.entry_id}/..%2f{b.entry_id}%2fhost-b/json",
            encoded=True,
        ),
        URL(f"/api/junie_remote/transcripts/{a.entry_id}/host-a/%2e%2e%2fjson", encoded=True),
        URL(f"/api/junie_remote/transcripts/{a.entry_id}/host-a/../json", encoded=True),
        URL(f"/api/junie_remote/transcripts/../{b.entry_id}/host-b/json", encoded=True),
    ]
    for path in paths:
        response = await proof.admin.get(path)
        assert response.status in (400, 404), (str(path), response.status)
        assert SECRET not in await response.text()
        if isinstance(path, str):
            response = await proof.anonymous.get(await sign(proof.admin_ws, path))
            assert response.status == 404, (path, response.status)
    # a smuggled other-entry host remains reachable only under its own entry
    assert (await proof.admin.get(transcript_path(b, "host-b", "json"))).status == 200


async def test_filesystem_tampering_is_not_served(proof):
    a, b = proof.entries
    path = transcript_path(a, "host-a", "json")
    host_dir = entry_root(proof, a) / "host-a"
    original = (host_dir / "latest.json").read_bytes()
    assert (await proof.admin.get(path)).status == 200

    outside = proof.tmp / "outside.json"
    outside.write_text(SECRET + " outside")
    for victim in (outside, entry_root(proof, b) / "host-b" / "latest.json"):
        (host_dir / "latest.json").unlink()
        (host_dir / "latest.json").symlink_to(victim)
        response = await proof.admin.get(path)
        assert response.status == 404
        assert "outside" not in await response.text()
        (host_dir / "latest.json").unlink()
        (host_dir / "latest.json").write_bytes(original)
    assert (await proof.admin.get(path)).status == 200

    # regular file swapped for different content is not provably ours
    (host_dir / "latest.json").write_text("swapped")
    assert (await proof.admin.get(path)).status == 404
    (host_dir / "latest.json").write_bytes(original)

    # host directory replaced by a symlink to another entry's/outside directory
    moved = entry_root(proof, a) / "host-a.real"
    host_dir.rename(moved)
    host_dir.symlink_to(moved, target_is_directory=True)
    assert (await proof.admin.get(path)).status == 404
    host_dir.unlink()
    moved.rename(host_dir)
    assert (await proof.admin.get(path)).status == 200

    # entry root itself replaced by a symlink to another entry
    a_root = entry_root(proof, a)
    parked = proof.root / "parked"
    a_root.rename(parked)
    a_root.symlink_to(entry_root(proof, b), target_is_directory=True)
    assert (await proof.admin.get(path)).status == 404
    a_root.unlink()
    parked.rename(a_root)
    assert (await proof.admin.get(path)).status == 200


async def test_storage_inside_public_root_is_refused(proof, hass):
    entry = proof.entries[0]
    (proof.www / "junie").mkdir()
    storage = proof.coordinators[entry.entry_id].storage
    storage.base_dir = proof.www / "junie"
    response = await proof.admin.get(transcript_path(entry, "host-a", "json"))
    assert response.status == 404
    assert not list((proof.www / "junie").rglob("*.json"))


async def test_restart_and_reload_preserve_access(proof, hass):
    entry = proof.entries[0]
    path = transcript_path(entry, "host-a", "md")
    old = proof.coordinators[entry.entry_id]
    await old.async_shutdown()
    inventory = hass.data[INVENTORY_HASS_KEY] = TranscriptInventory(hass)
    make_coordinator(hass, entry, proof.root, proof.www, inventory)
    response = await proof.admin.get(path)
    assert response.status == 200
    assert SECRET in await response.text()
    # a new write after restart still owns the same files
    new = hass.data[DOMAIN][entry.entry_id]
    await new.storage.async_save_transcript(make_doc("host-a", "a2"))
    assert "a2" in await (await proof.admin.get(path)).text()
    # removed (unloaded) entry is not served
    hass.data[DOMAIN].pop(entry.entry_id)
    assert (await proof.admin.get(path)).status == 404


async def test_s3_entries_are_not_served_locally(proof, hass):
    entry = proof.entries[0]
    hass.data[DOMAIN][entry.entry_id].storage = MagicMock()
    assert (await proof.admin.get(transcript_path(entry, "host-a", "json"))).status == 404


async def test_signed_access_rechecks_admin_privileges(proof, hass, hass_admin_user):
    assert hass_admin_user.is_admin and not hass_admin_user.is_owner
    path = transcript_path(proof.entries[0], "host-a", "json")
    signed = await sign(proof.admin_ws, path)
    assert (await proof.anonymous.get(signed)).status == 200
    await hass.auth.async_update_user(hass_admin_user, group_ids=[GROUP_ID_USER])
    assert not hass_admin_user.is_admin
    assert (await proof.anonymous.get(signed)).status == 403
    assert (await proof.admin.get(path)).status == 403


async def test_local_only_admin_signed_link_cannot_be_used_remotely(proof, hass, hass_admin_user):
    await hass.auth.async_update_user(hass_admin_user, local_only=True)
    path = transcript_path(proof.entries[0], "host-a", "json")
    signed = await sign(proof.admin_ws, path)
    assert (await proof.anonymous.get(signed)).status == 200
    remote = {"X-Forwarded-For": "8.8.8.8"}
    assert (await proof.admin.get(path, headers=remote)).status == 401
    assert (await proof.anonymous.get(signed, headers=remote)).status == 403


async def test_signed_download_tampering_and_expiration(proof, freezer):
    path = transcript_path(proof.entries[0], "host-a", "md")
    signed = await sign(proof.admin_ws, path, expires=5)
    assert (await proof.anonymous.get(signed)).status == 200
    assert (await proof.anonymous.get(signed + "&tampered=1")).status == 401
    assert (await proof.anonymous.get(signed + "&download=1")).status == 401
    changed_path = signed.replace(
        f"{proof.entries[0].entry_id}/host-a", f"{proof.entries[1].entry_id}/host-b"
    )
    assert (await proof.anonymous.get(changed_path)).status == 401
    token = URL(signed).query["authSig"]
    replacement = ("A" if token[0] != "A" else "B") + token[1:]
    assert (await proof.anonymous.get(signed.replace(token, replacement))).status == 401
    freezer.tick(6)
    assert (await proof.anonymous.get(signed)).status == 401
    assert (await proof.anonymous.get(await sign(proof.admin_ws, path, expires=-1))).status == 401


async def test_signed_download_revoked_with_refresh_token(proof, hass, hass_access_token):
    path = transcript_path(proof.entries[0], "host-a", "md")
    signed = await sign(proof.admin_ws, path)
    assert (await proof.anonymous.get(signed)).status == 200
    refresh = hass.auth.async_validate_access_token(hass_access_token)
    assert refresh is not None
    hass.auth.async_remove_refresh_token(refresh)
    assert (await proof.anonymous.get(signed)).status == 401
    assert (await proof.admin.get(path)).status == 401


async def test_user_deactivation_revokes_signed_download(proof, hass, hass_admin_user):
    path = transcript_path(proof.entries[1], "host-b", "md")
    signed = await sign(proof.admin_ws, path)
    assert (await proof.anonymous.get(signed)).status == 200
    await hass.auth.async_deactivate_user(hass_admin_user)
    assert (await proof.anonymous.get(signed)).status == 401


async def test_entity_attribute_and_logs_contain_no_credentials(proof, caplog):
    caplog.set_level("DEBUG")
    path = transcript_path(proof.entries[0], "host-a", "json")
    signed = await sign(proof.admin_ws, path)
    await proof.anonymous.get(signed)
    await proof.admin.get(transcript_path(proof.entries[0], "..", "json"))
    sig = URL(signed).query["authSig"]
    integration_logs = "\n".join(
        r.getMessage() for r in caplog.records if r.name.startswith("custom_components")
    )
    assert sig not in integration_logs
    assert SECRET not in integration_logs
    for result in proof.results.values():
        assert "authSig" not in result.json_url + result.md_url


async def test_real_setup_entry_wires_private_storage_and_protected_view(
    hass, hass_client, hass_client_no_auth
):
    assert await async_setup_component(hass, "http", {"http": {}})
    entry = MockConfigEntry(domain=DOMAIN, data={"auth_input": "test"})
    entry.add_to_hass(hass)
    object.__setattr__(entry, "state", ConfigEntryState.SETUP_IN_PROGRESS)
    cloud = MagicMock()
    cloud.list_tunnels = AsyncMock(return_value=[])
    cloud.close = AsyncMock()
    token = current_entry.set(entry)
    try:
        with patch("custom_components.junie_remote.JunieRemoteClient", return_value=cloud):
            assert await async_setup_entry(hass, entry)
    finally:
        current_entry.reset(token)
    storage = hass.data[DOMAIN][entry.entry_id].storage
    assert isinstance(storage, LocalTranscriptStorage)
    assert storage.base_dir == Path(hass.config.path("junie_remote", "transcripts"))
    result = await storage.async_save_transcript(make_doc("wired-host", "wired"))
    assert (await (await hass_client_no_auth()).get(result.json_url)).status == 401
    response = await (await hass_client()).get(result.json_url)
    assert response.status == 200
    assert SECRET in await response.text()
    assert await async_unload_entry(hass, entry)
