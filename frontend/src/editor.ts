// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Peter Lawler

import { LitElement, html, css, TemplateResult } from "lit";
import { property, state } from "lit/decorators.js";
import { HomeAssistant, JunieRemoteCardConfig } from "./types";

export class JunieRemoteCardEditor extends LitElement {
  @property({ attribute: false }) public hass?: HomeAssistant;
  @state() private _config?: JunieRemoteCardConfig;

  public setConfig(config: JunieRemoteCardConfig): void {
    this._config = { ...config };
  }

  private _valueChanged(ev: Event): void {
    if (!this._config) {
      return;
    }
    const target = ev.target as HTMLInputElement | HTMLSelectElement;
    const field = target.getAttribute("data-field");
    if (!field) {
      return;
    }
    const value = target.value;
    if (this._config[field] === value) {
      return;
    }

    const newConfig: JunieRemoteCardConfig = {
      ...this._config,
      [field]: value,
    };
    this._config = newConfig;

    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: newConfig },
        bubbles: true,
        composed: true,
      })
    );
  }

  static get styles() {
    return css`
      .card-config {
        display: flex;
        flex-direction: column;
        gap: 16px;
        padding: 8px 0;
      }
      .form-row {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .form-label {
        font-weight: 500;
        font-size: 0.95rem;
        color: var(--primary-text-color, #212121);
      }
      .form-help {
        font-size: 0.8rem;
        color: var(--secondary-text-color, #757575);
      }
      .editor-input,
      .editor-select {
        box-sizing: border-box;
        width: 100%;
        padding: 10px 12px;
        border-radius: 4px;
        border: 1px solid var(--divider-color, #e0e0e0);
        background: var(--card-background-color, #ffffff);
        color: var(--primary-text-color, #212121);
        font-size: 0.95rem;
        outline: none;
        transition: border-color 0.2s;
      }
      .editor-input:focus,
      .editor-select:focus {
        border-color: var(--primary-color, #0288d1);
      }
    `;
  }

  protected render(): TemplateResult {
    if (!this.hass) {
      return html`<div>Home Assistant instance not available</div>`;
    }

    const currentEntity = this._config?.entity || "";

    // Discover matching Junie Remote entities
    const discovered: Array<{ id: string; name: string }> = [];
    if (this.hass.states) {
      for (const [id, stateObj] of Object.entries(this.hass.states)) {
        if (
          id.startsWith("sensor.") &&
          (stateObj.attributes?.host_key !== undefined ||
            stateObj.attributes?.tunnel_id !== undefined ||
            id.includes("junie"))
        ) {
          const name =
            stateObj.attributes?.friendly_name ||
            stateObj.attributes?.title ||
            stateObj.attributes?.host_key ||
            id;
          discovered.push({ id, name: `${name} (${id})` });
        }
      }
    }

    // Ensure currently configured entity is present in list
    if (
      currentEntity &&
      !discovered.some((entry) => entry.id === currentEntity)
    ) {
      discovered.unshift({ id: currentEntity, name: currentEntity });
    }

    return html`
      <div class="card-config">
        <div class="form-row">
          <label class="form-label" for="entity-picker">Status Sensor Entity (required)</label>
          ${discovered.length > 0
            ? html`
                <select
                  id="entity-picker"
                  class="editor-select"
                  data-field="entity"
                  .value="${currentEntity}"
                  @change="${this._valueChanged}"
                >
                  <option value="" disabled ?selected="${!currentEntity}">
                    Select a Junie Remote sensor
                  </option>
                  ${discovered.map(
                    (item) => html`
                      <option
                        value="${item.id}"
                        ?selected="${item.id === currentEntity}"
                      >
                        ${item.name}
                      </option>
                    `
                  )}
                </select>
              `
            : ""}
          <input
            class="editor-input"
            type="text"
            data-field="entity"
            .value="${currentEntity}"
            placeholder="sensor.alice_linux_my_project_status"
            @input="${this._valueChanged}"
          />
          <span class="form-help">
            The Home Assistant sensor entity tracking your Junie CLI session.
          </span>
        </div>

        <div class="form-row">
          <label class="form-label" for="card-title">Card Title (optional)</label>
          <input
            id="card-title"
            class="editor-input"
            type="text"
            data-field="title"
            .value="${this._config?.title || ""}"
            placeholder="JetBrains Junie Remote (default)"
            @input="${this._valueChanged}"
          />
          <span class="form-help">
            Custom card header title override.
          </span>
        </div>

        <div class="form-row">
          <label class="form-label" for="max-height">Max Height (optional)</label>
          <input
            id="max-height"
            class="editor-input"
            type="text"
            data-field="max_height"
            .value="${this._config?.max_height || "520px"}"
            placeholder="520px"
            @input="${this._valueChanged}"
          />
          <span class="form-help">
            Maximum CSS height for the scrollable transcript container (e.g., 520px or 60vh).
          </span>
        </div>
      </div>
    `;
  }
}

// The first definition wins until the page is fully reloaded.
if (!customElements.get("junie-remote-card-editor")) {
  customElements.define("junie-remote-card-editor", JunieRemoteCardEditor);
}
