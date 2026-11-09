# Real Home Assistant transcript access proof

These tests exercise the **production** transcript view
(`custom_components/junie_remote/transcript_http.py`) on real Home Assistant:
real HTTP auth middleware, `hass_client` / `hass_client_no_auth`, a real
WebSocket `auth/sign_path` client, and the integration's real storage,
inventory and coordinator objects (only the Junie cloud client is stubbed).
One test also calls the production `async_setup_entry` with a real config-entry
setup context to verify default storage and route wiring. The inventory tests
use a plain `HomeAssistant(config_dir)` instead of the `hass_storage` fixture,
so disk-write failures and shutdown-state persistence exercise real HA I/O.
They do not prove protection of legacy public copies in `/config/www`, S3
bucket policy, reverse-proxy log redaction, real-browser behaviour, or any HA
version other than the one below. Filesystem checks are TOCTOU-limited: reads
use `O_NOFOLLOW` and a digest recorded in the ownership inventory, but an
external process with write access to the private directory is out of scope.

Tested baseline: Python 3.13.5, Home Assistant 2026.2.3,
pytest-homeassistant-custom-component 0.13.316, pytest 9.0.0,
pytest-asyncio 1.3.0, aiohttp 3.13.3 and PyJWT 2.10.1. No other Home Assistant
version has been tested or is claimed compatible; the integration currently
declares no minimum HA version. The direct proof dependencies are pinned in
`ha_tests/requirements.txt`; the remaining transitive dependencies are not
locked. Create an isolated environment and run:

```sh
uv venv --python python3.13 .venv/ha-proof
uv pip install --python .venv/ha-proof/bin/python -e . -r ha_tests/requirements.txt
.venv/ha-proof/bin/pytest ha_tests/test_transcript_http.py
```

These tests live outside the normal `tests` path, which uses the compatibility
layer rather than HA. In the tested HA version, `HomeAssistantView`'s request
wrapper enforces `requires_auth`; HTTP authentication supplies `hass_user` for
both bearer and signed requests. `auth/sign_path` is an authenticated
WebSocket command that signs with the connection's refresh token and defaults
to 30 seconds. Non-admin users can sign paths, so the view must independently
check `user.is_admin`. HA's signed request validator checks path, query,
expiration and refresh-token existence; unlike its bearer-token branch, it
does not call `async_user_not_allowed_do_auth` in this version. An admin check
alone allowed a remote signed request from a local-only admin in a real-HA
reverse-proxy test, while the corresponding bearer request was rejected. The
proof view also calls HA's `async_user_not_allowed_do_auth(hass, user, request)`
and the test verifies the remote signed request is denied. Production must
replicate and retest this restriction as well as deactivation and revocation;
this helper's compatibility with other HA versions is unverified.

Signed URLs are bearer credentials: do not store them in entity state or log
them in integration code. Test-server `aiohttp.access` logs included full
signed URLs when INFO logging was enabled; production access logs, reverse
proxies and other intermediaries can likewise record request targets. Configure
or redact such logs as appropriate; this proof does not establish that the
deployment's logs are secret-free.