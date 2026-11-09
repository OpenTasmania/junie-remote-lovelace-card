// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Peter Lawler

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { Window as HappyWindow } from "happy-dom";
import "../index";
import { JunieRemoteCard } from "../index";
import { JunieRemoteCardEditor } from "../editor";
import {
  escapeHtml,
  parseInlineMarkdown,
  markdownToHtml,
  renderChangesSummary,
} from "../markdown";
import { HomeAssistant, TranscriptDocument } from "../types";

describe("entity isolation and transcript freshness", () => {
  let card: JunieRemoteCard;
  const config = (entity: string) => ({ type: "custom:junie-remote-card", entity });
  const entity = (id: string, url: string | null, version?: string | null) => ({
    entity_id: id, state: "idle", last_changed: "", last_updated: "",
    attributes: { connection_status: "connected", transcript_json_url: url, transcript_updated_at: version },
  });
  const doc = (text: string) => ({
    host_key: "private-host", tunnel_id: "tunnel", updated_at: "now",
    connection_status: "connected", metadata: {}, session_status: "idle",
    can_send_prompt: true, brave_mode: false, has_plan: false,
    model_selection: { options: [] }, history: [{ type: "user-prompt", prompt: text }],
    progressing_steps: [], plan_proposal: null,
    active_requests: [{ type: "ask", id: "same-id", question: "private question" }],
  });
  const response = (text: string) => ({ ok: true, json: async () => doc(text) } as Response);
  const flush = async () => { await new Promise((resolve) => setTimeout(resolve, 0)); await card.updateComplete; };

  beforeEach(() => { card = new JunieRemoteCard(); document.body.appendChild(card); });
  afterEach(() => { card.remove(); vi.restoreAllMocks(); });

  it("clears old content and drafts on a switch with identical URL and version, even if replacement fails", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(response("private history"))
      .mockRejectedValueOnce(new Error("replacement failed"));
    card.setConfig(config("sensor.a"));
    card.hass = { states: { "sensor.a": entity("sensor.a", "/same", "v1"), "sensor.b": entity("sensor.b", "/same", "v1") }, callService: vi.fn() };
    await flush();
    expect(card.shadowRoot?.textContent).toContain("private history");
    const input = card.shadowRoot?.querySelector(".prompt-textarea") as HTMLTextAreaElement;
    input.value = "private draft"; input.dispatchEvent(new Event("input"));
    card.setConfig(config("sensor.b"));
    await flush();
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(card.shadowRoot?.textContent).not.toContain("private history");
    expect(card.shadowRoot?.textContent).not.toContain("private question");
    expect(card.shadowRoot?.textContent).toContain("replacement failed");
    expect((card.shadowRoot?.querySelector(".prompt-textarea") as HTMLTextAreaElement).value).toBe("");
  });

  it("invalidates an old fetch on disappearance and refetches an identical restored entity", async () => {
    let resolveOld!: (r: Response) => void;
    const fetcher = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(response("restored"));
    card.setConfig(config("sensor.a"));
    const hass = { states: { "sensor.a": entity("sensor.a", "/same", "v1") }, callService: vi.fn() };
    card.hass = hass; await card.updateComplete;
    card.hass = { ...hass, states: {} }; await card.updateComplete;
    card.hass = hass; await flush();
    resolveOld(response("stale")); await flush();
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(card.shadowRoot?.textContent).toContain("restored");
    expect(card.shadowRoot?.textContent).not.toContain("stale");
  });

  it("invalidates a pending fetch if versions change away and back before a render", async () => {
    let resolveOld!: (r: Response) => void;
    const fetcher = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(response("current"));
    const hass = { states: { "sensor.a": entity("sensor.a", "/same", "v1") }, callService: vi.fn() };
    card.setConfig(config("sensor.a")); card.hass = hass; await card.updateComplete;
    card.hass = { ...hass, states: { "sensor.a": entity("sensor.a", "/same", "v2") } };
    card.hass = { ...hass };
    resolveOld(response("stale")); await flush();
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(card.shadowRoot?.textContent).toContain("current");
    expect(card.shadowRoot?.textContent).not.toContain("stale");
  });

  it("does not let an A→B→A service completion erase a new draft or report an old error", async () => {
    let reject!: (reason: Error) => void;
    const callService = vi.fn(() => new Promise((_, r) => { reject = r; }));
    card.setConfig(config("sensor.a"));
    card.hass = { states: { "sensor.a": entity("sensor.a", null), "sensor.b": entity("sensor.b", null) }, callService };
    await card.updateComplete;
    const input = card.shadowRoot?.querySelector(".prompt-textarea") as HTMLTextAreaElement;
    input.value = "old"; input.dispatchEvent(new Event("input"));
    const pending = (card as any)._submitPrompt("sensor.a");
    card.setConfig(config("sensor.b")); card.setConfig(config("sensor.a"));
    await card.updateComplete;
    const next = card.shadowRoot?.querySelector(".prompt-textarea") as HTMLTextAreaElement;
    next.value = "new draft"; next.dispatchEvent(new Event("input"));
    reject(new Error("old error")); await pending; await card.updateComplete;
    expect(next.value).toBe("new draft");
    expect(card.shadowRoot?.textContent).not.toContain("old error");
  });

  it("keeps a new pending send disabled when an older send completes", async () => {
    const resolve: Array<() => void> = [];
    const callService = vi.fn(() => new Promise<void>((r) => { resolve.push(r); }));
    card.setConfig(config("sensor.a"));
    card.hass = { states: { "sensor.a": entity("sensor.a", null), "sensor.b": entity("sensor.b", null) }, callService };
    await card.updateComplete;
    let input = card.shadowRoot?.querySelector(".prompt-textarea") as HTMLTextAreaElement;
    input.value = "old"; input.dispatchEvent(new Event("input"));
    const old = (card as any)._submitPrompt("sensor.a");
    card.setConfig(config("sensor.b")); await card.updateComplete;
    input = card.shadowRoot?.querySelector(".prompt-textarea") as HTMLTextAreaElement;
    input.value = "new"; input.dispatchEvent(new Event("input"));
    const current = (card as any)._submitPrompt("sensor.b"); await card.updateComplete;
    expect((card.shadowRoot?.querySelector(".send-btn") as HTMLButtonElement).disabled).toBe(true);
    resolve[0](); await old; await card.updateComplete;
    expect((card.shadowRoot?.querySelector(".send-btn") as HTMLButtonElement).disabled).toBe(true);
    expect(input.value).toBe("new");
    resolve[1](); await current; await card.updateComplete;
    expect(input.value).toBe("");
  });

  it("ignores a late failure after switching to an entity without a URL", async () => {
    let reject!: (reason: Error) => void;
    vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => new Promise((_, r) => { reject = r; }));
    card.setConfig(config("sensor.a"));
    card.hass = { states: { "sensor.a": entity("sensor.a", "/a", "v1"), "sensor.b": entity("sensor.b", null) }, callService: vi.fn() };
    await card.updateComplete;
    card.setConfig(config("sensor.b")); await card.updateComplete;
    reject(new Error("old fetch failed")); await flush();
    expect(card.shadowRoot?.textContent).not.toContain("old fetch failed");
    expect(card.shadowRoot?.textContent).not.toContain("private-host");
    expect(card.shadowRoot?.textContent).not.toContain("private question");
  });

  it("does not dispatch a stale takeover control against a newly configured entity", async () => {
    const callService = vi.fn().mockResolvedValue(undefined);
    const a = { ...entity("sensor.a", null), state: "rejected" };
    const b = { ...entity("sensor.b", null), state: "rejected" };
    card.setConfig(config("sensor.a"));
    card.hass = { states: { "sensor.a": a, "sensor.b": b }, callService };
    await card.updateComplete;
    const takeover = card.shadowRoot?.querySelector(".takeover-btn") as HTMLButtonElement;
    expect(takeover).not.toBeNull();
    card.setConfig(config("sensor.b"));
    takeover.click();
    expect(callService).not.toHaveBeenCalled();
    await card.updateComplete;
  });

  it("ignores input events from the previous entity before the new render", async () => {
    card.setConfig(config("sensor.a"));
    card.hass = { states: { "sensor.a": entity("sensor.a", null), "sensor.b": entity("sensor.b", null) }, callService: vi.fn() };
    await card.updateComplete;
    const oldInput = card.shadowRoot?.querySelector(".prompt-textarea") as HTMLTextAreaElement;
    card.setConfig(config("sensor.b"));
    oldInput.value = "old input";
    oldInput.dispatchEvent(new Event("input", { bubbles: true }));
    await card.updateComplete;
    expect((card.shadowRoot?.querySelector(".prompt-textarea") as HTMLTextAreaElement).value).toBe("");
  });

  it("requests fresh unchanged signed URLs only when the normalized version changes", async () => {
    const url = "https://s3.example/latest.json?X-Amz-Signature=abc";
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(response("history"));
    card.setConfig(config("sensor.a"));
    const hass = { states: { "sensor.a": entity("sensor.a", url) }, callService: vi.fn() };
    card.hass = hass; await flush();
    for (const version of [null, "", undefined]) {
      card.hass = { ...hass, states: { "sensor.a": entity("sensor.a", url, version) } }; await flush();
    }
    expect(fetcher).toHaveBeenCalledTimes(1);
    card.hass = { ...hass, states: { "sensor.a": entity("sensor.a", url, "v2") } }; await flush();
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher).toHaveBeenLastCalledWith(url, { cache: "no-store" });
  });

  it("preserves same-entity drafts on cosmetic edits and isolates independent cards", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response("history"));
    const other = new JunieRemoteCard();
    document.body.appendChild(other);
    try {
      const hass = { states: { "sensor.a": entity("sensor.a", "/a", "v1"), "sensor.b": entity("sensor.b", "/b", "v1") }, callService: vi.fn() };
      card.setConfig(config("sensor.a")); card.hass = hass;
      other.setConfig(config("sensor.b")); other.hass = hass;
      await flush(); await other.updateComplete;
      const input = card.shadowRoot?.querySelector(".prompt-textarea") as HTMLTextAreaElement;
      input.value = "draft"; input.dispatchEvent(new Event("input"));
      card.setConfig({ ...config("sensor.a"), title: "New title", max_height: "600px" });
      await card.updateComplete;
      expect(input.value).toBe("draft");
      card.setConfig(config("sensor.b")); await card.updateComplete;
      expect(other.shadowRoot?.textContent).toContain("history");
    } finally { other.remove(); }
  });

  it("clears content and error on URL loss after a failed refresh, then refetches", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(response("old history"))
      .mockRejectedValueOnce(new Error("refresh failed"))
      .mockResolvedValueOnce(response("returned history"));
    const hass = { states: { "sensor.a": entity("sensor.a", "/a", "v1") }, callService: vi.fn() };
    card.setConfig(config("sensor.a")); card.hass = hass; await flush();
    card.hass = { ...hass, states: { "sensor.a": entity("sensor.a", "/a", "v2") } }; await flush();
    expect(card.shadowRoot?.textContent).toContain("refresh failed");
    card.hass = { ...hass, states: { "sensor.a": entity("sensor.a", null) } }; await flush();
    expect(card.shadowRoot?.textContent).not.toContain("old history");
    expect(card.shadowRoot?.textContent).not.toContain("private question");
    expect(card.shadowRoot?.textContent).not.toContain("refresh failed");
    card.hass = hass; await flush();
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(card.shadowRoot?.textContent).toContain("returned history");
  });

  it.each(["http", "json"])("retries %s errors on the next hass update", async (failure) => {
    const bad = failure === "http"
      ? new Response(null, { status: 304, statusText: "Not Modified" })
      : new Response("not-json", { status: 200 });
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(bad)
      .mockResolvedValueOnce(response("retried"));
    const hass = { states: { "sensor.a": entity("sensor.a", "/local/latest.json?t=1", "v1") }, callService: vi.fn() };
    card.setConfig(config("sensor.a")); card.hass = hass; await flush();
    expect(card.shadowRoot?.textContent).toContain(failure === "http" ? "HTTP 304" : "JSON");
    card.hass = { ...hass }; await flush();
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(card.shadowRoot?.textContent).toContain("retried");
  });

  it("ignores a stale successful ask completion for a reused request ID", async () => {
    let resolve!: () => void;
    const callService = vi.fn(() => new Promise<void>((r) => { resolve = r; }));
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response("history"));
    card.setConfig(config("sensor.a"));
    card.hass = { states: { "sensor.a": entity("sensor.a", "/a", "v1"), "sensor.b": entity("sensor.b", "/b", "v1") }, callService };
    await flush();
    let input = card.shadowRoot?.querySelector(".ask-input") as HTMLInputElement;
    input.value = "old"; input.dispatchEvent(new Event("input"));
    const pending = (card as any)._submitAsk({ type: "ask" }, "same-id", undefined, "sensor.a");
    card.setConfig(config("sensor.b")); await flush();
    input = card.shadowRoot?.querySelector(".ask-input") as HTMLInputElement;
    input.value = "new"; input.dispatchEvent(new Event("input"));
    resolve(); await pending; await card.updateComplete;
    expect(input.value).toBe("new");
  });

  it("keeps new asynchronous ask inputs and selections after an old completion", async () => {
    let resolve!: () => void;
    const callService = vi.fn(() => new Promise<void>((r) => { resolve = r; }));
    const asyncDoc = { ...doc("history"), active_requests: [{
      type: "ask-async", id: "same-id", question: "choose", options: [{ id: "one", label: "One" }],
    }] };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => asyncDoc } as Response);
    card.setConfig(config("sensor.a"));
    card.hass = { states: { "sensor.a": entity("sensor.a", "/a", "v1"), "sensor.b": entity("sensor.b", "/b", "v1") }, callService };
    await flush();
    const pending = (card as any)._submitAskAsync({ type: "ask-async" }, "same-id", undefined, "sensor.a");
    card.setConfig(config("sensor.b")); await flush();
    const input = card.shadowRoot?.querySelector(".ask-async-input") as HTMLInputElement;
    input.value = "new"; input.dispatchEvent(new Event("input"));
    (card.shadowRoot?.querySelector(".ask-async-opt-btn") as HTMLButtonElement).click();
    await card.updateComplete;
    resolve(); await pending; await card.updateComplete;
    expect(input.value).toBe("new");
    expect(card.shadowRoot?.querySelector(".ask-async-opt-btn")?.classList.contains("selected")).toBe(true);
  });
});

