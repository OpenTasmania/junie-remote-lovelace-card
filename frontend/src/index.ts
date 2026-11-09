// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Peter Lawler

import { LitElement, html, css, PropertyValues, TemplateResult } from "lit";
import { property, state } from "lit/decorators.js";
import "./editor";
import { renderMarkdown, renderChangesSummary } from "./markdown";
import {
  HomeAssistant,
  JunieRemoteCardConfig,
  TranscriptDocument,
  ReadyStepItem,
  ProgressingStep,
  ActiveRequest,
  ActiveRequestOption,
  PlanProposal,
  PlanSummary,
} from "./types";

// Register custom card in Home Assistant custom card picker
declare global {
  interface Window {
    customCards?: Array<{
      type: string;
      name: string;
      description: string;
      preview?: boolean;
      documentationURL?: string;
    }>;
  }
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "junie-remote-card")) {
  window.customCards.push({
    type: "junie-remote-card",
    name: "Junie Remote Card",
    description:
      "Control JetBrains Junie CLI sessions from Home Assistant Lovelace. Reload the page after updating the card.",
    preview: true,
    documentationURL:
      "https://gitlab.com/opentasmania/junie-remote-lovelace-card",
  });
}

const LOCAL_TRANSCRIPT_PREFIX = "/api/junie_remote/transcripts/";

/** Local transcripts are served by an authenticated, admin-only HA view. */
function isLocalTranscriptUrl(url: string): boolean {
  return url.startsWith(LOCAL_TRANSCRIPT_PREFIX);
}

export class JunieRemoteCard extends LitElement {
  private _hass?: HomeAssistant;
  @property({ attribute: false })
  public get hass(): HomeAssistant | undefined {
    return this._hass;
  }
  public set hass(value: HomeAssistant | undefined) {
    const old = this._hass;
    this._hass = value;
    this._syncEntityAvailability();
    this.requestUpdate("hass", old);
  }
  @state() private _config?: JunieRemoteCardConfig;
  @state() private _transcript?: TranscriptDocument | null = null;
  @state() private _transcriptLoading: boolean = false;
  @state() private _transcriptError: string | null = null;
  @state() private _actionError: string | null = null;
  @state() private _showScrollBottom: boolean = false;
  @state() private _isKicking: boolean = false;
  @state() private _promptText: string = "";
  @state() private _inputMode: "normal" | "plan" = "normal";
  @state() private _isSending: boolean = false;
  @state() private _bravePending: boolean = false;
  @state() private _planViewMode: "summary" | "full" | "collapsed" = "summary";
  @state() private _selectedPlanSection: number | string = 0;
  @state() private _askInputs: Record<string, string> = {};
  @state() private _askAsyncSelections: Record<string, string[]> = {};
  @state() private _askAsyncInputs: Record<string, string> = {};

  private _lastFetchedUrl: string | null = null;
  private _lastFetchedUpdatedAt: string | null = null;
  private _transcriptRequestId: number = 0;
  private _entityGeneration: number = 0;
  private _renderedGeneration: number = -1;
  private _entityPresent: boolean = false;
  private _entityHasUrl: boolean = false;
  private _observedUrl: string | null = null;
  private _observedVersion: string | null = null;
  private _userScrolledUp: boolean = false;

  public static getConfigElement(): HTMLElement {
    return document.createElement("junie-remote-card-editor");
  }

  public static getStubConfig(hass?: HomeAssistant): JunieRemoteCardConfig {
    let entityId = "sensor.junie_remote_status";
    if (hass?.states) {
      for (const [id, stateObj] of Object.entries(hass.states)) {
        if (
          id.startsWith("sensor.") &&
          (stateObj.attributes?.host_key !== undefined ||
            stateObj.attributes?.tunnel_id !== undefined ||
            id.includes("junie"))
        ) {
          entityId = id;
          break;
        }
      }
    }
    return {
      type: "custom:junie-remote-card",
      entity: entityId,
    };
  }

  public setConfig(config: JunieRemoteCardConfig): void {
    if (!config) {
      throw new Error(
        "Invalid configuration: configuration object is required"
      );
    }
    if (!config.entity) {
      throw new Error("Invalid configuration: 'entity' is required");
    }
    if (this._config?.entity !== config.entity) {
      this._resetEntityState();
      this._entityPresent = false;
      this._entityHasUrl = false;
      this._observedUrl = null;
      this._observedVersion = null;
    }
    this._config = { ...config };
    this._syncEntityAvailability();
  }

  private _resetEntityState(): void {
    this._entityGeneration++;
    this._transcriptRequestId++;
    this._lastFetchedUrl = null;
    this._lastFetchedUpdatedAt = null;
    this._transcript = null;
    this._transcriptLoading = false;
    this._transcriptError = null;
    this._actionError = null;
    this._showScrollBottom = false;
    this._userScrolledUp = false;
    this._isKicking = false;
    this._promptText = "";
    this._inputMode = "normal";
    this._isSending = false;
    this._bravePending = false;
    this._planViewMode = "summary";
    this._selectedPlanSection = 0;
    this._askInputs = {};
    this._askAsyncSelections = {};
    this._askAsyncInputs = {};
    this.shadowRoot?.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(
      ".prompt-textarea, .ask-input, .ask-async-input"
    ).forEach((input) => {
      input.value = "";
    });
  }

  private _syncEntityAvailability(): void {
    const entity = this._config?.entity;
    const state = entity ? this._hass?.states?.[entity] : undefined;
    const present = Boolean(state);
    const url = state?.attributes?.transcript_json_url || null;
    const version = state?.attributes?.transcript_updated_at || null;
    const hasUrl = Boolean(url);
    if ((this._entityPresent && !present) || (this._entityHasUrl && !hasUrl)) {
      this._resetEntityState();
    } else if (
      this._entityHasUrl && hasUrl &&
      (url !== this._observedUrl || version !== this._observedVersion)
    ) {
      this._transcriptRequestId++;
      this._lastFetchedUrl = null;
      this._lastFetchedUpdatedAt = null;
      this._transcriptLoading = false;
    }
    this._entityPresent = present;
    this._entityHasUrl = hasUrl;
    this._observedUrl = url;
    this._observedVersion = version;
  }

  public getCardSize(): number {
    return 6;
  }

  protected willUpdate(changedProperties: PropertyValues): void {
    super.willUpdate(changedProperties);

    if (changedProperties.has("hass") || changedProperties.has("_config")) {
      this._checkTranscriptUpdate();
    }
  }

