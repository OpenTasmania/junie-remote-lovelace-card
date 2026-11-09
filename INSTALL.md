<!--
SPDX-License-Identifier: MIT
Copyright (c) 2026 Peter Lawler
-->

# Installing Junie Remote Integration & Lovelace Card

This guide covers all installation methods for the **JetBrains Junie Remote** Home Assistant custom integration (`custom_components/junie_remote`) and Lovelace card (`junie-remote-card`).

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://hacs.xyz)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=OpenTasmania&repository=junie-remote-lovelace-card&category=integration)

---

> ## ⚠️ Security notice: transcript exposure (read before choosing storage)
>
> Junie transcripts contain prompts, source code, command output and results.
>
> - **Earlier versions published local transcripts publicly.** Home Assistant serves everything under `/config/www` at `/local/` **without authentication**, and earlier versions wrote `latest.json`, `latest.md` and `<tunnel_id>.json` to `/config/www/junie_remote/<host_key>/`. Anyone who can reach your Home Assistant and knows or guesses a URL could read them. **Those files are not deleted or moved by this integration.** Find them with `ls -R /config/www/junie_remote`, delete them yourself once you no longer need them, and review Home Assistant backups, snapshots and any reverse-proxy or CDN caches, which may still contain copies. Reload and uninstall never delete them.
> - **New local transcripts are private by default.** They are written under `/config/junie_remote/transcripts/<entry_id>/<host_key>/` (or a custom path). The integration rejects paths resolving inside `/config/www` or its own `custom_components/junie_remote/frontend` directory, including symlinks. **Other integrations may serve other directories:** these are not detected. Before choosing a custom path, verify it is not publicly served by any HTTP route or web server. New files are served only by an authenticated Home Assistant view to **administrator** users. The card fetches them with your Home Assistant login; downloads use short-lived signed links created on demand (they are bearer credentials: do not share or log them). Non-administrator dashboard users cannot view local transcripts.
> - **S3 storage is your responsibility.** Exposure depends on your bucket policy, CDN or *S3 Public Base URL*. A public base URL makes transcripts readable by anyone with the URL, and presigned URLs are bearer credentials stored in the entity's state attributes (and therefore possibly in the recorder history and backups).
> - **Entity attributes and recorder.** Sensor attributes include previews, active requests and plan summaries; the recorder may retain them. Exclude the Junie sensors from the recorder if that matters to you.
> - **Verification status.** The access rules (unauthenticated 401, non-admin 403, admin success, expiring/revocable signed links, cross-entry and traversal denial) are tested against Home Assistant **2026.2.3** only (`ha_tests/`, see its README). No other version has been tested, and no minimum Home Assistant version is declared yet. Browser behaviour has not been verified in a real browser. Reverse proxies and Home Assistant access logging may record the `authSig` query of signed links; keep the `aiohttp.access` logger above INFO and redact `authSig` in proxy logs.

---

## 1. HACS Installation (Recommended)