describe("independent bundle registrations", () => {
  it.each([{ names: [] }, { names: ["card"] }, { names: ["editor"] }, { names: ["card", "editor"] }])("keeps existing definitions with pre-registered $names", async ({ names }) => {
    const registry = new HappyWindow().customElements as unknown as CustomElementRegistry;
    class OldCard extends HTMLElement {}
    class OldEditor extends HTMLElement {}
    if (names.includes("card")) registry.define("junie-remote-card", OldCard);
    if (names.includes("editor")) registry.define("junie-remote-card-editor", OldEditor);
    vi.stubGlobal("customElements", registry);
    const originalCards = window.customCards;
    window.customCards = [];
    try {
      vi.resetModules(); await import("../index");
      const cardConstructor = registry.get("junie-remote-card");
      const editorConstructor = registry.get("junie-remote-card-editor");
      vi.resetModules(); await import("../index");
      expect(registry.get("junie-remote-card")).toBe(cardConstructor);
      expect(registry.get("junie-remote-card-editor")).toBe(editorConstructor);
      expect(cardConstructor).toBeDefined();
      expect(editorConstructor).toBeDefined();
      if (names.includes("card")) expect(cardConstructor).toBe(OldCard);
      if (names.includes("editor")) expect(editorConstructor).toBe(OldEditor);
      expect(window.customCards.filter((entry) => entry.type === "junie-remote-card")).toHaveLength(1);
    } finally { window.customCards = originalCards; vi.unstubAllGlobals(); }
  });
});

