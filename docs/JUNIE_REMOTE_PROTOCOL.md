<!--
SPDX-License-Identifier: MIT
Copyright (c) 2026 Peter Lawler
-->

# JetBrains Junie Remote — Protocol & Architecture Reference

This document specifies the reverse-engineered protocol used by `https://junie.jetbrains.com/remote/` and the architecture for bridging Junie CLI remote sessions into Home Assistant via the `junie_remote` custom integration and `junie-remote-card` Lovelace card.

---

## 1. Authentication & CSRF (`call-api`)

- **Base Origin**: `https://junie.jetbrains.com`
- **API Base Path**: `/api/public`
- **OAuth Login Endpoints**:
  - `/api/public/portal/login/oauth2/authorization/jba?redirectPath=http%3A%2F%2Fjunie.jetbrains.com%2Fremote%2F&via_provider=<provider>`
  - Supported `via_provider` values: omitted (JetBrains Account), `google`, `github`, `apple`, `gitlab`, `bitbucket`, `wechat`.
- **Cookie + CSRF Token Header**:
  - Authenticated requests rely on the browser session cookies plus a CSRF header derived from the `XSRF-TOKEN` cookie:
    ```http
    Cookie: XSRF-TOKEN=<url_encoded_token>; <session_cookies...>
    X-XSRF-TOKEN: <url_decoded_token>
    ```
  - All `POST` requests with parameters send `Content-Type: application/json` and a JSON-serialized body.
  - Non-`POST` requests with parameters append them as URL query parameters.
  - A Junie API HTTP `401` indicates an expired or unauthenticated session. The integration does not automatically start reauthentication on a 401; see [credential recovery](../INSTALL.md#credential-recovery) for the existing-entry options path and its limitations. Connectivity and S3 download errors are separate.

---

## 2. REST API Endpoints (`/api/public/...`)

### 2.1 List Active Remote Tunnels
- **Request**: `GET /api/public/cli/tunnel/tunnels`
- **Polling Interval**: Every `3000ms` in the web UI (`10000ms` in the Home Assistant coordinator).
- **Response (`200 OK`)**:
  ```json
  [
    {
      "tunnelId": "c7b3d1e0-1234-4567-89ab-cdef01234567",
      "connectedClients": 0,
      "metadata": {
        "currentDirectory": "/home/user/projects/my-repo",
        "userName": "user",
        "osName": "Linux",
        "createdAt": "2026-11-07T00:00:00Z",
        "gitRepoUrl": "git@github.com:org/my-repo.git",
        "gitBranch": "master"
      }
    }
  ]
  ```

### 2.2 Get Single Tunnel Metadata
- **Request**: `GET /api/public/cli/tunnel/tunnels/{tunnelId}`
- **Response**:
  - `200 OK`: Single tunnel object (same schema as above).
  - `404 Not Found`: Tunnel has disconnected or expired.

### 2.3 Connect Client to Tunnel (PKCE Handshake)
- **Request**: `POST /api/public/cli/tunnel/tunnels/{tunnelId}/client/connect`
- **Body**:
  ```json
  {
    "codeChallenge": "<base64url_no_padding(sha256(codeVerifier))>",
    "codeChallengeMethod": "S256"
  }
  ```
- **Response**:
  - `200 OK`:
    ```json
    {
      "wsUrl": "https://junie.jetbrains.com/..."
    }
    ```
  - `404 Not Found`: Tunnel not yet available or disconnected.
  - `409 Conflict`: Another web client is already connected (`rejected` state).

### 2.4 Kick Existing Client ("Disconnect & Take Over")
- **Request**: `POST /api/public/cli/tunnel/tunnels/{tunnelId}/kick-client`
- **Body**: `{}`
- **Behavior**: Disconnects the currently attached web client with WebSocket close reason `"client-kicked"`. After kicking, wait ~`500ms` before calling `/client/connect`.

### 2.5 CLI Token Management
- **Create Token**: `POST /api/public/cli/tokens` with body `{"name": "<token_name>"}`
- **Delete Token**: `DELETE /api/public/cli/tokens/{id}`

---

## 3. PKCE S256 WebSocket Bridge Protocol

### 3.1 PKCE Code Verifier & Challenge Generation
1. Generate 32 cryptographically random bytes:
   `code_verifier = base64url_encode(random_bytes(32)).rstrip("=")`
2. Compute SHA-256 digest over ASCII bytes of `code_verifier`:
   `code_challenge = base64url_encode(sha256(code_verifier.encode("ascii"))).rstrip("=")`

### 3.2 WebSocket Connection & Handshake
1. Rewrite the scheme of `wsUrl` returned by `/client/connect`:
   - `https://` $\rightarrow$ `wss://`
   - `http://` $\rightarrow$ `ws://`
2. Append `code_verifier` query parameter:
   `wss://...{ "?" or "&" }code_verifier=<code_verifier>`
3. On WebSocket open (`onopen`), immediately send:
   ```json
   {
     "type": "client-connected",
     "requestId": "<uuid4>"
   }
   ```
4. Start a `20000ms` handshake timer. Wait for the first server frame with `"type": "agent-ready"`:
   ```json
   {
     "type": "agent-ready",
     "requestId": "<uuid4>",
     "tunnelId": "<tunnelId>"
   }
   ```
   If `"agent-ready"` is not received within `20000ms`, close the WebSocket with code `4000` and reason `"handshake-timeout"`.
5. If the WebSocket closes with `reason == "client-kicked"`, transition to `"kicked"` state and stop all reconnection attempts.

---

## 4. Incoming WebSocket Events (Server $\rightarrow$ Client)

All frames after `agent-ready` are JSON objects dispatched to the session state reducer:

### 4.1 `session-metadata`
```json
{
  "type": "session-metadata",
  "title": "Fix authentication bug",
  "gitBranch": "master",
  "workingDir": "/home/user/projects/my-repo"
}
```

### 4.2 `session-status`
```json
{
  "type": "session-status",
  "status": "idle",
  "canSendPrompt": true,
  "braveMode": false,
  "hasPlan": false,
  "seq": 4
}
```
- `status`: `"idle"` | `"working"` | `"waiting-for-input"`
- When `hasPlan` is `false`, any prior `planProposal` with `seq < session_status.seq` is cleared.

### 4.3 `brave-mode-state`
```json
{
  "type": "brave-mode-state",
  "enabled": true
}
```

### 4.4 `model-selection-state`
```json
{
  "type": "model-selection-state",
  "currentModelId": "claude-3-7-sonnet",
  "currentEffortId": "high",
  "models": [
    {
      "id": "claude-3-7-sonnet",
      "name": "Claude 3.7 Sonnet",
      "currentEffortId": "high",
      "supportedEfforts": [
        { "id": "low", "name": "Low" },
        { "id": "medium", "name": "Medium" },
        { "id": "high", "name": "High" }
      ]
    }
  ]
}
```
- Each selectable option is formatted as value `"${model.id}:${effort.id}"` and label `"${model.name} · ${effort.name}"`.

### 4.5 `ready-step` (Completed Conversation History Item)
```json
{
  "type": "ready-step",
  "step": {
    "type": "user-prompt | user-response | step | system-message | skills-status",
    "...": "..."
  }
}
```
Variants of `step`:
- `user-prompt`: `{ "type": "user-prompt", "prompt": "...", "presentablePrompt": "..." }`
- `user-response`: `{ "type": "user-response", "prompt": "..." }`
- `step`:
  - Intermediate step: `{ "type": "step", "vm": { "stepId": "...", "type": "...", "title": "...", "description": "..." } }`
  - Final result step (`vm.type === "result"`):
    ```json
    {
      "type": "step",
      "vm": {
        "stepId": "...",
        "type": "result",
        "cancelled": false,
        "errorCode": null,
        "text": "Markdown response text...",
        "changesSummary": [
          "M custom_components/junie_remote/client.py"
        ]
      }
    }
    ```
- `system-message`: `{ "type": "system-message", "level": "INFO | ERROR", "text": "...", "details": "..." }`
- `skills-status`: `{ "type": "skills-status", "newSkills": ["..."], "failedSkills": [{ "path": "..." }] }`

### 4.6 `progressing-steps`
```json
{
  "type": "progressing-steps",
  "steps": [
    {
      "stepId": "step-1",
      "type": "command",
      "title": "Running pytest"
    }
  ]
}
```

### 4.7 `plan-proposal`
```json
{
  "type": "plan-proposal",
  "seq": 5,
  "readyForReview": true,
  "showActions": true,
  "planFilePath": "/path/to/plan.md",
  "sections": [
    { "name": "Architecture", "content": "Markdown content..." }
  ],
  "deliverySteps": [
    { "name": "Implement client", "description": "Details..." }
  ]
}
```

### 4.8 `active-requests` (Interactive Prompts / Approvals)
```json
{
  "type": "active-requests",
  "requests": [
    {
      "requestId": "req-1",
      "type": "ask | choice | approve | action | ask-async"
    }
  ]
}
```
Request schemas:
1. **`ask`**: `{ "requestId": "...", "type": "ask", "question": "..." }`
2. **`choice`**: `{ "requestId": "...", "type": "choice", "title": "...", "options": [{ "id": "...", "title": "...", "description": "..." }] }`
3. **`approve`**: `{ "requestId": "...", "type": "approve", "title": "...", "options": [{ "type": "allow-once | always-allow | deny", "label": "...", "optionIndex": 0 }] }`
4. **`action`**: `{ "requestId": "...", "type": "action", "title": "..." }`
5. **`ask-async`**: `{ "requestId": "...", "type": "ask-async", "name": "...", "question": "...", "options": [{ "id": "...", "title": "...", "description": "..." }], "allowMultiple": false }`

---

## 5. Outgoing WebSocket Commands (Client $\rightarrow$ Server)

| Action | JSON Payload Sent over WebSocket |
|---|---|
| **Send Prompt / Steer** | `{"type": "prompt", "prompt": "<text>"}` |
| **Send Plan Refinement** | `{"type": "planPrompt", "prompt": "<text>"}` |
| **Confirm & Implement Plan** | `{"type": "confirmAndImplementPlan"}` |
| **Cancel / Stop Task** | `{"type": "cancel"}` |
| **Toggle Brave Mode** | `{"type": "toggleBraveMode", "enabled": true}` |
| **Select Model & Effort** | `{"type": "selectModel", "modelId": "<modelId>", "effortId": "<effortId>"}` |
| **Respond to `ask`** | `{"type": "response", "displayText": "<answer>", "response": {"method": "ask", "requestId": "<id>", "response": "<answer>"}}` |
| **Respond to `choice`** | `{"type": "response", "displayText": "<label>", "response": {"method": "choice", "requestId": "<id>", "optionId": "<optId>"}}` |
| **Respond to `approve` (allow-once)** | `{"type": "response", "displayText": "Allow once", "response": {"method": "approve", "requestId": "<id>", "approve": true}}` |
| **Respond to `approve` (always-allow)** | `{"type": "response", "displayText": "<label>", "response": {"method": "approve", "requestId": "<id>", "approve": true, "addToAllowList": true, "optionIndex": 0}}` |
| **Respond to `approve` (deny)** | `{"type": "response", "displayText": "Deny", "response": {"method": "approve", "requestId": "<id>", "approve": false}}` |
| **Respond to `action`** | `{"type": "response", "displayText": "OK", "response": {"method": "cancel", "requestId": "<id>"}}` |
| **Respond to `ask-async`** | `{"type": "response", "displayText": "<summary>", "response": {"method": "ask-async", "requestId": "<id>", "optionIds": ["..."], "response": "<text_or_null>"}}` |

---

## 6. Home Assistant Statebridge & Hybrid Transcript Storage Architecture

1. **Host Identity (`host_key`)**:
   - Because restarting `junie` CLI generates a new `tunnelId`, each host session is keyed by a deterministic slug of `(metadata.userName, metadata.osName, metadata.gitRepoUrl || metadata.currentDirectory)`.
   - When a new `tunnelId` appears for an existing `host_key`, the coordinator transparently rebinds the Home Assistant device/entities to the new tunnel.
2. **Hybrid Storage Driver (`LocalTranscriptStorage` & `S3TranscriptStorage`)**:
   - Home Assistant state strings are capped at 255 characters and state attributes should remain compact.
   - Full conversation transcripts (`history`, `progressing_steps`, `plan_proposal`, `active_requests`) are written as structured JSON (`latest.json`) and Markdown (`latest.md`) to either:
     - **Private Local Storage**: `/config/junie_remote/transcripts/<entry_id>/<host_slug>/latest.json` (served only to authenticated administrators via `/api/junie_remote/transcripts/<entry_id>/<host_key>/json?t=<ts>`; never via `/local/`)
     - **S3-Compatible Object Storage**: `s3://<bucket>/junie_remote/<host_slug>/latest.json` (accessed via a presigned `GET` URL or configured public base URL; see [S3 networking and CORS](../INSTALL.md#s3-networking-and-cors)).
3. **Lovelace Card (`<junie-remote-card>`)**:
   - Reads lightweight status, metadata, model options, and `transcript_json_url` from `sensor.<host>_status`.
   - Fetches the full transcript JSON from `transcript_json_url` whenever `transcript_updated_at` changes.
   - Dispatches user inputs, model selections, plan confirmations, and interactive request responses via `junie_remote` Home Assistant services.
