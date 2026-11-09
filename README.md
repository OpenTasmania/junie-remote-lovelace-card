<!--
SPDX-License-Identifier: MIT
Copyright (c) 2026 Peter Lawler
-->

# Junie Remote Lovelace Card & Home Assistant Integration

A Home Assistant custom integration (`junie_remote`) and Lovelace custom card (`junie-remote-card`) that bridges [JetBrains Junie Remote](https://junie.jetbrains.com/remote/) into Home Assistant.

Handcrafted with ❤️ & [Junie](https://junie.jetbrains.com).

## Overview

- **Home Assistant Statebridge (`custom_components/junie_remote`)**:
  - Authenticates with JetBrains Account session state (`Cookie` + `X-XSRF-TOKEN`).
  - Auto-discovers active Junie CLI remote tunnels (`/api/public/cli/tunnel/tunnels`) and binds them to stable Home Assistant devices per `(userName, osName, workingDir / gitRepoUrl)`.
  - Connects directly to Junie CLI tunnels via PKCE S256 WebSocket handshake (`/api/public/cli/tunnel/tunnels/:tunnelId/client/connect`).
  - Streams long textual agent transcripts, code blocks, diffs, and plan proposals to **Private Local Storage** (`/config/junie_remote/transcripts/` or a custom path outside `/config/www`; served only to Home Assistant administrators — see the security notice in `INSTALL.md`) or **S3-Compatible Object Storage**.
- **Lovelace Custom Card (`frontend/` -> `custom_components/junie_remote/frontend/junie-remote-card.js`)**:
  - Multi-host support via multiple cards bound to discovered Junie host devices.
  - Displays live session status, Git repo/branch/working directory metadata, and full Markdown/code transcripts fetched from Local or S3 storage.
  - Renders structured transcript details when present, including response prompts, step descriptions, system-message details, skill changes, and result errors or cancellations.
  - Interactive controls for **Prompt / Steer / Plan Refinement** text input, **Stop / Cancel**, **Brave Mode** toggle, **Model & Effort** selector, **Plan Proposal** review/confirmation, and dynamic **Interactive Requests** (`ask`, `choice`, `approve`, `action`, `ask-async`).
  - Disables remote session controls while the Home Assistant connection status is not `connected` (except the takeover action when shown), and shows transcript-fetch or service-call failures in the card.

Automated frontend fixtures cover these documented transcript fields and control states. Confirm live parity and interaction behavior in Home Assistant after deployment; a disposable Junie session has not yet been used for end-to-end validation.

## Installation

### HACS (Recommended)

[HACS](https://hacs.xyz/) supports this integration as a **custom GitHub repository**.
GitHub is a read-only mirror; issues and contributions remain on [GitLab](https://gitlab.com/opentasmania/junie-remote-lovelace-card).

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://hacs.xyz)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=OpenTasmania&repository=junie-remote-lovelace-card&category=integration)

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Enter `https://github.com/OpenTasmania/junie-remote-lovelace-card` as the URL.
3. Select **Integration** as the category and click **Add**.
4. Open the **Junie Remote** repository in HACS and click **Download**
   (the default branch version is installed; GitHub Releases are not yet published).
5. **Restart Home Assistant** (a metadata refresh alone does not install files).
6. Add and configure the integration: **Settings** → **Devices & services** → **+ Add Integration** → **JetBrains Junie Remote**.

> For Home Assistant **2026.11** and later, HACS is built in as **Settings > Marketplace**.
> This is a single integration package containing its compiled card — do not install the card as a separate plugin.

### Updating via HACS

When a new version is available, HACS will show an update notification. Install the update,
then **restart Home Assistant** (a metadata refresh alone does not install files). After
restarting, fully reload each browser page so the updated card bundle is loaded.

### Removing via HACS

1. Remove the integration config entry via **Settings → Devices & services**
   (transcripts are retained by default — see [`INSTALL.md`](INSTALL.md#transcript-lifecycle--opt-in-cleanup) for opt-in cleanup).
2. In HACS, open the **Junie Remote** repository and click **Remove**.
3. Remove any Junie Remote cards from your dashboards.
4. Restart Home Assistant if the static `/junie_remote/` route persists.

Reinstall by adding the custom repository again and following the installation steps above.

### Manual Installation

See [`INSTALL.md`](INSTALL.md) for detailed instructions covering all installation methods:

- **HACS** (full details, including version selection and updates)
- **Manual deployment** (SSH, mounted share, or HA-host checkout with verification)
- **Configuration** (authentication, transcript storage, S3 setup)
- **Safe updates, recovery, and uninstall**
- **Credential recovery**
- **YAML resources** and **S3 networking and CORS**

**Minimum Home Assistant version:** 2026.2.3 (tested).

## Protocol & Architecture Documentation

See [`docs/JUNIE_REMOTE_PROTOCOL.md`](docs/JUNIE_REMOTE_PROTOCOL.md) for the complete reverse-engineered REST API, PKCE S256 WebSocket handshake, event schemas, and Home Assistant Statebridge storage specification.