describe("Markdown Renderer", () => {
  it("escapes raw HTML to prevent XSS", () => {
    const raw = '<script>alert("XSS")</script>&"\'';
    const escaped = escapeHtml(raw);
    expect(escaped).not.toContain("<script>");
    expect(escaped).toContain("&lt;script&gt;");
    expect(escaped).toContain("&amp;");
    expect(escaped).toContain("&quot;");
    expect(escaped).toContain("&#39;");
  });

  it("parses inline formatting and sanitizes links", () => {
    const md =
      "Hello **bold** *italic* `const x = 1` ~~struck~~ [Safe Link](https://example.com) [XSS](javascript:alert(1))";
    const parsed = parseInlineMarkdown(md);
    expect(parsed).toContain("<strong>bold</strong>");
    expect(parsed).toContain("<em>italic</em>");
    expect(parsed).toContain("<code>const x = 1</code>");
    expect(parsed).toContain("<del>struck</del>");
    expect(parsed).toContain(
      '<a href="https://example.com" target="_blank" rel="noopener noreferrer">Safe Link</a>'
    );
    expect(parsed).not.toContain("javascript:");
    expect(parsed).toContain("XSS");
  });

  it("renders headings, blockquotes, lists, and fenced code blocks", () => {
    const doc = [
      "# Heading 1",
      "## Heading 2",
      "> Quoted text",
      "- item 1",
      "- item 2",
      "```typescript",
      "const answer: number = 42;",
      "```",
    ].join("\n");

    const html = markdownToHtml(doc);
    expect(html).toContain("<h3>Heading 1</h3>");
    expect(html).toContain("<h4>Heading 2</h4>");
    expect(html).toContain("<blockquote>Quoted text</blockquote>");
    expect(html).toContain("<ul>");
    expect(html).toContain("<li>item 1</li>");
    expect(html).toContain("<li>item 2</li>");
    expect(html).toContain("</ul>");
    expect(html).toContain('class="code-block-wrapper"');
    expect(html).toContain('<span class="code-lang">typescript</span>');
    expect(html).toContain('class="copy-btn"');
    expect(html).toContain("const answer: number = 42;");
  });

  it("renders changes summary badges", () => {
    const changes = [
      { path: "src/types.ts", action: "modified", added: 10, deleted: 2 },
      { path: "src/new.ts", action: "created" },
      { path: "src/old.ts", action: "deleted" },
      "src/plain.ts",
    ];

    const result = renderChangesSummary(changes);
    expect(result).toBeDefined();
  });
});

describe("JunieRemoteCard Configuration & Statics", () => {
  it("returns editor instance from getConfigElement", () => {
    const el = JunieRemoteCard.getConfigElement();
    expect(el).toBeInstanceOf(HTMLElement);
    expect(el.tagName.toLowerCase()).toBe("junie-remote-card-editor");
  });

  it("provides stub configuration auto-selecting first junie entity", () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.temperature": {
          entity_id: "sensor.temperature",
          state: "20",
          attributes: {},
          last_changed: "",
          last_updated: "",
        },
        "sensor.junie_alice_status": {
          entity_id: "sensor.junie_alice_status",
          state: "idle",
          attributes: { host_key: "alice_host" },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: vi.fn(),
    };

    const stub = JunieRemoteCard.getStubConfig(mockHass);
    expect(stub.type).toBe("custom:junie-remote-card");
    expect(stub.entity).toBe("sensor.junie_alice_status");
  });

  it("throws on invalid configuration", () => {
    const card = new JunieRemoteCard();
    expect(() => card.setConfig(null as any)).toThrowError(
      /configuration object is required/
    );
    expect(() =>
      card.setConfig({ type: "custom:junie-remote-card" } as any)
    ).toThrowError(/'entity' is required/);
  });

  it("accepts valid configuration and reports card size", () => {
    const card = new JunieRemoteCard();
    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
      title: "My Junie Card",
      max_height: "600px",
    });
    expect(card.getCardSize()).toBeGreaterThanOrEqual(4);
  });
});

describe("Visual Card Editor", () => {
  let editor: JunieRemoteCardEditor;

  beforeEach(() => {
    editor = new JunieRemoteCardEditor();
    document.body.appendChild(editor);
  });

  afterEach(() => {
    if (editor.isConnected) {
      document.body.removeChild(editor);
    }
  });

  it("renders form fields and emits config-changed on entity selection", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_host_a": {
          entity_id: "sensor.junie_host_a",
          state: "idle",
          attributes: {
            host_key: "host_a",
            friendly_name: "Host Alpha",
          },
          last_changed: "",
          last_updated: "",
        },
        "sensor.junie_host_b": {
          entity_id: "sensor.junie_host_b",
          state: "working",
          attributes: {
            host_key: "host_b",
            friendly_name: "Host Beta",
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: vi.fn(),
    };

    editor.hass = mockHass;
    editor.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_host_a",
    });

    await editor.updateComplete;

    const select = editor.shadowRoot?.querySelector(
      "select.editor-select"
    ) as HTMLSelectElement | null;
    expect(select).not.toBeNull();
    expect(select?.value).toBe("sensor.junie_host_a");

    // Listen for config-changed
    let emittedConfig: any = null;
    editor.addEventListener("config-changed", (e: any) => {
      emittedConfig = e.detail.config;
    });

    // Simulate selecting Host Beta
    select!.value = "sensor.junie_host_b";
    select!.dispatchEvent(new Event("change"));

    expect(emittedConfig).not.toBeNull();
    expect(emittedConfig.entity).toBe("sensor.junie_host_b");
  });

  it("emits config-changed when title or max_height is changed", async () => {
    editor.hass = { states: {}, callService: vi.fn() };
    editor.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_test",
    });

    await editor.updateComplete;

    let emittedConfig: any = null;
    editor.addEventListener("config-changed", (e: any) => {
      emittedConfig = e.detail.config;
    });

    const titleInput = editor.shadowRoot?.querySelector(
      "input#card-title"
    ) as HTMLInputElement;
    expect(titleInput).not.toBeNull();
    titleInput.value = "Custom Junie Header";
    titleInput.dispatchEvent(new Event("input"));

    expect(emittedConfig).not.toBeNull();
    expect(emittedConfig.title).toBe("Custom Junie Header");
  });
});