  protected firstUpdated(changedProperties: PropertyValues): void {
    super.firstUpdated(changedProperties);
    for (const type of ["click", "input", "change", "keydown"]) {
      this.renderRoot.addEventListener(type, (event: Event) => {
        if (this._renderedGeneration === this._entityGeneration) return;
        const target = event.target;
        if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
          target.value = "";
        }
        event.preventDefault();
        event.stopImmediatePropagation();
      }, true);
    }
  }

  protected updated(changedProperties: PropertyValues): void {
    super.updated(changedProperties);
    this._renderedGeneration = this._entityGeneration;

    // Handle sticky auto-scroll to bottom if user has not scrolled up
    if (!this._userScrolledUp) {
      this._scrollToBottom(false);
    }
  }

  private _checkTranscriptUpdate(): void {
    if (!this.hass || !this._config?.entity) {
      return;
    }
    const stateObj = this.hass.states[this._config.entity];
    if (!stateObj) {
      return;
    }

    const attrs = stateObj.attributes || {};
    const url = attrs.transcript_json_url;
    const updatedAt = attrs.transcript_updated_at || null;

    if (!url) {
      return;
    }

    if (url !== this._lastFetchedUrl || updatedAt !== this._lastFetchedUpdatedAt) {
      this._lastFetchedUrl = url;
      this._lastFetchedUpdatedAt = updatedAt;
      this._fetchTranscript(url, ++this._transcriptRequestId);
    }
  }

  private _fetchLocalTranscript(url: string): Promise<Response> {
    const fetchWithAuth = this.hass?.fetchWithAuth;
    if (typeof fetchWithAuth !== "function") {
      return Promise.reject(
        new Error("Home Assistant authenticated fetch is unavailable")
      );
    }
    return fetchWithAuth.call(this.hass, url, { cache: "no-store" });
  }

  private async _downloadTranscript(format: "json" | "md"): Promise<void> {
    const entity = this._config?.entity;
    const attrs = entity ? this.hass?.states?.[entity]?.attributes : undefined;
    const url = format === "json"
      ? attrs?.transcript_json_url
      : attrs?.transcript_md_url;
    if (!this.hass || !url) {
      return;
    }
    const generation = this._entityGeneration;
    this._actionError = null;
    try {
      let target = url;
      if (isLocalTranscriptUrl(url)) {
        // Short-lived signed link, requested on demand and never stored.
        const path = `${url}${url.includes("?") ? "&" : "?"}download=1`;
        if (typeof this.hass.callWS !== "function") {
          throw new Error("Home Assistant WebSocket signing is unavailable");
        }
        const signed: { path: string } = await this.hass.callWS({
          type: "auth/sign_path",
          path,
          expires: 30,
        });
        if (generation !== this._entityGeneration) {
          return;
        }
        target = signed.path;
      }
      const link = document.createElement("a");
      link.href = target;
      link.rel = "noopener noreferrer";
      link.target = "_blank";
      link.download = "";
      link.click();
    } catch (err) {
      if (generation === this._entityGeneration) {
        this._actionError = err instanceof Error ? err.message : String(err);
      }
    }
  }

  private async _fetchTranscript(url: string, requestId: number): Promise<void> {
    const generation = this._entityGeneration;
    this._transcriptLoading = true;
    this._transcriptError = null;
    try {
      const local = isLocalTranscriptUrl(url);
      const resp = local
        ? await this._fetchLocalTranscript(url)
        : await fetch(url, { cache: "no-store" });
      if (!resp.ok) {
        if (local && resp.status === 403) {
          throw new Error(
            "Administrator access is required to view local transcripts"
          );
        }
        throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
      }
      const data: TranscriptDocument = await resp.json();
      if (generation !== this._entityGeneration || requestId !== this._transcriptRequestId) {
        return;
      }
      this._transcript = data;

      // When new transcript arrives, notify user if scrolled up
      if (this._userScrolledUp) {
        this._showScrollBottom = true;
      }
    } catch (err: any) {
      if (generation === this._entityGeneration && requestId === this._transcriptRequestId) {
        this._transcriptError = err?.message || String(err);
        this._lastFetchedUrl = null;
        this._lastFetchedUpdatedAt = null;
      }
    } finally {
      if (generation === this._entityGeneration && requestId === this._transcriptRequestId) {
        this._transcriptLoading = false;
      }
    }
  }

  private async _executeService(
    service: string,
    serviceData: Record<string, any>,
    allowDisconnected = false
  ): Promise<boolean> {
    if (
      !this.hass || this._renderedGeneration !== this._entityGeneration ||
      serviceData.entity_id !== this._config?.entity ||
      !this.hass.states[serviceData.entity_id]
    ) {
      return false;
    }

    const generation = this._entityGeneration;

    this._actionError = null;
    const connectionStatus =
      this.hass.states[serviceData.entity_id]?.attributes?.connection_status;
    if (!allowDisconnected && connectionStatus !== "connected") {
      this._actionError = "Controls are unavailable while disconnected.";
      return false;
    }

    try {
      await this.hass.callService("junie_remote", service, serviceData);
      return generation === this._entityGeneration;
    } catch (err) {
      if (generation === this._entityGeneration) {
        this._actionError = err instanceof Error ? err.message : String(err);
      }
      return false;
    }
  }

  private _onTranscriptScroll(e: Event): void {
    const el = e.target as HTMLElement;
    const threshold = 40;
    const isAtBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;

    if (isAtBottom) {
      this._userScrolledUp = false;
      this._showScrollBottom = false;
    } else {
      this._userScrolledUp = true;
    }
  }

  private _scrollToBottom(smooth = true): void {
    const container = this.shadowRoot?.querySelector(
      ".transcript-container"
    ) as HTMLElement | null;
    if (container) {
      if (smooth) {
        container.scrollTo({
          top: container.scrollHeight,
          behavior: "smooth",
        });
      } else {
        container.scrollTop = container.scrollHeight;
      }
    }
    if (this._showScrollBottom) {
      this._showScrollBottom = false;
    }
    this._userScrolledUp = false;
  }

  private async _handleTakeover(): Promise<void> {
    if (!this.hass || !this._config?.entity) {
      return;
    }
    const stateObj = this.hass.states[this._config.entity];
    const attrs = stateObj?.attributes || {};
    const generation = this._entityGeneration;
    this._isKicking = true;
    try {
      await this._executeService(
        "kick_client",
        {
          entity_id: this._config.entity,
          host_key: attrs.host_key,
        },
        true
      );
    } finally {
      if (generation === this._entityGeneration) this._isKicking = false;
    }
  }

  private async _handleContainerClick(e: MouseEvent): Promise<void> {
    const target = e.target as HTMLElement;
    const copyBtn = target.closest(".copy-btn") as HTMLButtonElement | null;
    if (copyBtn) {
      const codeWrapper = copyBtn.closest(".code-block-wrapper");
      const codeEl = codeWrapper?.querySelector("pre code");
      if (codeEl) {
        const text = codeEl.textContent || "";
        try {
          await navigator.clipboard.writeText(text);
          const orig = copyBtn.textContent;
          copyBtn.textContent = "Copied!";
          copyBtn.classList.add("copied");
          setTimeout(() => {
            copyBtn.textContent = orig;
            copyBtn.classList.remove("copied");
          }, 2000);
        } catch (err) {
          console.error("Failed to copy code to clipboard:", err);
        }
      }
    }
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      ha-card {
        padding: 0;
        overflow: hidden;
        display: flex;
        flex-direction: column;
        border-radius: var(--ha-card-border-radius, 12px);
        background: var(--ha-card-background, var(--card-background-color, #ffffff));
        box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0, 0, 0, 0.08));
        color: var(--primary-text-color, #212121);
      }

      /* Host Status Header Bar */
      .header-bar {
        padding: 14px 16px;
        background: var(--secondary-background-color, #f7f9fa);
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .header-main-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px;
      }
      .card-title-group {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .card-icon {
        font-size: 1.3rem;
      }
      .card-title {
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--primary-text-color, #212121);
      }
      .header-sub-row {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px;
        font-size: 0.85rem;
        color: var(--secondary-text-color, #616161);
      }
      .host-identity {
        display: flex;
        align-items: center;
        gap: 4px;
        font-weight: 500;
      }
      .git-badges {
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .git-repo-badge,
      .git-branch-badge {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        background: rgba(0, 0, 0, 0.06);
        padding: 2px 8px;
        border-radius: 4px;
        font-family: monospace;
        font-size: 0.8rem;
      }
      .transcript-downloads {
        display: inline-flex;
        gap: 4px;
      }
      .transcript-download {
        font-size: 0.75rem;
        cursor: pointer;
        border: 1px solid var(--divider-color, #888);
        border-radius: 4px;
        background: transparent;
        color: var(--primary-text-color);
        padding: 1px 6px;
      }
      .working-dir {
        font-family: monospace;
        font-size: 0.8rem;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        max-width: 320px;
      }

      /* Status Pill */
      .status-pill-container {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
        text-transform: capitalize;
      }
      .status-pill.status-idle {
        background: #e8f5e9;
        color: #2e7d32;
      }
      .status-pill.status-working {
        background: #e1f5fe;
        color: #0277bd;
      }
      .status-pill.status-waiting {
        background: #fff8e1;
        color: #f57f17;
      }
      .status-pill.status-rejected {
        background: #ffebee;
        color: #c62828;
      }
      .status-pill.status-kicked {
        background: #eceff1;
        color: #455a64;
      }
      .status-pill.status-connecting,
      .status-pill.status-reconnecting {
        background: #ede7f6;
        color: #512da8;
      }
      .status-pill.status-disconnected,
      .status-pill.status-tunnel-not-found {
        background: #fafafa;
        border: 1px solid #e0e0e0;
        color: #757575;
      }

      .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: currentColor;
      }
      .status-working .status-dot {
        animation: pulse 1.5s infinite;
      }
      @keyframes pulse {
        0% { transform: scale(0.9); opacity: 0.6; }
        50% { transform: scale(1.2); opacity: 1; }
        100% { transform: scale(0.9); opacity: 0.6; }
      }

      /* Takeover button */
      .takeover-btn {
        background: var(--warning-color, #f57f17);
        color: #ffffff;
        border: none;
        border-radius: 4px;
        padding: 5px 10px;
        font-size: 0.8rem;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.2s, background-color 0.2s;
      }
      .takeover-btn:hover {
        opacity: 0.9;
      }
      .takeover-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }

      /* Integration quick-link buttons */
      .integration-buttons {
        display: inline-flex;
        gap: 4px;
        margin-left: 8px;
      }
      .integration-btn {
        font-size: 0.75rem;
        color: var(--primary-color, #0288d1);
        text-decoration: none;
        padding: 2px 6px;
        border-radius: 3px;
        transition: background-color 0.2s;
        white-space: nowrap;
      }
      .integration-btn:hover {
        background: var(--primary-color, #0288d1);
        color: #ffffff;
      }

      /* Transcript Container */
      .transcript-container-wrapper {
        position: relative;
        flex: 1;
      }
      .card-action-error,
      .transcript-error {
        margin: 8px 16px;
        padding: 8px 12px;
        border: 1px solid var(--error-color, #db4437);
        border-radius: 6px;
        background: var(--card-background-color, #ffffff);
        color: var(--error-color, #db4437);
        font-size: 0.9rem;
      }
      .connection-warning {
        margin: 8px 16px;
        padding: 8px 12px;
        border: 1px solid var(--warning-color, #ff9800);
        border-radius: 6px;
        color: var(--primary-text-color, #212121);
        font-size: 0.9rem;
      }
      .transcript-container {
        overflow-y: auto;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 14px;
        scroll-behavior: smooth;
      }

      /* Floating Scroll to Bottom button */
      .scroll-bottom-btn {
        position: absolute;
        bottom: 16px;
        right: 16px;
        z-index: 10;
        background: var(--primary-color, #0288d1);
        color: #ffffff;
        border: none;
        border-radius: 20px;
        padding: 8px 14px;
        font-size: 0.85rem;
        font-weight: 600;
        box-shadow: 0 3px 8px rgba(0, 0, 0, 0.25);
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 6px;
        transition: transform 0.2s, background-color 0.2s;
      }
      .scroll-bottom-btn:hover {
        transform: translateY(-2px);
      }

      /* Transcript Items */
      .transcript-item {
        display: flex;
        flex-direction: column;
        max-width: 90%;
      }
      .item-user-prompt,
      .item-user-response {
        align-self: flex-end;
        background: var(--primary-color, #0288d1);
        color: #ffffff;
        border-radius: 14px 14px 2px 14px;
        padding: 10px 14px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
      }
      .item-user-response {
        background: #455a64;
      }
      .bubble-header {
        font-size: 0.75rem;
        opacity: 0.85;
        margin-bottom: 4px;
        display: flex;
        justify-content: space-between;
        gap: 8px;
      }
      .bubble-role {
        font-weight: 600;
        text-transform: uppercase;
      }
      .bubble-content {
        font-size: 0.95rem;
        line-height: 1.45;
        word-break: break-word;
        white-space: pre-wrap;
      }
      .response-prompt,
      .item-system-message-details,
      .skills-detail,
      .step-description,
      .step-error-code,
      .progressing-step-description {
        font-size: 0.88rem;
        line-height: 1.4;
      }
      .response-prompt {
        margin-bottom: 6px;
        opacity: 0.9;
      }
      .step-description,
      .step-error-code {
        margin: 4px 0 8px;
      }
      .step-error-code {
        color: var(--error-color, #db4437);
        font-weight: 600;
      }
      .progressing-step-content {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .progressing-step-description {
        color: var(--secondary-text-color, #757575);
        font-weight: 400;
      }

      /* Step / Result Items */
      .item-step {
        align-self: flex-start;
        width: 100%;
        max-width: 100%;
        background: var(--card-background-color, #ffffff);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        padding: 12px 14px;
        box-sizing: border-box;
      }
      .step-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
      }
      .step-title {
        font-weight: 600;
        font-size: 0.95rem;
        color: var(--primary-text-color, #212121);
      }
      .step-badge {
        font-size: 0.75rem;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
        text-transform: uppercase;
      }
      .badge-result {
        background: #e8f5e9;
        color: #2e7d32;
      }
      .badge-error {
        background: #ffebee;
        color: #c62828;
      }
      .badge-cancelled {
        background: #fff3e0;
        color: #e65100;
      }
      .badge-step {
        background: #e0f2f1;
        color: #00695c;
      }

      /* System Message */
      .item-system-message {
        align-self: center;
        width: 100%;
        box-sizing: border-box;
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 0.85rem;
        display: flex;
        align-items: center;
        gap: 8px;
        background: var(--secondary-background-color, #f5f5f5);
        color: var(--secondary-text-color, #616161);
        border-left: 3px solid #9e9e9e;
      }
      .item-system-message.level-error {
        background: #ffebee;
        color: #c62828;
        border-left-color: #c62828;
      }
      .item-system-message.level-warning {
        background: #fffde7;
        color: #f57f17;
        border-left-color: #f57f17;
      }

      /* Skills Status */
      .item-skills-status {
        align-self: center;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        background: rgba(0, 0, 0, 0.04);
        color: var(--secondary-text-color, #757575);
        display: inline-flex;
        align-items: center;
        gap: 6px;
      }
      .skills-label {
        font-weight: 600;
      }
      .skills-detail {
        display: block;
      }

      /* Progressing Steps */
      .progressing-steps-wrapper {
        border-top: 1px dashed var(--divider-color, #e0e0e0);
        padding-top: 10px;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .progressing-step-item {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.88rem;
        color: var(--primary-color, #0288d1);
        font-weight: 500;
      }
      .spinner {
        width: 14px;
        height: 14px;
        border: 2px solid rgba(2, 136, 209, 0.2);
        border-top-color: var(--primary-color, #0288d1);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
      }
      @keyframes spin {
        to { transform: rotate(360deg); }
      }

      /* Welcome Empty State */
      .welcome-empty-state {
        text-align: center;
        padding: 36px 16px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
      }
      .welcome-icon {
        font-size: 2.2rem;
      }
      .welcome-title {
        font-size: 1.15rem;
        font-weight: 600;
        color: var(--primary-text-color, #212121);
      }
      .welcome-subtitle {
        font-size: 0.9rem;
        color: var(--secondary-text-color, #757575);
        max-width: 380px;
      }

      /* Last Step Preview */
      .last-step-preview-box {
        padding: 12px;
        background: var(--secondary-background-color, #f9f9f9);
        border-radius: 6px;
        border: 1px solid var(--divider-color, #e0e0e0);
        font-size: 0.9rem;
        color: var(--secondary-text-color, #424242);
      }
      .preview-label {
        font-weight: 600;
        font-size: 0.75rem;
        text-transform: uppercase;
        color: var(--secondary-text-color, #757575);
        margin-bottom: 4px;
      }

      /* Markdown & Code Block Styles */
      .markdown-body {
        font-size: 0.95rem;
        line-height: 1.5;
        color: var(--primary-text-color, #212121);
        word-break: break-word;
      }
      .markdown-body p {
        margin: 0 0 8px 0;
      }
      .markdown-body p:last-child {
        margin-bottom: 0;
      }
      .markdown-body h3,
      .markdown-body h4,
      .markdown-body h5,
      .markdown-body h6 {
        margin: 12px 0 6px 0;
        font-weight: 600;
      }
      .markdown-body code {
        font-family: monospace;
        font-size: 0.88rem;
        background: rgba(0, 0, 0, 0.06);
        padding: 2px 5px;
        border-radius: 3px;
      }
      .markdown-body pre {
        margin: 0;
        padding: 10px 12px;
        background: #1e1e1e;
        color: #d4d4d4;
        overflow-x: auto;
        font-family: monospace;
        font-size: 0.85rem;
        border-radius: 0 0 6px 6px;
      }
      .markdown-body pre code {
        background: none;
        padding: 0;
        color: inherit;
      }
      .code-block-wrapper {
        margin: 10px 0;
        border-radius: 6px;
        overflow: hidden;
        border: 1px solid #333333;
      }
      .code-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #2d2d2d;
        color: #cccccc;
        padding: 4px 10px;
        font-size: 0.75rem;
        font-family: monospace;
      }
      .code-lang {
        text-transform: lowercase;
      }
      .copy-btn {
        background: rgba(255, 255, 255, 0.12);
        color: #ffffff;
        border: none;
        border-radius: 3px;
        padding: 2px 8px;
        font-size: 0.75rem;
        cursor: pointer;
        transition: background 0.2s;
      }
      .copy-btn:hover {
        background: rgba(255, 255, 255, 0.25);
      }
      .copy-btn.copied {
        background: #2e7d32;
      }

      /* Changes Summary Badges */
      .changes-summary-container {
        margin-top: 10px;
        padding-top: 8px;
        border-top: 1px dashed var(--divider-color, #e0e0e0);
      }
      .changes-summary-title {
        font-size: 0.8rem;
        font-weight: 600;
        color: var(--secondary-text-color, #757575);
        margin-bottom: 6px;
      }
      .changes-summary-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }
      .change-badge {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.8rem;
        font-family: monospace;
      }
      .change-action {
        font-weight: 600;
        text-transform: uppercase;
        font-size: 0.7rem;
      }
      .change-badge.action-created {
        background: #e8f5e9;
        color: #2e7d32;
      }
      .change-badge.action-deleted {
        background: #ffebee;
        color: #c62828;
      }
      .change-badge.action-modified {
        background: #e3f2fd;
        color: #1565c0;
      }
      .change-badge.action-renamed {
        background: #fff8e1;
        color: #f57f17;
      }
      .change-diff.added {
        color: #2e7d32;
        font-weight: 600;
      }
      .change-diff.deleted {
        color: #c62828;
        font-weight: 600;
      }

      /* Plan Proposal Drawer */
      .plan-proposal-drawer {
        border-top: 1px solid var(--divider-color, #e0e0e0);
        background: var(--secondary-background-color, #f8fafc);
        display: flex;
        flex-direction: column;
      }
      .plan-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 16px;
        background: var(--secondary-background-color, #f1f5f9);
        border-bottom: 1px solid var(--divider-color, #e2e8f0);
        flex-wrap: wrap;
        gap: 8px;
      }
      .plan-title-group {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .plan-title {
        font-weight: 600;
        font-size: 0.95rem;
        color: var(--primary-text-color, #1e293b);
      }
      .plan-badge {
        font-size: 0.72rem;
        font-weight: 700;
        padding: 2px 7px;
        border-radius: 4px;
        text-transform: uppercase;
      }
      .plan-badge.ready-badge {
        background: #e8f5e9;
        color: #2e7d32;
        border: 1px solid #c8e6c9;
      }
      .plan-view-toggles {
        display: flex;
        align-items: center;
        gap: 4px;
      }
      .plan-tab-btn,
      .plan-collapse-btn {
        background: transparent;
        border: 1px solid var(--divider-color, #cbd5e1);
        border-radius: 4px;
        padding: 4px 10px;
        font-size: 0.8rem;
        font-weight: 500;
        color: var(--secondary-text-color, #475569);
        cursor: pointer;
        transition: background 0.15s, color 0.15s, border-color 0.15s;
      }
      .plan-tab-btn:hover,
      .plan-collapse-btn:hover {
        background: rgba(0, 0, 0, 0.05);
      }
      .plan-tab-btn.active {
        background: var(--primary-color, #0288d1);
        color: #ffffff;
        border-color: var(--primary-color, #0288d1);
      }
      .plan-body {
        padding: 14px 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .plan-file-path {
        font-family: monospace;
        font-size: 0.8rem;
        color: var(--secondary-text-color, #64748b);
        background: rgba(0, 0, 0, 0.04);
        padding: 4px 8px;
        border-radius: 4px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .plan-delivery-steps {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .delivery-steps-title {
        font-size: 0.85rem;
        font-weight: 600;
        color: var(--secondary-text-color, #475569);
        text-transform: uppercase;
      }
      .delivery-steps-list {
        margin: 0;
        padding-left: 20px;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .delivery-step-item {
        font-size: 0.88rem;
        line-height: 1.4;
      }
      .delivery-step-name {
        font-weight: 600;
        color: var(--primary-text-color, #1e293b);
      }
      .delivery-step-desc {
        color: var(--secondary-text-color, #475569);
        margin-top: 2px;
      }
      .plan-section-previews {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .section-preview-item {
        background: var(--card-background-color, #ffffff);
        border: 1px solid var(--divider-color, #e2e8f0);
        border-radius: 6px;
        padding: 10px 12px;
      }
      .section-preview-title {
        margin: 0 0 6px 0;
        font-size: 0.9rem;
        font-weight: 600;
        color: var(--primary-text-color, #1e293b);
      }
      .plan-section-tabs {
        display: flex;
        gap: 6px;
        overflow-x: auto;
        padding-bottom: 4px;
        border-bottom: 1px solid var(--divider-color, #e2e8f0);
      }
      .plan-section-tab-btn {
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        padding: 6px 12px;
        font-size: 0.85rem;
        font-weight: 500;
        color: var(--secondary-text-color, #64748b);
        cursor: pointer;
        white-space: nowrap;
      }
      .plan-section-tab-btn:hover {
        color: var(--primary-text-color, #1e293b);
      }
      .plan-section-tab-btn.active {
        color: var(--primary-color, #0288d1);
        border-bottom-color: var(--primary-color, #0288d1);
        font-weight: 600;
      }
      .plan-section-content {
        background: var(--card-background-color, #ffffff);
        border: 1px solid var(--divider-color, #e2e8f0);
        border-radius: 6px;
        padding: 12px;
        min-height: 60px;
        max-height: 240px;
        overflow-y: auto;
      }
      .plan-actions {
        display: flex;
        gap: 8px;
        padding-top: 6px;
      }
      .confirm-plan-btn {
        background: var(--primary-color, #0288d1);
        color: #ffffff;
        border: none;
        border-radius: 4px;
        padding: 8px 14px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.2s;
      }
      .confirm-plan-btn:hover {
        opacity: 0.9;
      }
      .refine-plan-btn {
        background: transparent;
        color: var(--primary-color, #0288d1);
        border: 1px solid var(--primary-color, #0288d1);
        border-radius: 4px;
        padding: 8px 14px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s;
      }
      .refine-plan-btn:hover {
        background: rgba(2, 136, 209, 0.08);
      }

      /* Active Requests Widgets */
      .active-requests-container {
        padding: 12px 16px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        border-top: 1px solid var(--divider-color, #e0e0e0);
        background: var(--secondary-background-color, #fdf8f4);
      }
      .active-request-card {
        background: var(--card-background-color, #ffffff);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-left: 4px solid var(--accent-color, #ff9800);
        border-radius: 6px;
        padding: 12px 14px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .active-request-title {
        font-weight: 600;
        font-size: 0.92rem;
        color: var(--primary-text-color, #212121);
      }
      .active-request-subtitle {
        font-size: 0.85rem;
        color: var(--secondary-text-color, #616161);
      }
      .active-request-input-row,
      .ask-async-input-row {
        display: flex;
        gap: 8px;
        align-items: center;
      }
      .ask-input,
      .ask-async-input {
        flex: 1;
        padding: 8px 10px;
        border: 1px solid var(--divider-color, #cccccc);
        border-radius: 4px;
        font-size: 0.9rem;
        font-family: inherit;
        outline: none;
      }
      .ask-input:focus,
      .ask-async-input:focus {
        border-color: var(--primary-color, #0288d1);
      }
      .ask-send-btn,
      .ask-async-submit-btn,
      .action-ok-btn {
        background: var(--primary-color, #0288d1);
        color: #ffffff;
        border: none;
        border-radius: 4px;
        padding: 8px 14px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.2s;
        white-space: nowrap;
      }
      .ask-send-btn:hover,
      .ask-async-submit-btn:hover,
      .action-ok-btn:hover {
        opacity: 0.9;
      }
      .choice-options,
      .approve-options,
      .ask-async-options {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .choice-opt-btn {
        background: var(--secondary-background-color, #f5f5f5);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 4px;
        padding: 8px 12px;
        text-align: left;
        cursor: pointer;
        display: flex;
        flex-direction: column;
        gap: 2px;
        transition: background 0.15s, border-color 0.15s;
      }
      .choice-opt-btn:hover {
        background: #e3f2fd;
        border-color: #90caf9;
      }
      .choice-opt-btn .opt-title {
        font-weight: 600;
        font-size: 0.85rem;
        color: var(--primary-text-color, #212121);
      }
      .choice-opt-btn .opt-desc {
        font-size: 0.78rem;
        color: var(--secondary-text-color, #616161);
      }
      .approve-opt-btn {
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 7px 12px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.2s;
      }
      .approve-opt-btn.opt-allow-once {
        background: #e3f2fd;
        color: #1565c0;
        border-color: #bbdefb;
      }
      .approve-opt-btn.opt-always-allow {
        background: #e8f5e9;
        color: #2e7d32;
        border-color: #c8e6c9;
      }
      .approve-opt-btn.opt-deny {
        background: #ffebee;
        color: #c62828;
        border-color: #ffcdd2;
      }
      .approve-opt-btn:hover {
        opacity: 0.85;
      }
      .ask-async-opt-btn {
        background: var(--secondary-background-color, #f5f5f5);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 4px;
        padding: 6px 12px;
        font-size: 0.85rem;
        cursor: pointer;
        transition: background 0.15s, border-color 0.15s;
      }
      .ask-async-opt-btn:hover {
        background: #e0e0e0;
      }
      .ask-async-opt-btn.selected {
        background: #e3f2fd;
        color: #0d47a1;
        border-color: #2196f3;
        font-weight: 600;
      }

      /* Card Footer & Controls */
      .card-footer {
        padding: 12px 16px;
        border-top: 1px solid var(--divider-color, #e0e0e0);
        background: var(--card-background-color, #ffffff);
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .plan-mode-banner {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #fff8e1;
        border: 1px solid #ffe082;
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 0.85rem;
        color: #b78103;
      }
      .plan-mode-label {
        font-weight: 600;
      }
      .cancel-plan-mode-btn {
        background: transparent;
        border: 1px solid #fbc02d;
        border-radius: 3px;
        padding: 2px 8px;
        font-size: 0.75rem;
        font-weight: 600;
        color: #b78103;
        cursor: pointer;
      }
      .cancel-plan-mode-btn:hover {
        background: rgba(0, 0, 0, 0.05);
      }
      .footer-control-row {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .brave-toggle-btn {
        background: var(--secondary-background-color, #f5f5f5);
        color: var(--secondary-text-color, #616161);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        gap: 4px;
        white-space: nowrap;
        transition: background 0.2s, color 0.2s, border-color 0.2s;
      }
      .brave-toggle-btn:hover {
        background: #e0e0e0;
      }
      .brave-toggle-btn.brave-active {
        background: #ffebee;
        color: #d32f2f;
        border-color: #ef9a9a;
      }
      .brave-toggle-btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }
      .model-select {
        flex: 1;
        padding: 6px 10px;
        border: 1px solid var(--divider-color, #cccccc);
        border-radius: 4px;
        background: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #212121);
        font-size: 0.85rem;
        outline: none;
      }
      .model-select:focus {
        border-color: var(--primary-color, #0288d1);
      }
      .prompt-input-row {
        display: flex;
        gap: 8px;
        align-items: flex-end;
      }
      .prompt-textarea {
        flex: 1;
        border: 1px solid var(--divider-color, #cccccc);
        border-radius: 6px;
        padding: 8px 10px;
        font-size: 0.9rem;
        font-family: inherit;
        resize: vertical;
        min-height: 40px;
        outline: none;
        background: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #212121);
      }
      .prompt-textarea:focus {
        border-color: var(--primary-color, #0288d1);
      }
      .prompt-actions {
        display: flex;
        gap: 6px;
        align-items: center;
      }
      .send-btn,
      .steer-btn {
        background: var(--primary-color, #0288d1);
        color: #ffffff;
        border: none;
        border-radius: 4px;
        padding: 8px 14px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.2s;
      }
      .steer-btn {
        background: #2e7d32;
      }
      .stop-btn {
        background: var(--error-color, #d32f2f);
        color: #ffffff;
        border: none;
        border-radius: 4px;
        padding: 8px 14px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.2s;
      }
      .send-btn:hover,
      .steer-btn:hover,
      .stop-btn:hover {
        opacity: 0.9;
      }
      .send-btn:disabled,
      .steer-btn:disabled,
      .stop-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
    `;
  }

  private _resolveStatus(
    entityState: string,
    connStatus?: string,
    sessStatus?: string
  ): { text: string; cssClass: string } {
    if (connStatus === "rejected" || entityState === "rejected") {
      return { text: "Rejected (In Use)", cssClass: "status-rejected" };
    }
    if (connStatus === "kicked" || entityState === "kicked") {
      return {
        text: "Session Taken Over (Kicked)",
        cssClass: "status-kicked",
      };
    }
    if (
      connStatus === "tunnel-not-found" ||
      entityState === "tunnel-not-found"
    ) {
      return {
        text: "Tunnel Not Found",
        cssClass: "status-tunnel-not-found",
      };
    }
    if (connStatus === "connecting" || entityState === "connecting") {
      return { text: "Connecting…", cssClass: "status-connecting" };
    }
    if (connStatus === "reconnecting" || entityState === "reconnecting") {
      return { text: "Reconnecting…", cssClass: "status-reconnecting" };
    }
    if (
      connStatus === "disconnected" ||
      connStatus === "offline" ||
      entityState === "disconnected" ||
      entityState === "offline"
    ) {
      return { text: "Disconnected", cssClass: "status-disconnected" };
    }

    if (sessStatus === "working" || entityState === "working") {
      return { text: "Working…", cssClass: "status-working" };
    }
    if (
      sessStatus === "waiting-for-input" ||
      entityState === "waiting-for-input"
    ) {
      return { text: "Waiting for Input", cssClass: "status-waiting" };
    }

    // Default connected / idle
    return { text: "Connected · Idle", cssClass: "status-idle" };
  }

  private _formatRepoDisplay(rawRepo?: string): string {
    if (!rawRepo) return "N/A";
    const cleaned = rawRepo.replace(/\.git$/, "");
    const parts = cleaned.split(/[/:]/);
    if (parts.length >= 2) {
      return parts.slice(-2).join("/");
    }
    return rawRepo;
  }

  protected render(): TemplateResult {
    if (!this._config) {
      return html`<ha-card><div style="padding: 16px;">Invalid configuration</div></ha-card>`;
    }

    const stateObj = this.hass?.states[this._config.entity];
    if (!stateObj) {
      return html`
        <ha-card>
          <div style="padding: 16px;">
            Entity not found: <code>${this._config.entity}</code>
          </div>
        </ha-card>
      `;
    }

    const attrs = stateObj.attributes || {};
    const entityState = stateObj.state || "disconnected";
    const connStatus = attrs.connection_status || entityState;
    const sessStatus = attrs.session_status || entityState;

    const statusInfo = this._resolveStatus(entityState, connStatus, sessStatus);
    const isRejected = connStatus === "rejected" || entityState === "rejected";

    const cardTitle =
      this._config.title || attrs.title || "JetBrains Junie Remote";
    const userName = attrs.user_name || "N/A";
    const osName = attrs.os_name || "N/A";
    const gitRepo = attrs.git_repo || "";
    const gitBranch = attrs.git_branch || "N/A";
    const workingDir = attrs.working_dir || "N/A";

    const maxHeight = this._config.max_height || "520px";

    const historyItems = this._transcript?.history || [];
    const progressingSteps =
      this._transcript?.progressing_steps || [];
    const isWorking =
      sessStatus === "working" || entityState === "working";
    const isConnected = connStatus === "connected";

    const entityId = this._config.entity;
    const hostKey = attrs.host_key || this._transcript?.host_key;
    const isWorkingOrWaiting =
      sessStatus === "working" ||
      sessStatus === "waiting-for-input" ||
      entityState === "working" ||
      entityState === "waiting-for-input";
    const currentBrave = Boolean(
      attrs.brave_mode ?? this._transcript?.brave_mode ?? false
    );
    const plan = this._transcript?.plan_proposal || attrs.plan_summary;
    const activeRequests =
      this._transcript?.active_requests?.length
        ? this._transcript.active_requests
        : attrs.active_requests || [];
    const modelOptions =
      attrs.model_options ||
      this._transcript?.model_selection?.options ||
      [];
    const currentModelId =
      attrs.current_model_id ||
      this._transcript?.model_selection?.current_model_id;
    const currentEffortId =
      attrs.current_effort_id ||
      this._transcript?.model_selection?.current_effort_id;
    const selectedModelEffort =
      attrs.selected_model_effort ||
      (currentModelId
        ? currentEffortId
          ? `${currentModelId}:${currentEffortId}`
          : currentModelId
        : "");

    return html`
      <ha-card>
        ${!isConnected
          ? html`<div class="connection-warning" role="status">
              Controls are unavailable while disconnected.
            </div>`
          : ""}
        ${this._actionError
          ? html`<div class="card-action-error" role="alert">
              ${this._actionError}
            </div>`
          : ""}
        <!-- Host Status Header Bar -->
        <div class="header-bar">
          <div class="header-main-row">
            <div class="card-title-group">
              <span class="card-icon">🤖</span>
              <span class="card-title">${cardTitle}</span>
            </div>
            <div class="status-pill-container">
              <span class="status-pill ${statusInfo.cssClass}">
                <span class="status-dot"></span>
                <span class="status-text">${statusInfo.text}</span>
              </span>
              <button
                class="takeover-btn"
                type="button"
                ?disabled="${this._isKicking}"
                @click="${this._handleTakeover}"
                title="Disconnect conflicting clients and take over this session"
              >
                ${this._isKicking
                  ? "Disconnecting…"
                  : "🔑 Take Over"}
              </button>
            </div>
          </div>

          <div class="header-sub-row">
            <span class="host-identity" title="Host User & OS">
              👤 <strong>${userName}</strong> · ${osName}
            </span>
            ${gitRepo
              ? html`
                  <span class="git-badges">
                    <span class="git-repo-badge" title="${gitRepo}">
                      📦 ${this._formatRepoDisplay(gitRepo)}
                    </span>
                    <span class="git-branch-badge" title="Git Branch">
                      🌿 ${gitBranch}
                    </span>
                  </span>
                `
              : ""}
            <span class="working-dir" title="Working Directory: ${workingDir}">
              📂 ${workingDir}
            </span>
            ${attrs.transcript_json_url || attrs.transcript_md_url
              ? html`<span class="transcript-downloads">
                  ${attrs.transcript_json_url
                    ? html`<button class="transcript-download" type="button"
                        @click=${() => this._downloadTranscript("json")}>⬇ JSON</button>`
                    : ""}
                  ${attrs.transcript_md_url
                    ? html`<button class="transcript-download" type="button"
                        @click=${() => this._downloadTranscript("md")}>⬇ Markdown</button>`
                    : ""}
                </span>`
              : ""}
            <span class="integration-buttons">
              <a
                class="integration-btn"
                href="https://my.home-assistant.io/redirect/integration/?domain=junie_remote"
                target="_blank"
                rel="noopener noreferrer"
                title="Open Junie Remote integration settings"
              >
                ⚙️ Integration
              </a>
              <a
                class="integration-btn"
                href="https://my.home-assistant.io/redirect/marketplace_repository/?owner=OpenTasmania&repository=junie-remote-lovelace-card&category=integration"
                target="_blank"
                rel="noopener noreferrer"
                title="Open in HACS / Marketplace"
              >
                📦 HACS
              </a>
              <a
                class="integration-btn"
                href="https://my.home-assistant.io/redirect/integrations/"
                target="_blank"
                rel="noopener noreferrer"
                title="Open Integrations dashboard"
              >
                🔌 Integrations
              </a>
            </span>
          </div>
        </div>

        <!-- Transcript Viewer -->
        <div class="transcript-container-wrapper">
          ${this._transcriptError
            ? html`<div class="transcript-error" role="alert">
                Transcript could not be loaded: ${this._transcriptError}
              </div>`
            : ""}
          <div
            class="transcript-container"
            style="max-height: ${maxHeight};"
            @scroll="${this._onTranscriptScroll}"
            @click="${this._handleContainerClick}"
          >
            ${historyItems.length > 0
              ? html`
                  ${historyItems.map((item) => this._renderTranscriptItem(item))}
                `
              : isConnected && sessStatus === "idle"
              ? html`
                  <div class="welcome-empty-state">
                    <div class="welcome-icon">✨</div>
                    <div class="welcome-title">
                      Welcome to Junie — What shall we build today?
                    </div>
                    <div class="welcome-subtitle">
                      Ask questions, plan features, or request code changes.
                    </div>
                  </div>
                `
              : attrs.last_step_preview
              ? html`
                  <div class="last-step-preview-box">
                    <div class="preview-label">Last Activity Preview</div>
                    <div>${attrs.last_step_preview}</div>
                  </div>
                `
              : html`
                  <div style="padding: 16px; color: var(--secondary-text-color);">
                    ${this._transcriptLoading
                      ? "Loading transcript…"
                      : "No transcript recorded for this session."}
                  </div>
                `}

            <!-- In-progress steps -->
            ${(isWorking || progressingSteps.length > 0)
              ? html`
                  <div class="progressing-steps-wrapper">
                    ${progressingSteps.length > 0
                      ? progressingSteps.map((step) =>
                          this._renderProgressingStep(step)
                        )
                      : html`
                          <div class="progressing-step-item">
                            <span class="spinner"></span>
                            <span>Working on task…</span>
                          </div>
                        `}
                  </div>
                `
              : ""}
          </div>

          ${this._showScrollBottom
            ? html`
                <button
                  class="scroll-bottom-btn"
                  type="button"
                  @click="${() => this._scrollToBottom(true)}"
                >
                  ↓ New messages
                </button>
              `
            : ""}
        </div>

        <!-- Plan Proposal Drawer -->
        ${plan
          ? this._renderPlanProposal(plan, entityId, hostKey, isConnected)
          : ""}

        <!-- Active Requests Widgets -->
        ${activeRequests.length > 0
          ? html`
              <div class="active-requests-container">
                ${activeRequests.map((req, idx) =>
                  this._renderActiveRequest(
                    req,
                    idx,
                    hostKey,
                    entityId,
                    isConnected
                  )
                )}
              </div>
            `
          : ""}

        <!-- Footer Control Bar & Prompt Input -->
        ${this._renderFooter(
          attrs,
          hostKey,
          entityId,
          isWorkingOrWaiting,
          currentBrave,
          selectedModelEffort,
          modelOptions,
          isConnected
        )}
      </ha-card>
    `;
  }

  private _renderPlanProposal(
    plan: PlanProposal | PlanSummary,
    entityId: string,
    hostKey: string | undefined,
    isConnected: boolean
  ): TemplateResult {
    const readyForReview = Boolean(
      plan.ready_for_review ?? (plan as any).readyForReview
    );
    const showActions = Boolean(
      plan.show_actions ?? (plan as any).showActions
    );
    const planFilePath =
      plan.plan_file_path || (plan as any).planFilePath || null;
    const deliverySteps: any[] =
      plan.delivery_steps || (plan as any).deliverySteps || [];
    const rawSections =
      (plan as any).sections && (plan as any).sections.length > 0
        ? (plan as any).sections
        : (plan.section_names || []).map((name: string) => ({
            name,
            content: "",
          }));

    return html`
      <div class="plan-proposal-drawer">
        <div class="plan-header">
          <div class="plan-title-group">
            <span class="plan-title">📋 Plan Proposal</span>
            ${readyForReview
              ? html`<span class="plan-badge ready-badge">Ready for review</span>`
              : ""}
          </div>
          <div class="plan-view-toggles">
            <button
              class="plan-tab-btn plan-btn-summary ${this._planViewMode === "summary" ? "active" : ""}"
              type="button"
              @click="${() => (this._planViewMode = "summary")}"
            >
              Summary
            </button>
            <button
              class="plan-tab-btn plan-btn-full ${this._planViewMode === "full" ? "active" : ""}"
              type="button"
              @click="${() => (this._planViewMode = "full")}"
            >
              Full Plan
            </button>
            <button
              class="plan-collapse-btn"
              type="button"
              @click="${this._togglePlanCollapse}"
            >
              ${this._planViewMode === "collapsed" ? "Review Plan" : "Collapse"}
            </button>
          </div>
        </div>

        ${this._planViewMode !== "collapsed"
          ? html`
              <div class="plan-body">
                ${planFilePath
                  ? html`
                      <div class="plan-file-path" title="${planFilePath}">
                        📄 ${planFilePath}
                      </div>
                    `
                  : ""}
                ${this._planViewMode === "summary"
                  ? html`
                      <div class="plan-summary-view">
                        ${deliverySteps.length > 0
                          ? html`
                              <div class="plan-delivery-steps">
                                <div class="delivery-steps-title">
                                  Delivery Steps
                                </div>
                                <ol class="delivery-steps-list">
                                  ${deliverySteps.map(
                                    (step, idx) => html`
                                      <li class="delivery-step-item">
                                        <span class="delivery-step-name"
                                          >${step.name ||
                                          step.title ||
                                          `Step ${idx + 1}`}</span
                                        >
                                        ${step.description || step.text
                                          ? html`<div class="delivery-step-desc">
                                              ${step.description || step.text}
                                            </div>`
                                          : ""}
                                      </li>
                                    `
                                  )}
                                </ol>
                              </div>
                            `
                          : html`
                              <div class="plan-section-previews">
                                ${rawSections.slice(0, 2).map(
                                  (sec: any) => html`
                                    <div class="section-preview-item">
                                      <h4 class="section-preview-title">
                                        ${sec.name || sec.title || "Section"}
                                      </h4>
                                      <div class="section-preview-content">
                                        ${sec.content
                                          ? renderMarkdown(sec.content)
                                          : html`<em>No preview available</em>`}
                                      </div>
                                    </div>
                                  `
                                )}
                              </div>
                            `}
                      </div>
                    `
                  : html`
                      <div class="plan-full-view">
                        <div class="plan-section-tabs">
                          ${rawSections.map(
                            (sec: any, idx: number) => html`
                              <button
                                class="plan-section-tab-btn ${this._selectedPlanSection === idx ? "active" : ""}"
                                type="button"
                                @click="${() =>
                                  (this._selectedPlanSection = idx)}"
                              >
                                ${sec.name || sec.title || `Section ${idx + 1}`}
                              </button>
                            `
                          )}
                          ${deliverySteps.length > 0
                            ? html`
                                <button
                                  class="plan-section-tab-btn ${this._selectedPlanSection === "delivery-steps" ? "active" : ""}"
                                  type="button"
                                  @click="${() =>
                                    (this._selectedPlanSection =
                                      "delivery-steps")}"
                                >
                                  Delivery Steps
                                </button>
                              `
                            : ""}
                        </div>

                        <div class="plan-section-content">
                          ${this._selectedPlanSection === "delivery-steps"
                            ? html`
                                <div class="plan-delivery-steps">
                                  <ol class="delivery-steps-list">
                                    ${deliverySteps.map(
                                      (step, idx) => html`
                                        <li class="delivery-step-item">
                                          <span class="delivery-step-name"
                                            >${step.name ||
                                            step.title ||
                                            `Step ${idx + 1}`}</span
                                          >
                                          ${step.description || step.text
                                            ? html`<div
                                                class="delivery-step-desc"
                                              >
                                                ${step.description ||
                                                step.text}
                                              </div>`
                                            : ""}
                                        </li>
                                      `
                                    )}
                                  </ol>
                                </div>
                              `
                            : html`
                                ${(() => {
                                  const activeSec =
                                    typeof this._selectedPlanSection ===
                                    "number"
                                      ? rawSections[
                                          this._selectedPlanSection
                                        ] || rawSections[0]
                                      : rawSections[0];
                                  return activeSec?.content
                                    ? renderMarkdown(activeSec.content)
                                    : html`<div>
                                        ${activeSec?.name ||
                                        activeSec?.title ||
                                        "Section content"}
                                      </div>`;
                                })()}
                              `}
                        </div>
                      </div>
                    `}
                ${showActions
                  ? html`
                      <div class="plan-actions">
                        <button
                          class="confirm-plan-btn"
                          type="button"
                          ?disabled="${!isConnected}"
                          @click="${() =>
                            this._handleConfirmPlan(entityId, hostKey)}"
                        >
                          Confirm and Implement
                        </button>
                        <button
                          class="refine-plan-btn"
                          type="button"
                          ?disabled="${!isConnected}"
                          @click="${this._handleRefinePlan}"
                        >
                          Refine Plan
                        </button>
                      </div>
                    `
                  : ""}
              </div>
            `
          : ""}
      </div>
    `;
  }

  private _togglePlanCollapse(): void {
    if (this._planViewMode === "collapsed") {
      this._planViewMode = "summary";
    } else {
      this._planViewMode = "collapsed";
    }
  }

  private async _handleConfirmPlan(
    entityId: string,
    hostKey?: string
  ): Promise<void> {
    if (!this.hass || !this._config?.entity) return;
    const targetEntity = entityId || this._config.entity;
    const stateObj = this.hass.states[targetEntity];
    const attrs = stateObj?.attributes || {};
    const targetHost =
      hostKey || attrs.host_key || this._transcript?.host_key;

    await this._executeService("confirm_plan", {
      entity_id: targetEntity,
      host_key: targetHost,
    });
  }

  private _handleRefinePlan(): void {
    this._inputMode = "plan";
    this.updateComplete.then(() => {
      const textarea = this.shadowRoot?.querySelector(
        ".prompt-textarea"
      ) as HTMLTextAreaElement | null;
      textarea?.focus();
    });
  }

  private _renderActiveRequest(
    req: ActiveRequest,
    idx: number,
    hostKey: string | undefined,
    entityId: string | undefined,
    isConnected: boolean
  ): TemplateResult {
    const reqType = (req.type || "").toLowerCase();
    const requestId = req.requestId || req.id || `req_${idx}`;

    if (reqType === "ask") {
      const question =
        req.question || req.prompt || req.message || "Input required";
      return html`
        <div
          class="active-request-card active-request-ask"
          data-request-id="${requestId}"
        >
          <div class="active-request-title">${question}</div>
          <div class="active-request-input-row">
            <input
              type="text"
              class="ask-input"
              ?disabled="${!isConnected}"
              placeholder="Type your answer…"
              .value="${this._askInputs[requestId] || ""}"
              @input="${(e: Event) => {
                this._askInputs = {
                  ...this._askInputs,
                  [requestId]: (e.target as HTMLInputElement).value,
                };
              }}"
              @keydown="${(e: KeyboardEvent) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  this._submitAsk(req, requestId, hostKey, entityId);
                }
              }}"
            />
            <button
              class="ask-send-btn"
              type="button"
              ?disabled="${!isConnected}"
              @click="${() =>
                this._submitAsk(req, requestId, hostKey, entityId)}"
            >
              Send
            </button>
          </div>
        </div>
      `;
    }

    if (reqType === "choice") {
      const title =
        req.title || req.question || req.message || "Select an option";
      const options = req.options || [];
      return html`
        <div
          class="active-request-card active-request-choice"
          data-request-id="${requestId}"
        >
          <div class="active-request-title">${title}</div>
          <div class="choice-options">
            ${options.map(
              (opt) => html`
                <button
                  class="choice-opt-btn"
                  type="button"
                  ?disabled="${!isConnected}"
                  @click="${() =>
                    this._submitChoice(req, requestId, opt, hostKey, entityId)}"
                >
                  <span class="opt-title"
                    >${opt.title || opt.label || opt.name || opt.id}</span
                  >
                  ${opt.description
                    ? html`<span class="opt-desc">${opt.description}</span>`
                    : ""}
                </button>
              `
            )}
          </div>
        </div>
      `;
    }

    if (reqType === "approve") {
      const title =
        req.title || req.message || req.question || "Approval required";
      const options = req.options?.length
        ? req.options
        : [
            { type: "allow-once", label: "Allow once", optionIndex: 0 },
            { type: "always-allow", label: "Always allow", optionIndex: 1 },
            { type: "deny", label: "Deny", optionIndex: 2 },
          ];
      return html`
        <div
          class="active-request-card active-request-approve"
          data-request-id="${requestId}"
        >
          <div class="active-request-title">${title}</div>
          <div class="approve-options">
            ${options.map((opt, optIdx) => {
              let label = opt.label;
              if (!label) {
                if (opt.type === "deny") label = "Deny";
                else if (opt.type === "always-allow") label = "Always allow";
                else label = "Allow once";
              }
              return html`
                <button
                  class="approve-opt-btn opt-${opt.type || "allow-once"}"
                  type="button"
                  ?disabled="${!isConnected}"
                  @click="${() =>
                    this._submitApprove(
                      req,
                      requestId,
                      opt,
                      optIdx,
                      hostKey,
                      entityId
                    )}"
                >
                  ${label}
                </button>
              `;
            })}
          </div>
        </div>
      `;
    }

    if (reqType === "action") {
      const title = req.title || req.message || "Notice";
      return html`
        <div
          class="active-request-card active-request-action"
          data-request-id="${requestId}"
        >
          <div class="active-request-title">${title}</div>
          <button
            class="action-ok-btn"
            type="button"
            ?disabled="${!isConnected}"
            @click="${() =>
              this._submitAction(req, requestId, hostKey, entityId)}"
          >
            OK
          </button>
        </div>
      `;
    }

    if (reqType === "ask-async") {
      const name = req.name || req.title || "Request";
      const question = req.question || req.prompt || "";
      const options = req.options || [];
      const allowMultiple = Boolean(
        req.allowMultiple ?? req.allow_multiple
      );
      const selections = this._askAsyncSelections[requestId] || [];

      return html`
        <div
          class="active-request-card active-request-ask-async"
          data-request-id="${requestId}"
        >
          <div class="active-request-title">${name}</div>
          ${question
            ? html`<div class="active-request-subtitle">${question}</div>`
            : ""}
          ${options.length > 0
            ? html`
                <div class="ask-async-options">
                  ${options.map((opt) => {
                    const optId = opt.id || "";
                    const isSelected = selections.includes(optId);
                    return html`
                      <button
                        class="ask-async-opt-btn ${isSelected
                          ? "selected"
                          : ""}"
                        type="button"
                        ?disabled="${!isConnected}"
                        @click="${() =>
                          this._toggleAskAsyncOption(
                            requestId,
                            optId,
                            allowMultiple
                          )}"
                      >
                        ${isSelected ? "✓ " : ""}${opt.label ||
                        opt.title ||
                        opt.name ||
                        opt.id}
                      </button>
                    `;
                  })}
                </div>
              `
            : ""}
          <div class="ask-async-input-row">
            <input
              type="text"
              class="ask-async-input"
              ?disabled="${!isConnected}"
              placeholder="Type your response…"
              .value="${this._askAsyncInputs[requestId] || ""}"
              @input="${(e: Event) => {
                this._askAsyncInputs = {
                  ...this._askAsyncInputs,
                  [requestId]: (e.target as HTMLInputElement).value,
                };
              }}"
              @keydown="${(e: KeyboardEvent) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  this._submitAskAsync(req, requestId, hostKey, entityId);
                }
              }}"
            />
            <button
              class="ask-async-submit-btn"
              type="button"
              ?disabled="${!isConnected}"
              @click="${() =>
                this._submitAskAsync(req, requestId, hostKey, entityId)}"
            >
              Submit
            </button>
          </div>
        </div>
      `;
    }

    return html``;
  }

  private async _submitAsk(
    req: ActiveRequest,
    requestId: string,
    hostKey?: string,
    entityId?: string
  ): Promise<void> {
    if (!this.hass || !this._config?.entity) return;
    const generation = this._entityGeneration;
    const targetEntity = entityId || this._config.entity;
    const stateObj = this.hass.states[targetEntity];
    const attrs = stateObj?.attributes || {};
    const targetHost =
      hostKey || attrs.host_key || this._transcript?.host_key;

    const inputEl =
      (this.shadowRoot?.querySelector(
        `.active-request-ask[data-request-id="${requestId}"] .ask-input`
      ) as HTMLInputElement | null) ||
      (this.shadowRoot?.querySelector(".ask-input") as HTMLInputElement | null);
    const val = (inputEl?.value || this._askInputs[requestId] || "").trim();

    const sent = await this._executeService("respond_request", {
      entity_id: targetEntity,
      host_key: targetHost,
      request_id: requestId,
      method: "ask",
      display_text: val,
      response: val,
    });
    if (!sent || generation !== this._entityGeneration) return;

    const updated = { ...this._askInputs };
    delete updated[requestId];
    this._askInputs = updated;
    if (inputEl) inputEl.value = "";
  }

  private async _submitChoice(
    req: ActiveRequest,
    requestId: string,
    opt: ActiveRequestOption,
    hostKey?: string,
    entityId?: string
  ): Promise<void> {
    if (!this.hass || !this._config?.entity) return;
    const targetEntity = entityId || this._config.entity;
    const stateObj = this.hass.states[targetEntity];
    const attrs = stateObj?.attributes || {};
    const targetHost =
      hostKey || attrs.host_key || this._transcript?.host_key;
    const displayText = opt.title || opt.label || opt.name || opt.id;

    await this._executeService("respond_request", {
      entity_id: targetEntity,
      host_key: targetHost,
      request_id: requestId,
      method: "choice",
      option_id: opt.id || "",
      display_text: displayText,
    });
  }

  private async _submitApprove(
    req: ActiveRequest,
    requestId: string,
    opt: ActiveRequestOption,
    optIdx: number,
    hostKey?: string,
    entityId?: string
  ): Promise<void> {
    if (!this.hass || !this._config?.entity) return;
    const targetEntity = entityId || this._config.entity;
    const stateObj = this.hass.states[targetEntity];
    const attrs = stateObj?.attributes || {};
    const targetHost =
      hostKey || attrs.host_key || this._transcript?.host_key;

    const isDeny = opt.type === "deny";
    const isAlways = opt.type === "always-allow";
    const optionIndex =
      opt.optionIndex !== undefined ? opt.optionIndex : optIdx;
    const displayText = isDeny
      ? "Deny"
      : isAlways
      ? opt.label || "Always allow"
      : "Allow once";

    await this._executeService("respond_request", {
      entity_id: targetEntity,
      host_key: targetHost,
      request_id: requestId,
      method: "approve",
      approve: !isDeny,
      add_to_allow_list: isAlways,
      option_index: optionIndex,
      display_text: displayText,
    });
  }

  private async _submitAction(
    req: ActiveRequest,
    requestId: string,
    hostKey?: string,
    entityId?: string
  ): Promise<void> {
    if (!this.hass || !this._config?.entity) return;
    const targetEntity = entityId || this._config.entity;
    const stateObj = this.hass.states[targetEntity];
    const attrs = stateObj?.attributes || {};
    const targetHost =
      hostKey || attrs.host_key || this._transcript?.host_key;

    await this._executeService("respond_request", {
      entity_id: targetEntity,
      host_key: targetHost,
      request_id: requestId,
      method: "cancel",
      display_text: "OK",
    });
  }

  private _toggleAskAsyncOption(
    requestId: string,
    optionId: string,
    allowMultiple: boolean
  ): void {
    const current = this._askAsyncSelections[requestId] || [];
    let next: string[];
    if (allowMultiple) {
      if (current.includes(optionId)) {
        next = current.filter((id) => id !== optionId);
      } else {
        next = [...current, optionId];
      }
    } else {
      next = current.includes(optionId) ? [] : [optionId];
    }
    this._askAsyncSelections = {
      ...this._askAsyncSelections,
      [requestId]: next,
    };
  }

  private async _submitAskAsync(
    req: ActiveRequest,
    requestId: string,
    hostKey?: string,
    entityId?: string
  ): Promise<void> {
    if (!this.hass || !this._config?.entity) return;
    const generation = this._entityGeneration;
    const targetEntity = entityId || this._config.entity;
    const stateObj = this.hass.states[targetEntity];
    const attrs = stateObj?.attributes || {};
    const targetHost =
      hostKey || attrs.host_key || this._transcript?.host_key;

    const selectedIds = Array.from(
      this._askAsyncSelections[requestId] || []
    );
    const inputEl =
      (this.shadowRoot?.querySelector(
        `.active-request-ask-async[data-request-id="${requestId}"] .ask-async-input`
      ) as HTMLInputElement | null) ||
      (this.shadowRoot?.querySelector(
        ".ask-async-input"
      ) as HTMLInputElement | null);
    const textVal = (
      inputEl?.value ||
      this._askAsyncInputs[requestId] ||
      ""
    ).trim();
    const displayText =
      textVal || (selectedIds.length > 0 ? selectedIds.join(", ") : "Submit");

    const sent = await this._executeService("respond_request", {
      entity_id: targetEntity,
      host_key: targetHost,
      request_id: requestId,
      method: "ask-async",
      option_ids: selectedIds,
      response: textVal || null,
      display_text: displayText,
    });
    if (!sent || generation !== this._entityGeneration) return;

    const nextSelections = { ...this._askAsyncSelections };
    delete nextSelections[requestId];
    this._askAsyncSelections = nextSelections;

    const nextInputs = { ...this._askAsyncInputs };
    delete nextInputs[requestId];
    this._askAsyncInputs = nextInputs;
    if (inputEl) inputEl.value = "";
  }

  private _renderFooter(
    attrs: Record<string, any>,
    hostKey: string | undefined,
    entityId: string,
    isWorkingOrWaiting: boolean,
    currentBrave: boolean,
    selectedModelEffort: string,
    modelOptions: any[],
    isConnected: boolean
  ): TemplateResult {
    return html`
      <div class="card-footer">
        ${this._inputMode === "plan"
          ? html`
              <div class="plan-mode-banner">
                <span class="plan-mode-label"
                  >Plan &gt; Iterating on plan</span
                >
                <button
                  class="cancel-plan-mode-btn"
                  type="button"
                  @click="${this._cancelPlanMode}"
                >
                  Esc to cancel
                </button>
              </div>
            `
          : ""}

        <div class="footer-control-row">
          <button
            class="brave-toggle-btn ${currentBrave ? "brave-active" : ""}"
            type="button"
            aria-pressed="${currentBrave ? "true" : "false"}"
            ?disabled="${!isConnected || this._bravePending}"
            @click="${() =>
              this._handleToggleBraveMode(entityId, hostKey, currentBrave)}"
          >
            ${this._bravePending ? "Saving…" : "⚑ Brave"}
          </button>

          <select
            class="model-select"
            ?disabled="${!isConnected}"
            .value="${selectedModelEffort}"
            @change="${(e: Event) =>
              this._handleModelSelectChange(e, entityId, hostKey)}"
          >
            ${modelOptions.length > 0
              ? modelOptions.map(
                  (opt) => html`
                    <option
                      value="${opt.value || opt.id}"
                      ?selected="${(opt.value || opt.id) ===
                      selectedModelEffort}"
                    >
                      ${opt.label || opt.name || opt.value || opt.id}
                    </option>
                  `
                )
              : html`<option value="">Default Model</option>`}
          </select>
        </div>

        <div class="prompt-input-row">
          <textarea
            class="prompt-textarea"
            ?disabled="${!isConnected}"
            placeholder="${this._inputMode === "plan"
              ? "Describe how to refine the plan..."
              : "Type a message..."}"
            .value="${this._promptText}"
            @input="${this._onPromptInput}"
            @keydown="${(e: KeyboardEvent) =>
              this._onPromptKeydown(e, entityId, hostKey)}"
            rows="2"
          ></textarea>

          <div class="prompt-actions">
            ${isWorkingOrWaiting
              ? html`
                  ${this._promptText.trim().length > 0
                    ? html`
                        <button
                          class="steer-btn"
                          type="button"
                          ?disabled="${!isConnected}"
                          @click="${() =>
                            this._submitPrompt(entityId, hostKey)}"
                        >
                          Steer
                        </button>
                      `
                    : ""}
                  <button
                    class="stop-btn"
                    type="button"
                    title="Stop"
                    ?disabled="${!isConnected}"
                    @click="${() => this._handleStopTask(entityId, hostKey)}"
                  >
                    Stop
                  </button>
                `
              : html`
                  <button
                    class="send-btn"
                    type="button"
                    title="Send"
                    ?disabled="${!isConnected ||
                    this._isSending ||
                    (attrs.can_send_prompt ??
                      this._transcript?.can_send_prompt) === false}"
                    @click="${() => this._submitPrompt(entityId, hostKey)}"
                  >
                    Send
                  </button>
                `}
          </div>
        </div>
      </div>
    `;
  }

  private _onPromptInput(e: Event): void {
    this._promptText = (e.target as HTMLTextAreaElement).value;
  }

  private _onPromptKeydown(
    e: KeyboardEvent,
    entityId: string,
    hostKey?: string
  ): void {
    if (e.key === "Escape" && this._inputMode === "plan") {
      e.preventDefault();
      this._cancelPlanMode();
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      this._submitPrompt(entityId, hostKey);
    }
  }

  private _cancelPlanMode(): void {
    this._inputMode = "normal";
  }

  private async _submitPrompt(
    entityId: string,
    hostKey?: string
  ): Promise<void> {
    const textarea = this.shadowRoot?.querySelector(
      ".prompt-textarea"
    ) as HTMLTextAreaElement | null;
    const text = (textarea?.value || this._promptText || "").trim();
    if (!text || !this.hass || !this._config?.entity) {
      return;
    }
    const targetEntity = entityId || this._config.entity;
    if (targetEntity !== this._config.entity || !this.hass.states[targetEntity]) return;
    const generation = this._entityGeneration;
    const stateObj = this.hass.states[targetEntity];
    const attrs = stateObj?.attributes || {};
    const targetHost =
      hostKey || attrs.host_key || this._transcript?.host_key;

    this._isSending = true;
    try {
      if (this._inputMode === "plan") {
        const sent = await this._executeService("send_plan_prompt", {
          entity_id: targetEntity,
          host_key: targetHost,
          prompt: text,
        });
        if (!sent || generation !== this._entityGeneration) return;
        this._inputMode = "normal";
      } else {
        const sent = await this._executeService("send_prompt", {
          entity_id: targetEntity,
          host_key: targetHost,
          prompt: text,
        });
        if (!sent || generation !== this._entityGeneration) return;
      }
      this._promptText = "";
      if (textarea) textarea.value = "";
    } finally {
      if (generation === this._entityGeneration) this._isSending = false;
    }
  }

  private async _handleToggleBraveMode(
    entityId: string,
    hostKey?: string,
    currentBrave?: boolean
  ): Promise<void> {
    if (!this.hass || !this._config?.entity) return;
    const targetEntity = entityId || this._config.entity;
    if (targetEntity !== this._config.entity || !this.hass.states[targetEntity]) return;
    const generation = this._entityGeneration;
    const stateObj = this.hass.states[targetEntity];
    const attrs = stateObj?.attributes || {};
    const targetHost =
      hostKey || attrs.host_key || this._transcript?.host_key;
    const isEnabled =
      currentBrave !== undefined
        ? currentBrave
        : Boolean(attrs.brave_mode ?? this._transcript?.brave_mode ?? false);

    this._bravePending = true;
    try {
      await this._executeService("toggle_brave_mode", {
        entity_id: targetEntity,
        host_key: targetHost,
        enabled: !isEnabled,
      });
    } finally {
      if (generation === this._entityGeneration) this._bravePending = false;
    }
  }

  private async _handleModelSelectChange(
    e: Event,
    entityId: string,
    hostKey?: string
  ): Promise<void> {
    const target = e.target as HTMLSelectElement;
    const val = target.value;
    if (!this.hass || !this._config?.entity) return;
    const targetEntity = entityId || this._config.entity;
    const stateObj = this.hass.states[targetEntity];
    const attrs = stateObj?.attributes || {};
    const targetHost =
      hostKey || attrs.host_key || this._transcript?.host_key;

    const colonIdx = val.indexOf(":");
    let modelId = val;
    let effortId: string | null = null;
    if (colonIdx !== -1) {
      modelId = val.slice(0, colonIdx);
      effortId = val.slice(colonIdx + 1) || null;
    }

    await this._executeService("select_model", {
      entity_id: targetEntity,
      host_key: targetHost,
      model_id: modelId,
      effort_id: effortId,
    });
  }

  private async _handleStopTask(
    entityId: string,
    hostKey?: string
  ): Promise<void> {
    if (!this.hass || !this._config?.entity) return;
    const targetEntity = entityId || this._config.entity;
    const stateObj = this.hass.states[targetEntity];
    const attrs = stateObj?.attributes || {};
    const targetHost =
      hostKey || attrs.host_key || this._transcript?.host_key;

    await this._executeService("cancel_task", {
      entity_id: targetEntity,
      host_key: targetHost,
    });
  }

  private _renderProgressingStep(step: ProgressingStep): TemplateResult {
    const text = step.title || step.name || step.text || "Working…";
    return html`
      <div class="progressing-step-item">
        <span class="spinner"></span>
        <span class="progressing-step-content">
          <span>${text}</span>
          ${step.description
            ? html`<span class="progressing-step-description"
                >${step.description}</span
              >`
            : ""}
        </span>
      </div>
    `;
  }

  private _renderTranscriptItem(item: ReadyStepItem): TemplateResult {
    const itemType = item.type;

    if (itemType === "user-prompt") {
      const text = item.prompt || item.text || "";
      return html`
        <div class="transcript-item item-user-prompt">
          <div class="bubble-header">
            <span class="bubble-role">User</span>
          </div>
          <div class="bubble-content">${text}</div>
        </div>
      `;
    }

    if (itemType === "user-response") {
      const prompt = item.prompt || "";
      const response = item.displayText || item.text || "";
      return html`
        <div class="transcript-item item-user-response">
          <div class="bubble-header">
            <span class="bubble-role">Response</span>
          </div>
          ${prompt && response
            ? html`<div class="response-prompt">Prompt: ${prompt}</div>`
            : ""}
          <div class="bubble-content">${response || prompt}</div>
        </div>
      `;
    }

    if (itemType === "system-message") {
      const text = item.text || item.message || "";
      const level = item.level || "info";
      const icon = level === "error" ? "❌" : level === "warning" ? "⚠️" : "ℹ️";
      return html`
        <div class="transcript-item item-system-message level-${level}">
          <span>${icon}</span>
          <span>${text}</span>
          ${item.details
            ? html`<span class="item-system-message-details"
                >${item.details}</span
              >`
            : ""}
        </div>
      `;
    }

    if (itemType === "skills-status") {
      const text = item.status || item.text || "";
      const newSkills = Array.isArray(item.newSkills) ? item.newSkills : [];
      const failedSkills = Array.isArray(item.failedSkills)
        ? item.failedSkills
        : [];
      return html`
        <div class="transcript-item item-skills-status">
          <span class="skills-label">Skills:</span>
          <span>${text}</span>
          ${newSkills.length > 0
            ? html`<span class="skills-detail"
                >New: ${newSkills.join(", ")}</span
              >`
            : ""}
          ${failedSkills.length > 0
            ? html`<span class="skills-detail"
                >Failed: ${failedSkills
                  .map((skill) => {
                    if (typeof skill === "string") return skill;
                    const detail =
                      skill.error || skill.message || skill.reason || "";
                    return [skill.path || skill.name, detail]
                      .filter(Boolean)
                      .join(": ");
                  })
                  .join(", ")}</span
              >`
            : ""}
        </div>
      `;
    }

    // Agent Step / Result items
    const vm = item.vm;
    const isResult =
      vm?.type === "result" ||
      item.type === "result" ||
      item.status === "result" ||
      item.result !== undefined;

    let badgeText = "Step";
    let badgeClass = "badge-step";

    if (isResult) {
      const status = (vm?.status || item.status || "").toLowerCase();
      const errorCode = vm?.errorCode || item.errorCode;
      const isCancelled = Boolean(vm?.cancelled || item.cancelled);
      if (errorCode || status === "error" || status === "failed") {
        badgeText = "Task Error";
        badgeClass = "badge-error";
      } else if (isCancelled || status === "cancelled") {
        badgeText = "Task Cancelled";
        badgeClass = "badge-cancelled";
      } else {
        badgeText = "Task Result:";
        badgeClass = "badge-result";
      }
    }

    const stepTitle =
      vm?.title ||
      vm?.name ||
      item.title ||
      item.name ||
      (isResult ? "Task Result" : "Step");
    const description = vm?.description || item.description;
    const errorCode = vm?.errorCode || item.errorCode;
    const content =
      vm?.text ||
      vm?.result ||
      item.text ||
      item.result ||
      "";
    const changes = vm?.changesSummary || item.changesSummary;

    return html`
      <div class="transcript-item item-step">
        <div class="step-header">
          <span class="step-badge ${badgeClass}">${badgeText}</span>
          <span class="step-title">${stepTitle}</span>
        </div>
        ${errorCode
          ? html`<div class="step-error-code">Error: ${errorCode}</div>`
          : ""}
        ${description
          ? html`<div class="step-description">
              ${renderMarkdown(description)}
            </div>`
          : ""}
        ${content ? renderMarkdown(content) : ""}
        ${changes ? renderChangesSummary(changes) : ""}
      </div>
    `;
  }
}

// Existing definitions cannot be replaced; a full page reload loads updated code.
if (!customElements.get("junie-remote-card")) {
  customElements.define("junie-remote-card", JunieRemoteCard);
}
