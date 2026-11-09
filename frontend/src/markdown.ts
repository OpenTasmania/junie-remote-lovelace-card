// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Peter Lawler

import { html, TemplateResult } from "lit";
import { unsafeHTML } from "lit/directives/unsafe-html.js";
import { FileChangeSummary } from "./types";

/**
 * Escapes HTML characters in a string to prevent XSS.
 */
export function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Validates and sanitizes a link URL.
 */
function sanitizeUrl(rawUrl: string): string | null {
  const trimmed = rawUrl.trim();
  if (!trimmed) {
    return null;
  }
  const lower = trimmed.toLowerCase();
  if (
    lower.startsWith("javascript:") ||
    lower.startsWith("vbscript:") ||
    lower.startsWith("data:")
  ) {
    return null;
  }
  if (
    lower.startsWith("http://") ||
    lower.startsWith("https://") ||
    lower.startsWith("mailto:") ||
    lower.startsWith("/") ||
    lower.startsWith("#") ||
    lower.startsWith("./")
  ) {
    return escapeHtml(trimmed);
  }
  return null;
}

/**
 * Parses inline markdown: bold, italic, code, strikethrough, links.
 */
export function parseInlineMarkdown(text: string): string {
  // Extract and placeholder inline code first to prevent inner formatting
  const codePlaceholders: string[] = [];
  let processed = text.replace(/`([^`]+)`/g, (_, code) => {
    const idx = codePlaceholders.length;
    codePlaceholders.push(`<code>${escapeHtml(code)}</code>`);
    return `\uE000INLINECODE${idx}\uE000`;
  });

  // Escape the remaining non-code text
  processed = escapeHtml(processed);

  // Links: [label](url)
  processed = processed.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    (_, label, rawUrl) => {
      const safe = sanitizeUrl(rawUrl);
      if (safe) {
        return `<a href="${safe}" target="_blank" rel="noopener noreferrer">${label}</a>`;
      }
      return label;
    }
  );

  // Bold & Italic: ***text*** or ___text___
  processed = processed.replace(
    /\*\*\*([^*]+)\*\*\*/g,
    "<strong><em>$1</em></strong>"
  );
  processed = processed.replace(/___([^_]+)___/g, "<strong><em>$1</em></strong>");

  // Bold: **text** or __text__
  processed = processed.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  processed = processed.replace(/__([^_]+)__/g, "<strong>$1</strong>");

  // Italic: *text* or _text_
  processed = processed.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  processed = processed.replace(/_([^_]+)_/g, "<em>$1</em>");

  // Strikethrough: ~~text~~
  processed = processed.replace(/~~([^~]+)~~/g, "<del>$1</del>");

  // Restore inline code placeholders
  codePlaceholders.forEach((codeHtml, idx) => {
    processed = processed.replace(`\uE000INLINECODE${idx}\uE000`, codeHtml);
  });

  return processed;
}

/**
 * Converts markdown text into sanitized HTML.
 */
export function markdownToHtml(markdown: string): string {
  if (!markdown) {
    return "";
  }

  // Normalize line breaks
  const raw = markdown.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = raw.split("\n");
  const output: string[] = [];

  let inCodeBlock = false;
  let codeBlockLang = "";
  let codeBlockLines: string[] = [];

  let inList: "ul" | "ol" | null = null;
  let inBlockquote = false;
  let blockquoteLines: string[] = [];

  const closeList = () => {
    if (inList) {
      output.push(`</${inList}>`);
      inList = null;
    }
  };

  const closeBlockquote = () => {
    if (inBlockquote) {
      const content = blockquoteLines.map(parseInlineMarkdown).join("<br/>");
      output.push(`<blockquote>${content}</blockquote>`);
      inBlockquote = false;
      blockquoteLines = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Fenced code block detection (```lang)
    const codeFenceMatch = line.match(/^```(\w+)?/);
    if (codeFenceMatch) {
      if (!inCodeBlock) {
        closeList();
        closeBlockquote();
        inCodeBlock = true;
        codeBlockLang = codeFenceMatch[1] || "code";
        codeBlockLines = [];
        continue;
      } else {
        // End of code block
        inCodeBlock = false;
        const codeText = codeBlockLines.join("\n");
        const escapedCode = escapeHtml(codeText);
        const langEscaped = escapeHtml(codeBlockLang);
        output.push(
          `<div class="code-block-wrapper">` +
            `<div class="code-header">` +
            `<span class="code-lang">${langEscaped}</span>` +
            `<button class="copy-btn" type="button" aria-label="Copy code">Copy</button>` +
            `</div>` +
            `<pre><code class="language-${langEscaped}">${escapedCode}</code></pre>` +
            `</div>`
        );
        codeBlockLang = "";
        codeBlockLines = [];
        continue;
      }
    }

    if (inCodeBlock) {
      codeBlockLines.push(line);
      continue;
    }

    // Horizontal Rule
    if (/^(---|___|\*\*\*)$/.test(trimmed)) {
      closeList();
      closeBlockquote();
      output.push(`<hr class="markdown-hr" />`);
      continue;
    }

    // Blockquote (> text)
    if (line.startsWith(">")) {
      closeList();
      inBlockquote = true;
      blockquoteLines.push(line.replace(/^>\s?/, ""));
      continue;
    } else {
      closeBlockquote();
    }

    // Unordered List (- item, * item)
    const ulMatch = line.match(/^(\s*)[-*+]\s+(.*)$/);
    if (ulMatch) {
      if (inList !== "ul") {
        closeList();
        output.push("<ul>");
        inList = "ul";
      }
      output.push(`<li>${parseInlineMarkdown(ulMatch[2])}</li>`);
      continue;
    }

    // Ordered List (1. item)
    const olMatch = line.match(/^(\s*)\d+\.\s+(.*)$/);
    if (olMatch) {
      if (inList !== "ol") {
        closeList();
        output.push("<ol>");
        inList = "ol";
      }
      output.push(`<li>${parseInlineMarkdown(olMatch[2])}</li>`);
      continue;
    }

    // Not in a list
    closeList();

    // Headings (# h1 .. #### h4)
    const h1 = line.match(/^#\s+(.*)$/);
    if (h1) {
      output.push(`<h3>${parseInlineMarkdown(h1[1])}</h3>`);
      continue;
    }
    const h2 = line.match(/^##\s+(.*)$/);
    if (h2) {
      output.push(`<h4>${parseInlineMarkdown(h2[1])}</h4>`);
      continue;
    }
    const h3 = line.match(/^###\s+(.*)$/);
    if (h3) {
      output.push(`<h5>${parseInlineMarkdown(h3[1])}</h5>`);
      continue;
    }
    const h4 = line.match(/^####+\s+(.*)$/);
    if (h4) {
      output.push(`<h6>${parseInlineMarkdown(h4[1])}</h6>`);
      continue;
    }

    // Empty lines
    if (!trimmed) {
      continue;
    }

    // Paragraph
    output.push(`<p>${parseInlineMarkdown(line)}</p>`);
  }

  // Close any unclosed blocks
  if (inCodeBlock) {
    const codeText = codeBlockLines.join("\n");
    const escapedCode = escapeHtml(codeText);
    const langEscaped = escapeHtml(codeBlockLang || "code");
    output.push(
      `<div class="code-block-wrapper">` +
        `<div class="code-header">` +
        `<span class="code-lang">${langEscaped}</span>` +
        `<button class="copy-btn" type="button" aria-label="Copy code">Copy</button>` +
        `</div>` +
        `<pre><code class="language-${langEscaped}">${escapedCode}</code></pre>` +
        `</div>`
    );
  }
  closeList();
  closeBlockquote();

  return output.join("\n");
}

/**
 * Lit template renderer for Markdown text.
 */
export function renderMarkdown(markdown: string): TemplateResult {
  const htmlStr = markdownToHtml(markdown);
  return html`<div class="markdown-body">${unsafeHTML(htmlStr)}</div>`;
}

/**
 * Lit template renderer for changesSummary file lists.
 */
export function renderChangesSummary(
  changes: Array<FileChangeSummary | string> | null | undefined
): TemplateResult {
  if (!changes || !Array.isArray(changes) || changes.length === 0) {
    return html``;
  }

  return html`
    <div class="changes-summary-container">
      <div class="changes-summary-title">📁 Changed Files:</div>
      <div class="changes-summary-badges">
        ${changes.map((item) => {
          let path = "";
          let action = "modified";
          let added: number | undefined;
          let deleted: number | undefined;

          if (typeof item === "string") {
            path = item;
          } else if (item && typeof item === "object") {
            path = item.path || item.file || "";
            action = item.action || "modified";
            added = item.added;
            deleted = item.deleted;
          }

          const actionClass =
            action === "created" || action === "added"
              ? "action-created"
              : action === "deleted" || action === "removed"
              ? "action-deleted"
              : action === "renamed"
              ? "action-renamed"
              : "action-modified";

          return html`
            <span class="change-badge ${actionClass}">
              <span class="change-action">${action}</span>
              <span class="change-path">${path}</span>
              ${added !== undefined
                ? html`<span class="change-diff added">+${added}</span>`
                : ""}
              ${deleted !== undefined
                ? html`<span class="change-diff deleted">-${deleted}</span>`
                : ""}
            </span>
          `;
        })}
      </div>
    </div>
  `;
}