describe("Host Status Header Bar & State Rendering", () => {
  let card: JunieRemoteCard;

  beforeEach(() => {
    card = new JunieRemoteCard();
    document.body.appendChild(card);
  });

  afterEach(() => {
    if (card.isConnected) {
      document.body.removeChild(card);
    }
  });

  it("renders host identity, git repo badge, branch badge, working dir, and status pill", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "idle",
          attributes: {
            host_key: "dev_laptop",
            user_name: "alice",
            os_name: "Linux x86_64",
            git_repo: "git@github.com:opentasmania/junie-remote-lovelace-card.git",
            git_branch: "master",
            working_dir: "/home/alice/projects/junie-remote-lovelace-card",
            connection_status: "connected",
            session_status: "idle",
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: vi.fn(),
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;

    await card.updateComplete;

    const shadow = card.shadowRoot!;
    const text = shadow.textContent || "";

    // Host identity
    expect(text).toContain("alice");
    expect(text).toContain("Linux x86_64");

    // Git badges & Working dir
    expect(text).toContain("opentasmania/junie-remote-lovelace-card");
    expect(text).toContain("master");
    expect(text).toContain(
      "/home/alice/projects/junie-remote-lovelace-card"
    );

    // Status pill
    const statusPill = shadow.querySelector(".status-pill");
    expect(statusPill).not.toBeNull();
    expect(statusPill?.textContent).toContain("Connected · Idle");
    expect(statusPill?.classList.contains("status-idle")).toBe(true);

    // Takeover button is always present
    const takeoverBtn = shadow.querySelector(".takeover-btn");
    expect(takeoverBtn).not.toBeNull();
  });

  it("renders working and waiting-for-input session states correctly", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "working",
          attributes: {
            host_key: "dev_laptop",
            connection_status: "connected",
            session_status: "working",
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: vi.fn(),
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    expect(card.shadowRoot?.querySelector(".status-pill")?.textContent).toContain(
      "Working…"
    );

    // Change to waiting-for-input
    mockHass.states["sensor.junie_status"].state = "waiting-for-input";
    mockHass.states["sensor.junie_status"].attributes.session_status =
      "waiting-for-input";
    card.hass = { ...mockHass };
    await card.updateComplete;

    expect(card.shadowRoot?.querySelector(".status-pill")?.textContent).toContain(
      "Waiting for Input"
    );
  });

  it("renders takeover button on rejected status and calls kick_client service", async () => {
    const callServiceMock = vi.fn().mockResolvedValue({});
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "rejected",
          attributes: {
            host_key: "host_lockout_123",
            user_name: "alice",
            connection_status: "rejected",
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: callServiceMock,
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const shadow = card.shadowRoot!;
    const statusPill = shadow.querySelector(".status-pill");
    expect(statusPill?.textContent).toContain("Rejected (In Use)");

    const takeoverBtn = shadow.querySelector(
      ".takeover-btn"
    ) as HTMLButtonElement | null;
    expect(takeoverBtn).not.toBeNull();
    expect(takeoverBtn?.textContent).toContain("Take Over");

    // Click takeover button
    takeoverBtn?.click();
    await card.updateComplete;

    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "kick_client",
      {
        entity_id: "sensor.junie_status",
        host_key: "host_lockout_123",
      }
    );
  });
});

describe("Transcript Viewer (Consumer & Renderer)", () => {
  let card: JunieRemoteCard;

  beforeEach(() => {
    card = new JunieRemoteCard();
    document.body.appendChild(card);
    if (!navigator.clipboard) {
      Object.assign(navigator, {
        clipboard: {
          writeText: vi.fn().mockResolvedValue(undefined),
        },
      });
    } else {
      vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
    }
  });

  afterEach(() => {
    if (card.isConnected) {
      document.body.removeChild(card);
    }
    vi.restoreAllMocks();
  });

  it("renders welcome empty state when connected with empty history and idle status", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "idle",
          attributes: {
            connection_status: "connected",
            session_status: "idle",
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: vi.fn(),
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const welcome = card.shadowRoot?.querySelector(".welcome-empty-state");
    expect(welcome).not.toBeNull();
    expect(welcome?.textContent).toContain(
      "Welcome to Junie — What shall we build today?"
    );
  });

  it("renders last_step_preview fallback when transcript fetch is unavailable", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "working",
          attributes: {
            connection_status: "connected",
            session_status: "working",
            last_step_preview: "Analyzing workspace repository...",
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: vi.fn(),
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const preview = card.shadowRoot?.querySelector(".last-step-preview-box");
    expect(preview).not.toBeNull();
    expect(preview?.textContent).toContain("Analyzing workspace repository...");
  });

  it("fetches transcript_json_url and renders prompts, steps, markdown, code, and changesSummary", async () => {
    const sampleDoc: TranscriptDocument = {
      host_key: "test_host",
      tunnel_id: "tun_123",
      updated_at: "2026-11-07T00:00:00Z",
      connection_status: "connected",
      metadata: {
        title: "Test Task",
        user_name: "alice",
        os_name: "Linux",
      },
      session_status: "working",
      can_send_prompt: true,
      brave_mode: true,
      has_plan: false,
      model_selection: {
        current_model_id: "claude-3-7-sonnet",
        options: [{ value: "claude-3-7-sonnet", label: "Claude 3.7 Sonnet" }],
      },
      history: [
        {
          type: "user-prompt",
          prompt: "Please implement Stage 6 in TypeScript",
        },
        {
          type: "user-response",
          prompt: "Which setup should I use?",
          displayText: "Proceed with vitest setup",
        },
        {
          type: "system-message",
          text: "Tunnel connection verified",
          details: "Handshake details are available",
          level: "error",
        },
        {
          type: "skills-status",
          status: "Loaded 5 skills",
          newSkills: ["card-review"],
          failedSkills: [{ path: "skills/failed-skill.md", error: "invalid format" }],
        },
        {
          type: "step",
          vm: {
            type: "command",
            title: "Inspect changed files",
            description: "Read the test output before editing.",
          },
        },
        {
          type: "step",
          vm: {
            type: "result",
            status: "success",
            title: "Completed Step 1",
            description: "The implementation is ready for review.",
            text: "Created the test file.\n```typescript\nconst x: number = 100;\n```",
            changesSummary: [
              { path: "frontend/src/types.ts", action: "created", added: 250 },
            ],
          },
        },
        {
          type: "step",
          vm: {
            type: "result",
            errorCode: "TOOL_EXECUTION_FAILED",
            text: "The command could not be completed.",
          },
        },
        {
          type: "step",
          vm: {
            type: "result",
            cancelled: true,
            text: "The task was cancelled.",
          },
        },
      ],
      progressing_steps: [
        {
          type: "step",
          title: "Running vitest test suite...",
          description: "Checking the complete frontend suite.",
        },
      ],
      plan_proposal: null,
      active_requests: [],
    };

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => sampleDoc,
    } as Response);

    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "working",
          attributes: {
            host_key: "test_host",
            connection_status: "connected",
            session_status: "working",
            transcript_json_url: "https://storage.local/junie/test.json",
            transcript_updated_at: "2026-11-07T00:00:00Z",
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: vi.fn(),
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;

    await card.updateComplete;
    // Allow microtasks for fetch resolution
    await new Promise((resolve) => setTimeout(resolve, 50));
    await card.updateComplete;

    expect(fetchSpy).toHaveBeenCalledWith(
      "https://storage.local/junie/test.json", { cache: "no-store" }
    );

    const shadow = card.shadowRoot!;
    const content = shadow.textContent || "";

    // Prompts and responses
    expect(content).toContain("Please implement Stage 6 in TypeScript");
    expect(content).toContain("Which setup should I use?");
    expect(content).toContain("Proceed with vitest setup");

    // System message and skills status
    expect(content).toContain("Tunnel connection verified");
    expect(content).toContain("Handshake details are available");
    expect(content).toContain("Loaded 5 skills");
    expect(content).toContain("card-review");
    expect(content).toContain("skills/failed-skill.md");
    expect(content).toContain("invalid format");

    // Step descriptions and protocol-level errors
    expect(content).toContain("Read the test output before editing.");
    expect(content).toContain("The implementation is ready for review.");
    expect(content).toContain("TOOL_EXECUTION_FAILED");
    expect(
      card.shadowRoot?.querySelector(".badge-cancelled")?.textContent
    ).toContain("Task Cancelled");

    // Task Result badge and Markdown code block
    const resultBadge = shadow.querySelector(".badge-result");
    expect(resultBadge).not.toBeNull();
    expect(resultBadge?.textContent).toContain("Task Result:");

    const codeEl = shadow.querySelector("pre code");
    expect(codeEl).not.toBeNull();
    expect(codeEl?.textContent).toContain("const x: number = 100;");

    // Language badge
    const langBadge = shadow.querySelector(".code-lang");
    expect(langBadge?.textContent).toBe("typescript");

    // Changes summary badge
    const changeBadge = shadow.querySelector(".change-badge");
    expect(changeBadge).not.toBeNull();
    expect(changeBadge?.textContent).toContain("created");
    expect(changeBadge?.textContent).toContain("frontend/src/types.ts");

    // Progressing step with spinner
    const progressingStep = shadow.querySelector(".progressing-step-item");
    expect(progressingStep).not.toBeNull();
    expect(progressingStep?.textContent).toContain(
      "Running vitest test suite..."
    );
    expect(progressingStep?.textContent).toContain(
      "Checking the complete frontend suite."
    );
    expect(progressingStep?.querySelector(".spinner")).not.toBeNull();

    // Test copy button interaction
    const copyBtn = shadow.querySelector(
      ".copy-btn"
    ) as HTMLButtonElement | null;
    expect(copyBtn).not.toBeNull();
    copyBtn?.click();
    await card.updateComplete;
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "const x: number = 100;"
    );
  });

  it("keeps the newest transcript when an older fetch resolves last", async () => {
    const resolveFetch: Array<(response: Response) => void> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () => new Promise((resolve) => resolveFetch.push(resolve))
    );

    const makeTranscript = (prompt: string): TranscriptDocument =>
      ({
        host_key: "test_host",
        tunnel_id: "tun_123",
        updated_at: "2026-11-07T00:00:00Z",
        connection_status: "connected",
        metadata: {},
        history: [{ type: "user-prompt", prompt }],
      }) as TranscriptDocument;
    const makeHass = (url: string, updatedAt: string): HomeAssistant => ({
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "working",
          attributes: {
            connection_status: "connected",
            session_status: "working",
            transcript_json_url: url,
            transcript_updated_at: updatedAt,
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: vi.fn(),
    });

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = makeHass("https://storage.local/old.json", "old");
    await card.updateComplete;
    card.hass = makeHass("https://storage.local/new.json", "new");
    await card.updateComplete;

    resolveFetch[1]({
      ok: true,
      json: async () => makeTranscript("new transcript"),
    } as Response);
    await new Promise((resolve) => setTimeout(resolve, 0));
    await card.updateComplete;

    resolveFetch[0]({
      ok: true,
      json: async () => makeTranscript("stale transcript"),
    } as Response);
    await new Promise((resolve) => setTimeout(resolve, 0));
    await card.updateComplete;

    expect(card.shadowRoot?.textContent).toContain("new transcript");
    expect(card.shadowRoot?.textContent).not.toContain("stale transcript");
  });

  it("renders transcript fetch failures in the card", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new Error("transcript unavailable")
    );
    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "idle",
          attributes: {
            connection_status: "connected",
            session_status: "idle",
            transcript_json_url: "https://storage.local/unavailable.json",
            transcript_updated_at: "2026-11-07T00:00:00Z",
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: vi.fn(),
    };
    await card.updateComplete;
    await new Promise((resolve) => setTimeout(resolve, 0));
    await card.updateComplete;

    expect(card.shadowRoot?.querySelector('[role="alert"]')?.textContent).toContain(
      "transcript unavailable"
    );
  });

});