[HACS](https://hacs.xyz/) supports this integration as a **custom GitHub repository**.
GitHub is a read-only mirror; issues and contributions remain on [GitLab](https://gitlab.com/opentasmania/junie-remote-lovelace-card).

**Prerequisites:** Home Assistant **2026.2.3** or newer (the tested minimum).
For Home Assistant **2026.11** and later, HACS is built in as **Settings > Marketplace**;
the standalone HACS integration is no longer available. For older versions, use standalone
[HACS](https://hacs.xyz/docs/use/download/prerequisites/).

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Enter `https://github.com/OpenTasmania/junie-remote-lovelace-card` as the URL.
3. Select **Integration** as the category and click **Add**.
4. Open the **Junie Remote** repository in HACS and click **Download**
   (the default branch version is installed; GitHub Releases are not yet published).
5. **Restart Home Assistant.** A metadata refresh alone does not install files.
6. Add and configure the integration as described in [Step 3–4](#3-authenticate-with-jetbrains-junie-remote).

This is a single integration package containing its compiled card—do not install the
card as a separate plugin.

### Updating via HACS

When a new version is available, HACS will show an update notification. Install the
update, then **restart Home Assistant** (a metadata refresh alone does not install files).
After restarting, fully reload each browser page so the updated card bundle is loaded.

**Version selection:** This repository uses the default branch for HACS updates.
A Git tag by itself is not a GitHub Release; release-based version selection in HACS
requires actual GitHub Releases, which are not yet published. To update, install the
latest from the default branch. If GitHub Releases are added in the future, HACS will
offer version selection automatically.

### Removing via HACS

1. Remove the integration config entry via **Settings → Devices & services**
   (transcripts are retained by default — see [Transcript Lifecycle](#6-transcript-lifecycle--opt-in-cleanup) for opt-in cleanup).
2. In HACS, open the **Junie Remote** repository and click **Remove**.
3. Remove any Junie Remote cards from your dashboards.
4. Restart Home Assistant if the static `/junie_remote/` route persists.

Reinstall by adding the custom repository again and following the installation steps above.

### Verification status

The HACS installation procedure is documented from the [HACS custom repositories
guide](https://www.hacs.xyz/docs/faq/custom_repositories/) and the [Marketplace
documentation](https://www.hacs.xyz/docs/marketplace/). End-to-end testing on a
disposable Home Assistant instance with HACS has not yet been performed: live browser
behavior, external S3-provider checks, and Marketplace (HA 2026.11+) compatibility
are unverified. Report gaps rather than assuming compatibility.

---

## 2. Manual Installation

### Clone the Repository & Verify the Frontend Bundle

Clone the repository onto your desktop computer:
```bash
git clone https://gitlab.com/opentasmania/junie-remote-lovelace-card.git
cd junie-remote-lovelace-card
```

The compiled Lovelace card bundle is already tracked in the repository at:
```text
custom_components/junie_remote/frontend/junie-remote-card.js
```

If you have modified any TypeScript files under `frontend/src/`, rebuild the bundle first:
```bash
npm --prefix frontend install
npm --prefix frontend run build
```

See [`frontend/BUILD.md`](frontend/BUILD.md) for staged publication, watch mode and recovery.

---

### Deploy or update without overlaying old files

Everything needed is in `custom_components/junie_remote/`, including the shipped
bundle. Back up HA and record storage settings securely first. For an update, keep
the existing entry: an entry reload, code replacement, entry removal and transcript
deletion are separate operations. Stop HA if your installation permits it; otherwise
avoid using the integration during replacement and restart immediately afterwards.

Choose a trusted, complete checkout of the intended release. From its root, inspect
`find custom_components/junie_remote -type l -print`: stop if any symlinks are found.
Inspect the source directory for unintended local files, caches or secrets before
copying: these commands transfer its complete contents, including hidden files.
The examples require `tar`, `find`, `sha256sum`, `sort`, `cp` and `mv`; adapt them
to your host, permissions and filesystem. Run one deployment at a time. Stage and
backup must be on the same filesystem as `custom_components`; do not follow a
symlinked stage, backup or destination. The named stage and backup must not exist;
choose new names rather than overwriting a previous backup. Commands stop on errors;
inspect and preserve a failed stage for diagnosis. Check that the HA user can read
the staged files and traverse their directories before promotion.

### A. SSH from the checkout

Run in Bash on the desktop, replacing the host. This creates a fresh stage, transfers
the whole integration, and checks every regular file against the checkout:

```bash
set -euo pipefail
HA=root@homeassistant.local
ssh "$HA" 'set -eu; test ! -e /config/junie-remote-stage; test ! -L /config/junie-remote-stage; test ! -e /config/junie-remote-backup; test ! -L /config/junie-remote-backup; test ! -L /config/custom_components; test ! -L /config/custom_components/junie_remote; mkdir -p /config/custom_components; mkdir /config/junie-remote-stage'
tar -C custom_components -cf - junie_remote | ssh "$HA" 'tar -xf - -C /config/junie-remote-stage'
(cd custom_components/junie_remote && find . -type f -exec sha256sum {} \; | LC_ALL=C sort) | ssh "$HA" 'cd /config/junie-remote-stage/junie_remote && sha256sum -c -'
```

Stop if transfer or verification fails. Check the stage for symlinks and permissions
on the HA host. Then run the **promotion** block below on that host via its terminal
or `ssh "$HA"`; do not start a fresh copy first.

### B. Mounted share or local HA container

From the checkout on the machine with the mounted `/config` (replace the path):

```bash
set -euo pipefail
CONFIG=/mnt/homeassistant/config
test ! -e "$CONFIG/junie-remote-stage"
test ! -L "$CONFIG/junie-remote-stage"
test ! -e "$CONFIG/junie-remote-backup"
test ! -L "$CONFIG/junie-remote-backup"
test ! -L "$CONFIG/custom_components"
test ! -L "$CONFIG/custom_components/junie_remote"
mkdir -p "$CONFIG/custom_components"
mkdir "$CONFIG/junie-remote-stage"
cp -a custom_components/junie_remote "$CONFIG/junie-remote-stage/"
(cd custom_components/junie_remote && find . -type f -exec sha256sum {} \; | LC_ALL=C sort) | (cd "$CONFIG/junie-remote-stage/junie_remote" && sha256sum -c -)
```

Check stage symlinks and permissions, then use the promotion block with the same
`CONFIG`. Use a filesystem that supports same-filesystem directory renames; if a
network share does not, stop and use the HA host's local terminal instead.

### C. Checkout on the HA host

In Terminal & SSH, clone into a **new**, operator-chosen directory, for example
`/config/junie-remote-checkout`, and select the intended release:

```bash
test ! -e /config/junie-remote-checkout || exit 1
test ! -L /config/junie-remote-checkout || exit 1
git clone https://gitlab.com/opentasmania/junie-remote-lovelace-card.git /config/junie-remote-checkout
cd /config/junie-remote-checkout
```

After selecting and inspecting the intended release and checking for symlinks, use
the mounted-share block above with `CONFIG=/config`, then the promotion block. Keep
the checkout until you have verified the deployment; do not recursively delete it
without checking its contents.

### Promotion and rollback (all methods)

Run on the host or mounted share, using the same `CONFIG` as above (`/config` for
SSH and HA-host deployments). Confirm the destination is the intended integration,
the backup is still absent, and no other deployment is running. This moves the old
directory aside instead of overlaying it; a failed promotion restores it when one
existed. Do not restart HA if restoration fails.

```bash
set -eu
CONFIG=/config  # change to /mnt/homeassistant/config for the mounted-share example
test -d "$CONFIG/junie-remote-stage/junie_remote"
test ! -L "$CONFIG/junie-remote-stage"
test ! -L "$CONFIG/junie-remote-stage/junie_remote"
test ! -e "$CONFIG/junie-remote-backup"
test ! -L "$CONFIG/junie-remote-backup"
test ! -L "$CONFIG/custom_components"
test ! -L "$CONFIG/custom_components/junie_remote"
if [ -e "$CONFIG/custom_components/junie_remote" ]; then
  test -d "$CONFIG/custom_components/junie_remote"
  mv "$CONFIG/custom_components/junie_remote" "$CONFIG/junie-remote-backup"
fi
if ! mv "$CONFIG/junie-remote-stage/junie_remote" "$CONFIG/custom_components/junie_remote"; then
  if [ -d "$CONFIG/junie-remote-backup" ]; then
    mv "$CONFIG/junie-remote-backup" "$CONFIG/custom_components/junie_remote" || { printf '%s\n' 'Restore failed; stop and recover manually'; exit 1; }
  fi
  exit 1
fi
```

Restart HA and fully reload browsers as described below. Keep the backup until the
integration, cards and active tunnel work. To roll back, stop HA, move the failed
new `custom_components/junie_remote` to a new, absent quarantine path, move the
backup back to `custom_components/junie_remote`, and restart. If either move fails,
stop and recover from the HA backup; never overwrite another directory. An initial
install has no old directory to restore. Review and remove only your own stage,
quarantine and backup after verification; they can contain sensitive configuration.

---

### Restart Home Assistant

After copying `custom_components/junie_remote/` into `/config/custom_components/junie_remote/`:
1. If HA was stopped, start it. Otherwise, in Home Assistant, go to **Developer Tools** $\rightarrow$ **YAML** $\rightarrow$ click **Restart** $\rightarrow$ **Restart Home Assistant**.
2. When `junie_remote` is set up, it serves the Lovelace card at `/junie_remote/junie-remote-card.js`. In storage resource mode it registers a module URL with a content-derived `?v=` value, and updates only its own unmodified resource when the bundle changes. Existing unowned or modified card resources are retained without adding a duplicate; check the logs and manage them manually. If no resource store exists, the integration checks the dashboard first; legacy dashboard resources or an unreadable dashboard require manual review. YAML resources must be configured manually.

After updating, fully reload each open browser page: an already registered custom element is not replaced in place. If an old card persists, check the resource URL and browser network/cache, then use a hard reload or clear the relevant browser cache. For a manually managed `/local/junie-remote-card.js` resource, update the file yourself and change its version query when its bytes change. Do not edit the integration's ownership records or add version queries to signed transcript URLs.

If `/config/www` exists, the integration also attempts to maintain an optional
`/local/junie-remote-card.js` fallback. It never adopts a pre-existing, manually
modified, or symlinked fallback. If you use that older URL, inspect and update
the file yourself from the shipped bundle; otherwise use the integration's
`/junie_remote/junie-remote-card.js` resource instead. A warning about atomic
exchange can mean that the `/config/www` filesystem does not support Linux
`renameat2` exchange (for example, some network mounts), or that `/proc/self/fd`
is unavailable. The old file is preserved and a later restart can retry;
on unsupported systems, maintain the fallback manually if you need it. Do not
edit ownership records to force an update.

Home Assistant only serves `/local/` if `/config/www` existed when it started.
If you deliberately create it for the first time for the optional fallback or to
inspect legacy files, restart HA once afterwards and fully reload the browser.
An existing `www` directory or a new subdirectory needs no such restart. New
private transcripts use the authenticated API, not `/local/`; this restart does
not fix their authentication errors. For an unavailable fallback, check the exact
resource URL, file permissions and browser response before restarting again. See
[HA hosting files](https://www.home-assistant.io/integrations/http#hosting-files).

### Managing resources in YAML

Resource mode is independent of dashboard mode. The integration does not create or
update YAML resources. Do not switch a UI-managed installation to YAML casually:
that changes management of **all** resources. For an existing YAML-managed setup,
merge one entry into the existing `lovelace` configuration, preserving all other
resources and dashboards:

```yaml
lovelace:
  resource_mode: yaml
  resources:
    - url: /junie_remote/junie-remote-card.js?v=REPLACE_WITH_BUNDLE_SHA256
      type: module
```

Calculate the SHA-256 of `/config/custom_components/junie_remote/frontend/junie-remote-card.js`
with `sha256sum` on the HA host and replace the placeholder with its hex digest.
Update this manually after each bundle change. Before adding it, remove only the
Junie resource you intend to replace, including older query-string or
`/local/junie-remote-card.js` variants, so there is exactly one; preserve unrelated
resources. In storage mode the integration updates only a recorded, unmodified
resource; an existing legacy or manually modified URL is not adopted, so manage
that URL yourself rather than adding a duplicate. Consult HA logs for warnings.
Validate the YAML and use the administrator action `lovelace.reload_resources`
where available, or restart HA; then fully reload each browser. This action is for
YAML resource mode, not UI-managed resources. See [HA dashboard configuration](https://www.home-assistant.io/dashboards/dashboards/)
and [reload resources](https://www.home-assistant.io/actions/lovelace.reload_resources/).

---

## 3. Authenticate with JetBrains Junie Remote

When you add the integration, you'll be presented with two authentication options:

### Option 1: JBA Web Login
This is an assisted link to the JetBrains Account page, not automatic login or cookie capture. Sign in in a trusted browser and paste the cookies as below.

### Option 2: Manual Cookie Input
Select **Manual Cookie Input** to paste your session cookies from the browser:

1. Open [Junie Remote](https://junie.jetbrains.com/remote/) in your browser and sign in.
2. Press `F12` (or `Ctrl+Shift+I`) to open **Developer Tools** and select the **Application** tab.
3. Go to **Cookies** → `junie.jetbrains.com`.
4. Copy the values for `SESSION` and `XSRF-TOKEN`.
5. Paste them as: `SESSION=your_session; XSRF-TOKEN=your_token`

**Required cookies:** `SESSION`, `XSRF-TOKEN` (and optionally `JBA`).

---

## 4. Add the Integration in Home Assistant

1. In Home Assistant, go to **Settings** $\rightarrow$ **Devices & services** $\rightarrow$ **+ Add Integration**.
2. Search for **JetBrains Junie Remote** and select it.
3. **Step 1 — Authentication Method**:
   - Both **JBA Web Login** and **Manual Cookie Input** require you to paste cookies manually.
   - Follow the prompts for your chosen method.
   - The integration verifies connectivity against `/api/public/cli/tunnel/tunnels`.
4. **Step 2 — Transcript Storage**:
   - Read the security warning shown on this step (it repeats the notice at the top of this guide).
   - **Storage Type**:
     - Choose **`local`** to store transcripts privately under `/config/junie_remote/transcripts/` (default) or a custom path that is **outside** `/config/www`. They are served only to Home Assistant administrators through an authenticated endpoint, never at `/local/`.
     - Or choose **`s3`** and enter your S3-compatible bucket, endpoint URL (e.g., MinIO/Garage/Ceph/AWS), region, access key, and secret key. Review the bucket policy and any public base URL first.
   - Click **Submit**.

### Credential recovery

A Junie API HTTP 401 may mean the session expired; DNS, TLS, timeout or network
errors are connectivity problems, and an S3 browser download failure is separate.
An empty tunnel list alone is not an authentication failure. The integration
currently does **not** automatically start an HA reauth flow on a 401. A reauth
form exists but writes entry data while non-empty options credentials take
precedence, so a stale options value can override it. Use the existing entry's
options instead:

1. Sign in to [Junie Remote](https://junie.jetbrains.com/remote/) in a trusted
   browser and copy fresh `SESSION` and `XSRF-TOKEN` using the cookie steps above.
2. In **Settings → Devices & services → JetBrains Junie Remote**, open the
   existing entry's **Configure** options. Replace the authentication field;
   preserve and check all storage settings, especially a legacy public path that
   is deliberately replaced by the private default in the form. Submit.
3. Changed non-empty credentials are tested using `list_tunnels`: a 401 is
   reported as invalid authentication, network failure as cannot connect. The
   options update reloads a loaded entry; check logs and, with an active CLI
   tunnel, confirm reconnection and the expected entity status. An empty successful
   list is valid. If the entry was not loaded, retry setup/reload after saving.

Options credentials override entry data at runtime; leaving the field empty falls
back to entry data rather than clearing it. The form does not revalidate unchanged
credentials. If the options action or reload fails, retain the entry and investigate
logs; do not edit `.storage`. As a last resort, back up and securely record storage
settings before removing and re-adding the entry: entity IDs/cards can change and
the new entry will not adopt old transcript ownership. See [uninstall and retention](#update-recovery-and-uninstall).
Never paste cookies, storage-state JSON, S3 keys or signed URLs into issues, logs,
screenshots or shared backups. Review JetBrains account session/security controls
for revocation; no specific account-side revocation action has been verified here.
For HA's general mechanism see [reauthentication guidance](https://contributors.home-assistant.io/core/integrations/reauth-reconfigure).

### S3 networking and CORS

The form accepts an endpoint, bucket (the only explicitly required S3 field),
region (default `us-east-1`), access/secret keys, and an optional public URL base.
HA uploads via its configured S3 client; the browser independently GETs the
resulting URL. Ensure the browser can resolve and reach its host, with valid TLS;
an HTTPS dashboard must not fetch HTTP mixed content. Use a least-privilege S3
principal and private objects where possible. With no public base, each successful
save generates presigned GET URLs with a one-hour requested expiry; signing
credentials or provider policy may expire or revoke them sooner. The URL is not
automatically renewed merely by reloading the browser: a subsequent successful
transcript save produces a new URL. A configured public base is used instead of
presigning, with the key appended; its CDN/bucket policy may expose transcripts.
Do not append cache parameters to signed URLs or share them.

Cross-origin browser GETs need provider/CDN CORS for the exact HA origin (scheme,
host and non-default port, no path). For example, adapt this AWS S3 bucket CORS
configuration to your trusted origin and provider:

```json
[
  {"AllowedOrigins": ["https://ha.example.com:8123"], "AllowedMethods": ["GET"]}
]
```

Add only needed headers if your provider requires preflight. CORS is not object
authorization; never make a bucket public merely to fix it. In browser Network
tools, check destination, status and CORS response without sharing credentials or
transcript content: distinguish DNS/TLS and mixed-content failures from missing
CORS, 403/access policy or expired signatures. Check HA upload logs separately,
and CDN caching for stale successful responses. A new transcript save can issue a
fresh URL if credentials remain valid; there is no independent refresh action.
See [AWS S3 CORS](https://docs.aws.amazon.com/AmazonS3/latest/userguide/ManageCorsUsing.html)
and [presigned URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html).
Actual browser and external-provider behavior has not been verified here.

---

## 5. Start Junie CLI Remote on Your Host(s) & Add Lovelace Cards

1. On any workstation or server where Junie CLI is installed, start a remote-enabled session inside your project directory:
   ```bash
   junie --remote
   ```
   *(Or enable remote tunnel mode inside Junie CLI).*
2. Within 10 seconds, the Home Assistant coordinator auto-discovers the tunnel and creates a stable device & entities for that `(user, OS, repo/directory)`:
   - `sensor.<host>_status`
   - `switch.<host>_brave_mode`
   - `select.<host>_model_effort`
   - `button.<host>_stop`, `button.<host>_confirm_plan`, `button.<host>_take_over`
3. Open any Home Assistant Dashboard $\rightarrow$ click **Edit Dashboard** (pencil icon) $\rightarrow$ **+ Add Card**:
   - Search for **Junie Remote Card** in the card picker (the visual editor automatically lists all discovered `sensor.*_status` entities), **or** click **Manual** and enter:
     ```yaml
     type: custom:junie-remote-card
     entity: sensor.alice_linux_my_repo_status
     title: Workstation — my-repo
     max_height: 560px
     ```
4. Add additional **Junie Remote Cards** for each host/project you want to monitor and control simultaneously.

---

## 6. Transcript Lifecycle & Opt-In Cleanup

### Update, recovery and uninstall

1. Back up HA and record the entry's storage type, private/custom local path or S3
   endpoint, bucket and prefix securely. Review which entries and other users share
   these locations. A reload or code update does not remove the entry or its data.
2. **Retain:** simply remove the entry through **Settings → Devices & services**;
   transcripts are retained. **Delete selected owned data:** while the entry still
   exists, call the admin-only cleanup action below with explicit confirmation; wait
   for completion and review any reported partial failure before removing it.
   Cleanup pauses writes persistently; retry failures or resume explicitly if keeping
   the entry. It does not delete legacy, unowned, shared or ambiguous data.
3. Remove any remaining entries through HA before removing component files; disabled
   entries still count. Only after no other entry uses this integration, stop HA,
   move `/config/custom_components/junie_remote` to a new, absent backup location,
   and restart HA. Keep the backup until recovery is no longer needed. Reinstall by
   deploying a release and adding a new entry; old transcripts are retained but are
   not automatically adopted by the new entry. Do not edit HA `.storage` files.
4. Remove unwanted dashboard cards and manual UI/YAML resources yourself. Inspect
   legacy `/config/www/junie_remote`, custom paths and S3 `junie_remote/` objects
   individually, along with versions, delete markers, backups, snapshots and recorder
   history. Remove only positively identified objects after checking other users;
   never recursively delete a custom directory, all `www`, a shared prefix or bucket.
   Review the JetBrains account's available session/security controls for revocation.

- **Shared card artifacts:** Removing the final config entry attempts to remove only the
  integration-owned, unmodified storage-mode Lovelace resource and optional
  `/config/www/junie-remote-card.js` fallback. Other configured entries, including
  disabled ones, keep both artifacts. Reloading does not remove them. User-modified,
  legacy, ambiguous and YAML-managed resources or files are retained; check the Home
  Assistant logs for failures or manual-review warnings. If removal was interrupted,
  ownership may be ambiguous and the file or a `.junie-remote-cleanup-*` quarantine
  may require manual review. Once the cause is resolved, reinstall and remove a config
  entry to retry any still-recorded cleanup; never edit ownership records.
- **Manual dashboard cleanup:** Removing the integration does not delete dashboard
  card configurations. Remove Junie cards through each dashboard's editor; remove
  manually configured resources through **Settings → Dashboards → Resources**, or
  from your YAML configuration if YAML-managed. Inspect and remove any unwanted
  manually maintained `/config/www/junie-remote-card.js` yourself. Restart as needed;
  the static HTTP route may remain registered until Home Assistant restarts.
- **Retention by default:** Routine reloads, restarts, and removing a config entry (or uninstalling the integration) retain all local transcripts and S3 objects by default.
- **Opt-in cleanup before removal:** If you want to delete transcript data created by a config entry, call the `junie_remote.cleanup_transcripts` service **before** removing the entry (under **Developer Tools** $\rightarrow$ **Actions / Services** as an **Administrator**):
  ```yaml
  action: junie_remote.cleanup_transcripts
  data:
    entry_id: "YOUR_CONFIG_ENTRY_ID"
    confirm: true
  ```
  To find the ID, use **Developer Tools → Template** and evaluate
  `{{ config_entry_id('sensor.YOUR_JUNIE_REMOTE_SENSOR') }}` using an entity from the entry.
- **Guarded pause & inventory checks:** Cleanup persistently pauses new writes for that entry across restarts, drains a registered coordinator when present, then serializes with local saves before taking the ownership snapshot. This also covers first-refresh saves made before coordinator registration. Only recorded inventory entries are considered. Local files are quarantined in a verified (non-symlink) directory and removed only if the SHA-256 digest still matches. Unproven files, symlinks, modified files, and unrelated files are preserved with partial failure reported for manual review. A failed or interrupted cleanup can leave a `.junie-remote-cleanup-*` file; its path is reported on retry, and it must be reviewed manually before retrying cleanup.
- **Resuming writes:** If you decide to keep the entry after pausing or cleaning up, call `junie_remote.resume_transcripts` with `entry_id: "YOUR_CONFIG_ENTRY_ID"` (Administrator only) to unpause writes. Cleanup and resume for the same entry are serialized.
- **Limits and manual review:**
  - **Local concurrency:** Integration saves and cleanup share a per-entry lock, and the private entry directory limits ordinary access. Processes with write access to the HA configuration filesystem (for example, the HA user or root) can still alter files; cleanup re-checks identity and digest after quarantine and retains mismatches for manual review.
  - **S3 identity:** Cleanup deletes only recorded non-`null` immutable `VersionId`s at the matching endpoint, and preserves keys also recorded by another entry. Deleting a version permanently removes that version and does **not** create a delete marker. Unversioned objects, including `VersionId: null` from suspended versioning, are always retained for manual review: some providers silently ignore conditional `IfMatch` deletes. S3 ETags are not content digests — multipart uploads in particular produce ETags that are not a SHA-256 of the bytes.
  - **S3 version retention:** The inventory keeps only the most recently recorded version for each endpoint, bucket, and key. Earlier versions fall out of the ownership inventory and are retained in the bucket for manual review or an S3 lifecycle policy; versions and delete markers never recorded by this integration are likewise not owned or deleted.
  - **Backups & Snapshots:** Home Assistant backups and filesystem snapshots containing transcript copies are not modified.
  - **Recorder History:** State attributes previously recorded in the database remain until purged by your recorder retention settings.