describe("Interactive Request Widgets (active-requests)", () => {
  let card: JunieRemoteCard;
  let callServiceMock: any;

  beforeEach(() => {
    card = new JunieRemoteCard();
    document.body.appendChild(card);
    callServiceMock = vi.fn().mockResolvedValue({});
  });

  afterEach(() => {
    if (card.isConnected) {
      document.body.removeChild(card);
    }
    vi.restoreAllMocks();
  });

  it("handles 'ask' request with text input and Send button or Enter submit", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "waiting-for-input",
          attributes: {
            host_key: "test_host",
            connection_status: "connected",
            session_status: "waiting-for-input",
            active_requests: [
              {
                requestId: "req_ask_1",
                type: "ask",
                question: "What is your target branch name?",
              },
            ],
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: callServiceMock,
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const shadow = card.shadowRoot!;
    const cardEl = shadow.querySelector(".active-request-card");
    expect(cardEl).not.toBeNull();
    expect(cardEl?.textContent).toContain(
      "What is your target branch name?"
    );

    const input = shadow.querySelector(".ask-input") as HTMLInputElement;
    const sendBtn = shadow.querySelector(
      ".ask-send-btn"
    ) as HTMLButtonElement;
    expect(input).not.toBeNull();
    expect(sendBtn).not.toBeNull();

    input.value = "feature/lovelace-v2";
    input.dispatchEvent(new Event("input"));
    await card.updateComplete;

    sendBtn.click();
    await card.updateComplete;

    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "respond_request",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
        request_id: "req_ask_1",
        method: "ask",
        display_text: "feature/lovelace-v2",
        response: "feature/lovelace-v2",
      }
    );
  });

  it("handles 'choice' request with multiple option buttons", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "waiting-for-input",
          attributes: {
            host_key: "test_host",
            connection_status: "connected",
            session_status: "waiting-for-input",
            active_requests: [
              {
                requestId: "req_choice_1",
                type: "choice",
                title: "Select deployment target",
                options: [
                  {
                    id: "opt_staging",
                    title: "Staging Server",
                    description: "Deploy to staging cluster",
                  },
                  {
                    id: "opt_prod",
                    title: "Production",
                    description: "Deploy to production environment",
                  },
                ],
              },
            ],
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: callServiceMock,
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const shadow = card.shadowRoot!;
    const optButtons = shadow.querySelectorAll(".choice-opt-btn");
    expect(optButtons.length).toBe(2);
    expect(optButtons[0].textContent).toContain("Staging Server");
    expect(optButtons[0].textContent).toContain("Deploy to staging cluster");
    expect(optButtons[1].textContent).toContain("Production");

    (optButtons[1] as HTMLButtonElement).click();
    await card.updateComplete;

    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "respond_request",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
        request_id: "req_choice_1",
        method: "choice",
        option_id: "opt_prod",
        display_text: "Production",
      }
    );
  });

  it("handles 'approve' request with allow-once, always-allow, and deny options", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "waiting-for-input",
          attributes: {
            host_key: "test_host",
            connection_status: "connected",
            session_status: "waiting-for-input",
            active_requests: [
              {
                requestId: "req_approve_1",
                type: "approve",
                title: "Run command: pytest tests/",
                options: [
                  { type: "allow-once", label: "Allow once", optionIndex: 0 },
                  {
                    type: "always-allow",
                    label: "Always allow pytest",
                    optionIndex: 1,
                  },
                  { type: "deny", label: "Deny", optionIndex: 2 },
                ],
              },
            ],
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: callServiceMock,
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const shadow = card.shadowRoot!;
    const approveBtns = shadow.querySelectorAll(".approve-opt-btn");
    expect(approveBtns.length).toBe(3);

    // 1. Always allow
    (approveBtns[1] as HTMLButtonElement).click();
    await card.updateComplete;
    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "respond_request",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
        request_id: "req_approve_1",
        method: "approve",
        approve: true,
        add_to_allow_list: true,
        option_index: 1,
        display_text: "Always allow pytest",
      }
    );

    // 2. Deny
    (approveBtns[2] as HTMLButtonElement).click();
    await card.updateComplete;
    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "respond_request",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
        request_id: "req_approve_1",
        method: "approve",
        approve: false,
        add_to_allow_list: false,
        option_index: 2,
        display_text: "Deny",
      }
    );

    // 3. Allow once
    (approveBtns[0] as HTMLButtonElement).click();
    await card.updateComplete;
    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "respond_request",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
        request_id: "req_approve_1",
        method: "approve",
        approve: true,
        add_to_allow_list: false,
        option_index: 0,
        display_text: "Allow once",
      }
    );
  });

  it("handles 'action' request with OK button", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "waiting-for-input",
          attributes: {
            host_key: "test_host",
            connection_status: "connected",
            session_status: "waiting-for-input",
            active_requests: [
              {
                requestId: "req_action_1",
                type: "action",
                title: "Process completed successfully",
              },
            ],
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: callServiceMock,
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const shadow = card.shadowRoot!;
    const okBtn = shadow.querySelector(
      ".action-ok-btn"
    ) as HTMLButtonElement;
    expect(okBtn).not.toBeNull();
    expect(okBtn.textContent?.trim()).toBe("OK");

    okBtn.click();
    await card.updateComplete;

    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "respond_request",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
        request_id: "req_action_1",
        method: "cancel",
        display_text: "OK",
      }
    );
  });

  it("handles 'ask-async' request with multiple selection and comments input", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "waiting-for-input",
          attributes: {
            host_key: "test_host",
            connection_status: "connected",
            session_status: "waiting-for-input",
            active_requests: [
              {
                requestId: "req_async_1",
                type: "ask-async",
                name: "Database migrations",
                question: "Select pending migrations to apply:",
                allowMultiple: true,
                options: [
                  { id: "mig_001", label: "001_initial_schema" },
                  { id: "mig_002", label: "002_add_index" },
                  { id: "mig_003", label: "003_add_constraints" },
                ],
              },
            ],
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: callServiceMock,
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const shadow = card.shadowRoot!;
    const optButtons = shadow.querySelectorAll(".ask-async-opt-btn");
    expect(optButtons.length).toBe(3);

    // Toggle mig_001 and mig_003
    (optButtons[0] as HTMLButtonElement).click();
    (optButtons[2] as HTMLButtonElement).click();
    await card.updateComplete;

    expect(optButtons[0].classList.contains("selected")).toBe(true);
    expect(optButtons[1].classList.contains("selected")).toBe(false);
    expect(optButtons[2].classList.contains("selected")).toBe(true);

    const input = shadow.querySelector(
      ".ask-async-input"
    ) as HTMLInputElement;
    input.value = "Skip 002 for now";
    input.dispatchEvent(new Event("input"));
    await card.updateComplete;

    const submitBtn = shadow.querySelector(
      ".ask-async-submit-btn"
    ) as HTMLButtonElement;
    submitBtn.click();
    await card.updateComplete;

    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "respond_request",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
        request_id: "req_async_1",
        method: "ask-async",
        option_ids: ["mig_001", "mig_003"],
        response: "Skip 002 for now",
        display_text: "Skip 002 for now",
      }
    );
  });
});

describe("Plan Proposal Drawer", () => {
  let card: JunieRemoteCard;
  let callServiceMock: any;

  beforeEach(() => {
    card = new JunieRemoteCard();
    document.body.appendChild(card);
    callServiceMock = vi.fn().mockResolvedValue({});
  });

  afterEach(() => {
    if (card.isConnected) {
      document.body.removeChild(card);
    }
    vi.restoreAllMocks();
  });

  it("renders Plan Proposal with Summary, Full Plan, Collapse views and handles Confirm & Refine", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "waiting-for-input",
          attributes: {
            host_key: "test_host",
            connection_status: "connected",
            session_status: "waiting-for-input",
            plan_summary: {
              ready_for_review: true,
              show_actions: true,
              plan_file_path: "/workspace/plan-v1.md",
              sections: [
                {
                  name: "Architecture",
                  content: "### System Architecture\nUses LitElement and HA services.",
                },
                {
                  name: "Verification",
                  content: "### Verification\nRun vitest and pytest.",
                },
              ],
              delivery_steps: [
                {
                  name: "Scaffold Components",
                  description: "Create LitElement structure",
                },
                {
                  name: "Add Unit Tests",
                  description: "Verify controls and responses",
                },
              ],
            },
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: callServiceMock,
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const shadow = card.shadowRoot!;
    const drawer = shadow.querySelector(".plan-proposal-drawer");
    expect(drawer).not.toBeNull();

    // Verify Ready for review badge
    const badge = drawer?.querySelector(".ready-badge");
    expect(badge).not.toBeNull();
    expect(badge?.textContent).toContain("Ready for review");

    // Verify plan file path
    const filePath = drawer?.querySelector(".plan-file-path");
    expect(filePath?.textContent).toContain("/workspace/plan-v1.md");

    // Summary view should be active by default and show delivery steps
    expect(drawer?.textContent).toContain("Scaffold Components");
    expect(drawer?.textContent).toContain("Create LitElement structure");

    // Switch to Full Plan view
    const fullPlanBtn = drawer?.querySelector(
      ".plan-btn-full"
    ) as HTMLButtonElement;
    expect(fullPlanBtn).not.toBeNull();
    fullPlanBtn.click();
    await card.updateComplete;

    const sectionTabs = drawer?.querySelectorAll(".plan-section-tab-btn");
    expect(sectionTabs?.length).toBe(3); // Architecture, Verification, Delivery Steps
    expect(sectionTabs?.[0].textContent?.trim()).toBe("Architecture");
    expect(sectionTabs?.[1].textContent?.trim()).toBe("Verification");
    expect(sectionTabs?.[2].textContent?.trim()).toBe("Delivery Steps");

    // Architecture content is rendered as markdown
    const content = drawer?.querySelector(".plan-section-content");
    expect(content?.textContent).toContain("System Architecture");

    // Collapse drawer
    const collapseBtn = drawer?.querySelector(
      ".plan-collapse-btn"
    ) as HTMLButtonElement;
    expect(collapseBtn.textContent?.trim()).toBe("Collapse");
    collapseBtn.click();
    await card.updateComplete;

    // Body is hidden, button changes to Review Plan
    expect(drawer?.querySelector(".plan-body")).toBeNull();
    expect(collapseBtn.textContent?.trim()).toBe("Review Plan");

    // Click Review Plan to reopen
    collapseBtn.click();
    await card.updateComplete;
    expect(drawer?.querySelector(".plan-body")).not.toBeNull();

    // Confirm and Implement button
    const confirmBtn = drawer?.querySelector(
      ".confirm-plan-btn"
    ) as HTMLButtonElement;
    expect(confirmBtn).not.toBeNull();
    confirmBtn.click();
    await card.updateComplete;

    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "confirm_plan",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
      }
    );

    // Refine Plan button
    const refineBtn = drawer?.querySelector(
      ".refine-plan-btn"
    ) as HTMLButtonElement;
    expect(refineBtn).not.toBeNull();
    refineBtn.click();
    await card.updateComplete;

    // Plan refinement mode banner should appear
    const banner = shadow.querySelector(".plan-mode-banner");
    expect(banner).not.toBeNull();
    expect(banner?.textContent).toContain("Plan > Iterating on plan");

    const textarea = shadow.querySelector(
      ".prompt-textarea"
    ) as HTMLTextAreaElement;
    expect(textarea.placeholder).toBe(
      "Describe how to refine the plan..."
    );

    // Enter refinement text and submit
    textarea.value = "Please include end-to-end integration tests";
    textarea.dispatchEvent(new Event("input"));
    await card.updateComplete;

    const steerBtn = shadow.querySelector(
      ".steer-btn"
    ) as HTMLButtonElement;
    expect(steerBtn).not.toBeNull();
    steerBtn.click();
    await new Promise((resolve) => setTimeout(resolve, 10));
    await card.updateComplete;

    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "send_plan_prompt",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
        prompt: "Please include end-to-end integration tests",
      }
    );

    // Mode should reset to normal
    expect(shadow.querySelector(".plan-mode-banner")).toBeNull();
  });
});

describe("Footer Control Bar & Prompt/Steer Input", () => {
  let card: JunieRemoteCard;
  let callServiceMock: any;

  beforeEach(() => {
    card = new JunieRemoteCard();
    document.body.appendChild(card);
    callServiceMock = vi.fn().mockResolvedValue({});
  });

  afterEach(() => {
    if (card.isConnected) {
      document.body.removeChild(card);
    }
    vi.restoreAllMocks();
  });

  it("toggles brave mode when button is clicked", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "idle",
          attributes: {
            host_key: "test_host",
            connection_status: "connected",
            session_status: "idle",
            brave_mode: false,
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: callServiceMock,
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const shadow = card.shadowRoot!;
    const braveBtn = shadow.querySelector(
      ".brave-toggle-btn"
    ) as HTMLButtonElement;
    expect(braveBtn).not.toBeNull();
    expect(braveBtn.getAttribute("aria-pressed")).toBe("false");

    braveBtn.click();
    await card.updateComplete;

    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "toggle_brave_mode",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
        enabled: true,
      }
    );

    // Now test with brave_mode active
    mockHass.states["sensor.junie_status"].attributes.brave_mode = true;
    card.hass = { ...mockHass };
    await card.updateComplete;

    expect(braveBtn.getAttribute("aria-pressed")).toBe("true");
    expect(braveBtn.textContent).toContain("⚑ Brave");

    braveBtn.click();
    await card.updateComplete;

    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "toggle_brave_mode",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
        enabled: false,
      }
    );
  });

  it("calls select_model service when model & effort dropdown is changed", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "idle",
          attributes: {
            host_key: "test_host",
            connection_status: "connected",
            session_status: "idle",
            current_model_id: "claude-3-7-sonnet",
            current_effort_id: "medium",
            selected_model_effort: "claude-3-7-sonnet:medium",
            model_options: [
              {
                value: "claude-3-7-sonnet:medium",
                label: "Claude 3.7 Sonnet · Medium",
              },
              {
                value: "gpt-4o:high",
                label: "GPT-4o · High",
              },
            ],
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: callServiceMock,
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const shadow = card.shadowRoot!;
    const select = shadow.querySelector(
      ".model-select"
    ) as HTMLSelectElement;
    expect(select).not.toBeNull();
    expect(select.value).toBe("claude-3-7-sonnet:medium");

    select.value = "gpt-4o:high";
    select.dispatchEvent(new Event("change"));
    await card.updateComplete;

    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "select_model",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
        model_id: "gpt-4o",
        effort_id: "high",
      }
    );
  });

  it("sends normal prompt when idle via Send button and Enter key", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "idle",
          attributes: {
            host_key: "test_host",
            connection_status: "connected",
            session_status: "idle",
            can_send_prompt: true,
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: callServiceMock,
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const shadow = card.shadowRoot!;
    const textarea = shadow.querySelector(
      ".prompt-textarea"
    ) as HTMLTextAreaElement;
    const sendBtn = shadow.querySelector(
      ".send-btn"
    ) as HTMLButtonElement;
    expect(textarea).not.toBeNull();
    expect(sendBtn).not.toBeNull();

    textarea.value = "Implement new dashboard";
    textarea.dispatchEvent(new Event("input"));
    await card.updateComplete;

    sendBtn.click();
    await card.updateComplete;

    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "send_prompt",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
        prompt: "Implement new dashboard",
      }
    );
  });

  it("reveals Steer button when typing in working state, and Stop button cancels task", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "working",
          attributes: {
            host_key: "test_host",
            connection_status: "connected",
            session_status: "working",
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: callServiceMock,
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const shadow = card.shadowRoot!;

    // When textarea is empty, only Stop button is visible
    expect(shadow.querySelector(".steer-btn")).toBeNull();
    const stopBtn = shadow.querySelector(
      ".stop-btn"
    ) as HTMLButtonElement;
    expect(stopBtn).not.toBeNull();

    stopBtn.click();
    await card.updateComplete;

    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "cancel_task",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
      }
    );

    // When typing text, Steer button appears
    const textarea = shadow.querySelector(
      ".prompt-textarea"
    ) as HTMLTextAreaElement;
    textarea.value = "Focus on frontend tests first";
    textarea.dispatchEvent(new Event("input"));
    await card.updateComplete;

    const steerBtn = shadow.querySelector(
      ".steer-btn"
    ) as HTMLButtonElement;
    expect(steerBtn).not.toBeNull();
    steerBtn.click();
    await card.updateComplete;

    expect(callServiceMock).toHaveBeenCalledWith(
      "junie_remote",
      "send_prompt",
      {
        entity_id: "sensor.junie_status",
        host_key: "test_host",
        prompt: "Focus on frontend tests first",
      }
    );
  });

  it("cancels plan mode on Escape key and cancel button", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "idle",
          attributes: {
            host_key: "test_host",
            connection_status: "connected",
            session_status: "idle",
            plan_summary: {
              ready_for_review: true,
              show_actions: true,
            },
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: callServiceMock,
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const shadow = card.shadowRoot!;
    const refineBtn = shadow.querySelector(
      ".refine-plan-btn"
    ) as HTMLButtonElement;
    refineBtn.click();
    await card.updateComplete;

    expect(shadow.querySelector(".plan-mode-banner")).not.toBeNull();

    // Press Escape key in textarea
    const textarea = shadow.querySelector(
      ".prompt-textarea"
    ) as HTMLTextAreaElement;
    textarea.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape" })
    );
    await card.updateComplete;

    expect(shadow.querySelector(".plan-mode-banner")).toBeNull();

    // Re-enter and cancel via cancel button
    refineBtn.click();
    await card.updateComplete;
    expect(shadow.querySelector(".plan-mode-banner")).not.toBeNull();

    const cancelBtn = shadow.querySelector(
      ".cancel-plan-mode-btn"
    ) as HTMLButtonElement;
    cancelBtn.click();
    await card.updateComplete;

    expect(shadow.querySelector(".plan-mode-banner")).toBeNull();
  });

  it("disables session controls and skips service calls while disconnected", async () => {
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "disconnected",
          attributes: {
            host_key: "test_host",
            connection_status: "disconnected",
            session_status: "idle",
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: callServiceMock,
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    const braveButton = card.shadowRoot?.querySelector(
      ".brave-toggle-btn"
    ) as HTMLButtonElement;
    expect(braveButton.disabled).toBe(true);
    braveButton.click();
    await card.updateComplete;

    expect(callServiceMock).not.toHaveBeenCalled();
    expect(card.shadowRoot?.querySelector('[role="status"]')?.textContent).toContain(
      "Controls are unavailable while disconnected"
    );
  });

  it("shows a visible error when a session action fails", async () => {
    callServiceMock.mockRejectedValue(new Error("service unavailable"));
    const mockHass: HomeAssistant = {
      states: {
        "sensor.junie_status": {
          entity_id: "sensor.junie_status",
          state: "idle",
          attributes: {
            host_key: "test_host",
            connection_status: "connected",
            session_status: "idle",
          },
          last_changed: "",
          last_updated: "",
        },
      },
      callService: callServiceMock,
    };

    card.setConfig({
      type: "custom:junie-remote-card",
      entity: "sensor.junie_status",
    });
    card.hass = mockHass;
    await card.updateComplete;

    (card.shadowRoot?.querySelector(".brave-toggle-btn") as HTMLButtonElement).click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    await card.updateComplete;

    expect(card.shadowRoot?.querySelector('[role="alert"]')?.textContent).toContain(
      "service unavailable"
    );
  });
});

describe("authenticated local transcripts and signed downloads", () => {
  let card: JunieRemoteCard;
  const LOCAL = "/api/junie_remote/transcripts/entry1/host-a";
  const config = (entity: string) => ({ type: "custom:junie-remote-card", entity });
  const entity = (id: string, json: string | null, md: string | null = null) => ({
    entity_id: id, state: "idle", last_changed: "", last_updated: "",
    attributes: {
      connection_status: "connected", transcript_json_url: json,
      transcript_md_url: md, transcript_updated_at: "v1",
    },
  });
  const body = {
    host_key: "private-host", tunnel_id: "t", updated_at: "now", connection_status: "connected",
    metadata: {}, session_status: "idle", can_send_prompt: true, brave_mode: false,
    has_plan: false, model_selection: { options: [] }, history: [{ type: "user-prompt", prompt: "secret prompt" }],
    progressing_steps: [], plan_proposal: null, active_requests: [],
  };
  const ok = () => ({ ok: true, json: async () => body } as Response);
  const flush = async () => { await new Promise((r) => setTimeout(r, 0)); await card.updateComplete; };
  const clicked: string[] = [];

  beforeEach(() => {
    clicked.length = 0;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.getAttribute("href") || "");
    });
    card = new JunieRemoteCard(); document.body.appendChild(card);
  });
  afterEach(() => { card.remove(); vi.restoreAllMocks(); });

  it("fetches local transcripts through hass.fetchWithAuth, never plain fetch", async () => {
    const plain = vi.spyOn(globalThis, "fetch");
    const fetchWithAuth = vi.fn().mockResolvedValue(ok());
    card.setConfig(config("sensor.a"));
    card.hass = { states: { "sensor.a": entity("sensor.a", `${LOCAL}/json?t=1`) }, callService: vi.fn(), fetchWithAuth };
    await flush();
    expect(fetchWithAuth).toHaveBeenCalledWith(`${LOCAL}/json?t=1`, { cache: "no-store" });
    expect(plain).not.toHaveBeenCalled();
    expect(card.shadowRoot?.textContent).toContain("secret prompt");
  });

  it("keeps plain no-store fetch for S3/CDN URLs and signed URLs", async () => {
    const plain = vi.spyOn(globalThis, "fetch").mockResolvedValue(ok());
    const fetchWithAuth = vi.fn();
    const url = "https://bucket.s3.example/junie/host/latest.json?X-Amz-Signature=abc";
    card.setConfig(config("sensor.a"));
    card.hass = { states: { "sensor.a": entity("sensor.a", url) }, callService: vi.fn(), fetchWithAuth };
    await flush();
    expect(plain).toHaveBeenCalledWith(url, { cache: "no-store" });
    expect(fetchWithAuth).not.toHaveBeenCalled();
  });

  it("explains 403 and fails closed without authenticated fetch", async () => {
    const plain = vi.spyOn(globalThis, "fetch");
    card.setConfig(config("sensor.a"));
    card.hass = {
      states: { "sensor.a": entity("sensor.a", `${LOCAL}/json?t=1`) }, callService: vi.fn(),
      fetchWithAuth: vi.fn().mockResolvedValue(new Response("nope", { status: 403 })),
    };
    await flush();
    expect(card.shadowRoot?.textContent).toContain("Administrator access is required");

    const other = new JunieRemoteCard(); document.body.appendChild(other);
    other.setConfig(config("sensor.a"));
    other.hass = { states: { "sensor.a": entity("sensor.a", `${LOCAL}/json?t=1`) }, callService: vi.fn() };
    await new Promise((r) => setTimeout(r, 0)); await other.updateComplete;
    expect(other.shadowRoot?.textContent).toContain("authenticated fetch is unavailable");
    expect(plain).not.toHaveBeenCalled();
    other.remove();
  });

  it("signs a short-lived download link on demand and never stores it", async () => {
    const callWS = vi.fn().mockResolvedValue({ path: `${LOCAL}/md?t=1&download=1&authSig=SIG` });
    const states = { "sensor.a": entity("sensor.a", `${LOCAL}/json?t=1`, `${LOCAL}/md?t=1`) };
    card.setConfig(config("sensor.a"));
    card.hass = { states, callService: vi.fn(), callWS, fetchWithAuth: vi.fn().mockResolvedValue(ok()) };
    await flush();
    const buttons = card.shadowRoot!.querySelectorAll<HTMLButtonElement>(".transcript-download");
    expect(buttons.length).toBe(2);
    expect(callWS).not.toHaveBeenCalled();
    buttons[1].click(); await flush();
    expect(callWS).toHaveBeenCalledWith({ type: "auth/sign_path", path: `${LOCAL}/md?t=1&download=1`, expires: 30 });
    expect(clicked).toEqual([`${LOCAL}/md?t=1&download=1&authSig=SIG`]);
    expect(JSON.stringify(states)).not.toContain("authSig");
    expect(card.shadowRoot?.innerHTML).not.toContain("authSig");
  });

  it("downloads S3 URLs directly without signing and reports signing failures", async () => {
    const s3 = "https://cdn.example/junie/host/latest.md";
    const callWS = vi.fn().mockRejectedValue(new Error("sign failed"));
    card.setConfig(config("sensor.a"));
    card.hass = {
      states: { "sensor.a": entity("sensor.a", s3.replace(".md", ".json"), s3) },
      callService: vi.fn(), callWS, fetchWithAuth: vi.fn(),
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(ok());
    await flush();
    card.shadowRoot!.querySelectorAll<HTMLButtonElement>(".transcript-download")[1].click(); await flush();
    expect(callWS).not.toHaveBeenCalled();
    expect(clicked).toEqual([s3]);

    card.hass = {
      states: { "sensor.a": entity("sensor.a", `${LOCAL}/json?t=2`, `${LOCAL}/md?t=2`) },
      callService: vi.fn(), callWS, fetchWithAuth: vi.fn().mockResolvedValue(ok()),
    };
    await flush();
    card.shadowRoot!.querySelectorAll<HTMLButtonElement>(".transcript-download")[1].click(); await flush();
    expect(card.shadowRoot?.textContent).toContain("sign failed");
    expect(clicked).toEqual([s3]);
  });

  it("drops a signing completion that arrives after the entity changed", async () => {
    let resolve!: (v: { path: string }) => void;
    const callWS = vi.fn(() => new Promise<{ path: string }>((r) => { resolve = r; }));
    const hass = {
      states: {
        "sensor.a": entity("sensor.a", `${LOCAL}/json?t=1`, `${LOCAL}/md?t=1`),
        "sensor.b": entity("sensor.b", null),
      },
      callService: vi.fn(), callWS, fetchWithAuth: vi.fn().mockResolvedValue(ok()),
    };
    card.setConfig(config("sensor.a")); card.hass = hass; await flush();
    card.shadowRoot!.querySelectorAll<HTMLButtonElement>(".transcript-download")[1].click();
    card.setConfig(config("sensor.b")); await flush();
    resolve({ path: `${LOCAL}/md?authSig=OLD` }); await flush();
    expect(clicked).toEqual([]);
  });
});
